# cs1302_25b Question Bank Diagnostic (2026-07-26)

## Context structure discovered

Course `cs1302_25b` (course id=2) contexts:
- `id=5`: contextlevel=30 (category), instanceid=2, path=/1/5
- `id=7`: contextlevel=80 (block), instanceid=2, path=/1/7
- `id=17`: contextlevel=50 (course), instanceid=2, path=/1/3/17
- `id=18`: contextlevel=70 (course-module), instanceid=2, path=/1/3/17/18

**Key finding:** Question categories for this course live under `contextid=18` (level=70, course-module), NOT under the course-level context (17, level=50). This means naive queries checking `contextlevel=50` will return 0 categories.

## Findings

| Metric | Value |
|---|---|
| Question categories (contextid=18) | 33 |
| Questions in bank | 2,127 |
| Quizzes | 37 |
| Quiz slots | 405 |
| Question references to slots | **0** |
| Orphaned slots | **405** (all of them) |
| Quiz attempts | 15,244 |

## Schema corrections confirmed

- `mdl_question_bank_entries.questioncategoryid` (NOT `questionarea`)
- `mdl_context.instanceid` (NOT `courseid`)
- `mdl_quiz_slots` has NO `questionid` column
- `mdl_quiz_sections` has NO `layout` JSON column (older Moodle schema)

## Diagnostic path

1. List courses → find courseid
2. Find contexts for course: `SELECT * FROM mdl_context WHERE instanceid = <id> OR path LIKE '%/50/<id>/%'`
3. Find question categories: check WHICH contextid hosts them (may not be level 50)
4. Count questions: join `mdl_question` → `mdl_question_versions` → `mdl_question_bank_entries` → filter by `questioncategoryid`
5. Check quiz slots: `mdl_quiz_slots.quizid` → `mdl_quiz.course`
6. Check references: `mdl_question_references` WHERE `component='mod_quiz' AND questionarea='slots' AND itemid=slot_id`

## Issue

All 405 quiz slots across all 37 quizzes have `questionbankentryid = NULL` — no question_references link any slot to a question. The question bank itself (2,127 questions) is intact and healthy.
