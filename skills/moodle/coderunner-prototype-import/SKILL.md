---
name: coderunner-prototype-import
description: "Fixes missing Code Runner prototype errors by importing prototype questions via direct SQL inserts. Used when a template backup excluded system-level prototypes."
---

# Code Runner Prototype Import

## When to use this skill

Trigger when Code Runner questions show: *"Broken question (missing or duplicate prototype 'python3_CS1302_prototype'). Cannot be run."*

This happens when:
- A `--template` backup was used (excludes system-level prototypes)
- The prototype lived at the system level (`CR_PROTOTYPES` category, id=2, contextid=12)
- The restore doesn't include system-level questions

## Context matters for course-level prototypes

Code Runner's `get_prototype()` only searches specific question bank contexts determined by `prototype_contexts()`. For Moodle 5.2+, this searches the frontpage qbank context + question bank activity instances linked to the course. **Not all course-level contexts are searched.**

To find which contexts are searched for a course:
```bash
moosh php-eval "
\$m = new ReflectionMethod('qtype_coderunner', 'prototype_contexts');
\$m->setAccessible(true);
\$ctx = context_course::instance(COURSE_ID);
echo implode(',', \$m->invoke(null, \$ctx));
"
```

When creating a course-level prototype category, set `contextid` to one of the searched contexts.

## Root Cause

Code Runner's `get_prototype()` SQL joins through **four** tables:

```
mdl_question_coderunner_options
  → mdl_question
  → mdl_question_versions
  → mdl_question_bank_entries
  → mdl_question_categories
```

A naive `INSERT INTO mdl_question` only creates the question row but misses `question_bank_entries` and `question_versions`, so the join returns 0 results.

## Fix: Complete SQL Insert via `moosh sql-run`

All commands use `moosh -p /var/www/html/public -n sql-run "..."`.

### Step 1: Delete any stale placeholder

```bash
moosh sql-run "DELETE FROM mdl_question_coderunner_tests WHERE questionid = OLD_ID"
moosh sql-run "DELETE FROM mdl_question_coderunner_options WHERE questionid = OLD_ID"
moosh sql-run "DELETE FROM mdl_question_versions WHERE questionid = OLD_ID"
moosh sql-run "DELETE FROM mdl_question_bank_entries WHERE id = OLD_ID"
moosh sql-run "DELETE FROM mdl_question WHERE id = OLD_ID"
```

### Step 2: Insert `mdl_question`

```bash
moosh sql-run "
INSERT INTO mdl_question (parent, name, questiontext, questiontextformat,
  generalfeedback, generalfeedbackformat, defaultmark, penalty, qtype, length,
  stamp, timecreated, timemodified, createdby, modifiedby)
VALUES (0, 'python3_CS1302_prototype', '# Prototype of python3 for CS1302', 0,
  '', 0, 1, 0, 'coderunner', 1, 'manual-$(date +%s)', UNIX_TIMESTAMP(), UNIX_TIMESTAMP(), 2, 2)
"
```

- **`parent=0`** — even for prototype questions. The category linkage goes through `mdl_question_bank_entries`, not the legacy `parent` field. Setting `parent` to the category ID breaks the question bank UI.
- **Do NOT specify `id`** — let the DB auto-increment. The question ID will be a new value, different from the category and entry IDs.

### Step 3: Insert `mdl_question_coderunner_options`

Key fields to match the original XML:
- `prototypetype=1` (user-defined prototype, visible in question bank AND found by Code Runner)
- `iscombinatortemplate=1` (required for the prototype template to work — does NOT hide the question when `prototypetype=1`)
- `language`, `grader`, `template`, `testsplitterre` from the XML

```bash
moosh sql-run "
INSERT INTO mdl_question_coderunner_options (questionid, coderunnertype, prototypetype,
  allornothing, showsource, precheck, hidecheck, answerboxlines, answerboxcolumns,
  answerpreload, useace, penaltyregime, validateonsave, template, iscombinatortemplate,
  allowmultiplestdins, testsplitterre, language, grader, hoisttemplateparams,
  extractcodefromjson, templateparamslang, templateparamsevalpertry, templateparamsevald,
  twigall, uiplugin, attachments, attachmentsrequired, maxfilesize, displayfeedback,
  giveupallowed)
VALUES (NEW_QUESTION_ID, 'python3_CS1302_prototype', 1, 0, 0, 2, 0, 18, 100, '# YOUR CODE HERE',
  1, '10, 20, ...', 1, 'YOUR_TEMPLATE_HERE', 1, 0,
  '|YOUR_TEST_SPLITTER|ms', 'python3', 'EqualityGrader', 1, 1, 'None', 0, '{}',
  0, 'ace', 0, 0, 10240, 1, 0)
"
```

### Step 4: Insert `mdl_question_bank_entries` (CRITICAL)

This is the table most commonly forgotten. **Let the DB auto-increment the ID** — it will be different from the question ID:

```bash
moosh sql-run "
INSERT INTO mdl_question_bank_entries (questioncategoryid) VALUES (YOUR_CATEGORY_ID)
"
```

### Step 5: Insert `mdl_question_versions` (CRITICAL)

Link the separate question ID and entry ID together:

```bash
moosh sql-run "
INSERT INTO mdl_question_versions (questionbankentryid, version, questionid, status)
VALUES (NEW_ENTRY_ID, 1, NEW_QUESTION_ID, 'ready')
"
```

### Step 6: Insert test cases (if the prototype has any)

One call per test case:

```bash
moosh sql-run "
INSERT INTO mdl_question_coderunner_tests (questionid, testtype, testcode, stdin,
  expected, useasexample, display, hiderestiffail, mark)
VALUES (4274, 0, 'test_code', 'stdin_text', 'expected_output', 1, 'SHOW', 0, 1)
"
```

## Verification

### Test prototype is discoverable via PHP:

```bash
moosh php-eval "
\$coursectx = context_course::instance(COURSE_ID);
\$qtype = new qtype_coderunner();
echo var_export(\$qtype->get_prototype('python3_CS1302_prototype', \$coursectx, true), true);
"
```

Should return `true`.

### Or run Code Runner's exact SQL:

```bash
moosh sql-run "
SELECT q.id, q.name FROM mdl_question_coderunner_options qco
JOIN mdl_question q ON qco.questionid = q.id
JOIN mdl_question_versions qv ON qv.questionid = q.id
JOIN mdl_question_bank_entries qbe ON qv.questionbankentryid = qbe.id
JOIN mdl_question_categories qc ON qc.id = qbe.questioncategoryid
WHERE qv.version = (SELECT MAX(v.version) FROM mdl_question_versions v
  JOIN mdl_question_bank_entries be ON be.id = v.questionbankentryid
  WHERE be.id = qbe.id)
AND qco.prototypetype != 0
AND qc.contextid IN (1, 12)
AND qco.coderunnertype = 'python3_CS1302_prototype'
"
```

## How Code Runner Finds Prototypes (Context Search)

Code Runner's `get_prototype()` calls a **private** `prototype_contexts()` method to determine which contexts to search. This is the most critical concept for understanding why a prototype may not be found even when the database is correct.

For **Moodle 5.2+** (when `qtype_coderunner_util::using_mod_qbank()` returns true), `prototype_contexts()` uses `question_bank_helper` and only searches:
1. The **frontpage question bank** context (contextid=12)
2. Any **question bank activity instances** linked to the course

It does **NOT** automatically search the course-level question bank context (contextlevel=50). A prototype placed in a course-level category may not be found — you must check which contexts are actually searched.

### Inspecting searched contexts (reflection required)

The method is private, so use reflection:

```bash
moosh php-eval "
\$m = new ReflectionMethod('qtype_coderunner', 'prototype_contexts');
\$m->setAccessible(true);
\$ctx = context_course::instance(COURSE_ID);
echo implode(',', \$m->invoke(null, \$ctx)) . PHP_EOL;
"
```

If your prototype's category contextid is NOT in the returned list, move the category to one that is:

```bash
moosh sql-run "UPDATE mdl_question_categories SET contextid = SEARCHED_CONTEXT_ID WHERE id = YOUR_CATEGORY_ID"
```

### Why course-level prototypes still work

In Moodle 5.2+, each course may have question bank activity instances whose contexts **do** appear in the search list. The course-level context (e.g., contextid=18 for cs1302_25b) often IS in the list because it's the context of the default question bank. But a fresh course may only have context IDs like 609, 616, etc. — so always verify.

### No conflict between same-named prototypes in different courses

Each course's `prototype_contexts()` returns an isolated set of context IDs. When course A looks for a prototype, it only sees prototypes in course A's contexts. Course B's prototype is invisible.

### Code Runner upgrade safety

Upgrades **only** delete built-in prototypes whose names start with `BUILTIN_PROTOTYPE_` (see `upgradelib.php` line 276: `WHERE q.name LIKE 'BUILT%IN_PROTOTYPE_%'`). User-defined prototypes are **never** deleted by upgrades.

The `CR_PROTOTYPES` category name is just a convention — `get_prototype()` filters by **contextid**, not category name. A prototype in any category within a searched context will be found.

## Best Practice: Course-Level Prototypes

Place prototypes in a **course-level question category** so they're included in course backups (including `--template` backups):

1. Create a category under the course's question bank context (same `contextid` as the course's `top` category)
2. Insert the prototype into that category — `parent=0` (NOT the category ID), and `questioncategoryid=YOUR_CATEGORY_ID` in `mdl_question_bank_entries`
3. Verify the category's contextid appears in `prototype_contexts()` — if not, move the category

## Related: Math delimiter conversion

Code Runner questions often use `$...$` for inline math, which MathJax 3 doesn't render by default. See the `moodle-math-delimiter-fix` skill for the PHP-based conversion workflow.

## Prototype visibility in the question bank UI

**`prototypetype` controls BOTH visibility and prototype discovery:**
- `0` — visible in question bank, but **NOT** found by `get_prototype()` (SQL requires `prototypetype != 0`). Setting this breaks all questions that reference the prototype.
- `1` — **visible** in question bank, **found** by `get_prototype()`. Built-in prototypes use this.
- `2` — **hidden** from question bank, found by `get_prototype()`. Makes prototypes invisible in the UI, impossible to edit.

Built-in Code Runner prototypes (`BUILTIN_PROTOTYPE_*`) are stored at the system level with `prototypetype=1`.

**Course-level prototypes should use `prototypetype=2`** (hidden from UI, found by `get_prototype()`) matching the user's working configuration. The user created their prototypes this way and it works correctly. `iscombinatortemplate=1` must also be set for the template to function.

If you discover hidden prototypes that need to be made visible:
```bash
moosh sql-run "UPDATE mdl_question_coderunner_options SET prototypetype=1 WHERE questionid IN (QUESTION_IDS)"
```

**Critical: `mdl_question.id` ≠ `mdl_question_bank_entries.id`** — Moodle auto-assigns separate IDs for each table. Do NOT force them to be the same value. Let the DB auto-increment both. The linkage is:
- `mdl_question.id` → `mdl_question_versions.questionid`
- `mdl_question_bank_entries.id` → `mdl_question_versions.questionbankentryid`
- `mdl_question_bank_entries.questioncategoryid` → `mdl_question_categories.id`

**`mdl_question.parent` = 0** — even for prototype questions. The category is resolved via `mdl_question_bank_entries.questioncategoryid`, not the legacy `parent` field. Setting `parent` to the category ID breaks the question bank UI.

## Pitfalls

1. **`moosh sql-run` only supports single statements** — no `SET @var`, no multi-statement SQL. One call per INSERT.
1. **`moosh sql-run` is unreliable for backslash-heavy updates** — shell escaping produces inconsistent results (mix of `\(r\)` and `\\(h\\)` in the same row). Use a PHP script with `$DB->update_record()` instead.
2. **Duplicate `question_coderunner_options` rows** — if you retry, check for duplicates:
   ```bash
   moosh sql-run "SELECT id, questionid, prototypetype FROM mdl_question_coderunner_options WHERE questionid = 4274"
   ```
   Delete extras: `DELETE FROM mdl_question_coderunner_options WHERE questionid = 4274 AND prototypetype = <wrong>`
3. **`question_bank_entries` is the missing link** — without it, Code Runner's join returns nothing. Always insert this table.
4. **`prototypetype` values**: 0 = visible but not found by Code Runner (breaks prototype lookup), 1 = visible AND found, 2 = hidden from UI but found. The user's working course prototypes use `prototypetype=2`. If you need prototypes to be visible in the UI, set to `1`. NEVER set to `0`.
5. **`idnumber` unique constraint** — `mdl_question_categories` has a unique index on `(contextid, idnumber)`. If you get `Duplicate entry` errors, omit `idnumber` (let it be NULL) or use a unique value.
6. **`info` column has no default** — always include `info=''` in your INSERT for `mdl_question_categories`.
7. **Context search mismatch** — for Moodle 5.2+, `prototype_contexts()` may not include the course-level context. Always verify which contexts are actually searched and place your prototype category in one of them.
8. **OPcache** — after inserting, PHP-FPM may still return cached "not found". Clear Moodle cache via `moosh cache-clear`. If that's insufficient, PHP-FPM needs a restart (may require pod restart in Kubernetes).
9. **`iscombinatortemplate=1` does NOT hide questions** when `prototypetype=1` or `prototypetype=2`. The user's working course prototypes use `prototypetype=2` AND `iscombinatortemplate=1` and are found by `get_prototype()` without issue. Only `prototypetype=2` controls UI visibility (hidden). `iscombinatortemplate=1` is required for the prototype template to function correctly.
10. **Category parent and contextid must be in the same context tree** — a question category's `parent` must be a category that shares the same `contextid`. If parent category has `contextid=510` but child category has `contextid=609`, Moodle will not display the child's questions. Always verify:
    ```sql
    SELECT qc.id, qc.name, qc.contextid, qc.parent, pc.contextid AS parent_contextid
    FROM mdl_question_categories qc
    JOIN mdl_question_categories pc ON qc.parent = pc.id
    WHERE qc.id = YOUR_CATEGORY_ID
    ```
    The `contextid` and `parent_contextid` must match.
11. **`mdl_question.parent` = 0 for all questions** — including prototypes. The category linkage goes through `mdl_question_bank_entries.questioncategoryid`. Setting `parent` to the category ID breaks the question bank UI. Code Runner's `get_prototype()` joins through `question_bank_entries`, not `parent`.
12. **Verify by looking, not just querying** — after fixing prototype visibility, actually open the question bank URL (`/question/edit.php?cat=CATEGORY_ID,CONTEXT_ID&cmid=CMID`) to confirm questions render. A DB row with `status='ready'` does not guarantee UI visibility. Always check the link includes the `cmid` parameter.
