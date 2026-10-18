---
name: moodle-question-course-mapping
description: "Correctly maps Moodle questions to their courses via the versioning chain and context paths. Avoids common pitfalls like using mdl_question.parent or joining coderunner_options."
---

# Moodle Question-to-Course Mapping

## When to use

When you need to find, list, or analyze questions in a specific course, or verify which course a question belongs to.

## The correct query chain

Questions do **not** link to courses directly. The full chain is:

```
mdl_question
  → mdl_question_versions (by questionid)
  → mdl_question_bank_entries (by questionbankentryid)
  → mdl_question_categories (by questioncategoryid)
  → mdl_context (by contextid)
  → mdl_course (by instanceid)
```

### Find questions by course

```sql
SELECT q.id, q.name, qc.name AS categoryname, ctx.contextid
FROM mdl_question q
JOIN mdl_question_versions qv ON qv.questionid = q.id
JOIN mdl_question_bank_entries qbe ON qbe.id = qv.questionbankentryid
JOIN mdl_question_categories qc ON qc.id = qbe.questioncategoryid
JOIN mdl_context ctx ON ctx.id = qc.contextid
WHERE q.qtype = 'coderunner'
  AND ctx.contextlevel = 70
  AND ctx.instanceid = <course_id>
```

Or by contextid directly (more reliable):

```sql
-- Replace with the course's contextid (e.g. 18 for <course>_25b, 609 for <coursecode>)
SELECT q.id, q.name, qc.name
FROM mdl_question q
JOIN mdl_question_versions qv ON qv.questionid = q.id
JOIN mdl_question_bank_entries qbe ON qbe.id = qv.questionbankentryid
JOIN mdl_question_categories qc ON qc.id = qbe.questioncategoryid
WHERE q.qtype = 'coderunner'
  AND qc.contextid = <contextid>
```

## Find a course's contextid

```sql
SELECT id, contextlevel, instanceid FROM mdl_context
WHERE contextlevel = 70 AND instanceid = <course_id>
```

Known contextids:
- <course>_25b (course id=2): contextid=18
- <coursecode> (course id=3): contextid=609

## Pitfalls

1. **NEVER use `mdl_question.parent`** — it's a legacy field that is often `0`. The real category link is through `mdl_question_bank_entries.questioncategoryid`.

2. **NEVER join `mdl_question_coderunner_options`** to find coderunner questions. Some coderunner questions have `qtype='coderunner'` but no row in `coderunner_options` (the options table is created lazily when first saved, and cloned questions can also be missing this row). Joining it silently drops those questions — an entire clone's questions were missed this way, producing a wrong count of 967 instead of the true 1,047. Always use `q.qtype = 'coderunner'` instead.

3. **NEVER use path-based heuristics** like `path LIKE '/1/3/17%'` — context paths are fragile and can be off-by-one. Use `qc.contextid = <known_contextid>` directly.

4. **Question versions** — always join `mdl_question_versions`. The latest version is determined by `MAX(v.version)` per questionbankentryid.

5. **Don't assume 1:1 category names across courses** — categories with the same name can exist in both courses and contain different questions.

6. **`mdl_question.id` ≠ `mdl_question_bank_entries.id`** — they are separate auto-incremented values. When joining, go through `mdl_question_versions`: `q.id = qv.questionid AND qv.questionbankentryid = qbe.id`. Joining `q.id = qbe.id` directly produces wrong results.

7. **Cloned courses may live under a context whose `instanceid` points to a deleted course.** After cloning, the clone's categories often have a `contextid` whose `mdl_context.instanceid` points to the old course (which may have been deleted). Don't trust `instanceid` alone to find questions — use the actual `contextid` as the authoritative anchor. A query filtering by `ctx.instanceid = <course_id>` will miss cloned questions entirely.