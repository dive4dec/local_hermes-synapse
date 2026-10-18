# CodeRunner file-dependent questions — E-Quiz 7 / CE-Quiz 7 case (2026-09-24)

Confirmed live bug found while reviewing the E-Quiz 4+ / CE-Quiz 3+ bank
(13 quizzes, 116 unique deployed questions). One of the 3 raw-harness
failures turned out to be a REAL bug of a new pattern: the question's tests
read files that the sandbox never provides.

## The questions

- qid 3881 `read_first_line` (E-Quiz 7, slot 12, 2 marks, deployed v4 of
  entry 1032) — test1/test2 call `read_first_line("file1.txt")` /
  `read_first_line("file2.txt")`. Expected: `First line.\n` /
  `About with statement:\n`.
- qid 3883 `read_lines - generator` (E-Quiz 7 slot 16 + CE-Quiz 7 slot 2,
  2 + 1 mark, deployed v2 of entry 1033) — test2 reads `file2.txt` expecting
  the 4 lines "About with statement:" / "The with statement applies to any
  context manager that provides the methods" / "__enter__ for initialization,
  and" / "__exit__ for finalization.".
- Both tests 1/3 create their own files (test1 writes `test1.txt`, test3
  generates a random `testcase3.txt`/`test.txt`) — only the `file1.txt` /
  `file2.txt` reads assume pre-existing files. Neither test creates them.

## Why the raw harness is double-blind

- Harness WITHOUT the files → `FileNotFoundError` → looks like a bug.
- Harness WITH the files I supply → model answer passes → looks fine.
- Neither is conclusive about the live sandbox. You must establish what the
  sandbox itself provides.

## What the sandbox actually provides (this fork)

- Sandbox = **Jobe** (`mdl_config_plugins` plugin `qtype_coderunner`:
  `jobesandbox_enabled=1`, `ideonesandbox_enabled=0`).
- File seeding path: `jobrunner.php` sets
  `$this->files = array_merge($attachments, $question->get_files());`
  → sandbox `load_files()` writes exactly those files into a fresh temp
  working dir (`tempnam("/tmp","coderunner_")`). Nothing else is seeded.
- `$attachments` = files the STUDENT attached to their answer (empty on these
  questions — attachments disabled).
- `get_files()` = `get_support_files(prototype) + get_support_files(question)`,
  each reading `get_area_files($contextid, 'qtype_coderunner', 'datafile',
  $question->id)`.

## The definitive check (PHP)

```php
// Support files actually attached to a question:
$fs = get_file_storage();
$files = $fs->get_area_files($ctx->id, 'qtype_coderunner', 'datafile', $qid);
```

Result here: **zero rows** for 3881, 3883, AND for all three
`python3_CS1302_prototype` candidates (qids 10659 ctx 969, 4282 ctx 609,
4281 ctx 18 — course 3 resolves to ctx 609). Contrast: this was the ONE
coderunner file mechanism that checks out; the naive
`component='core_question' AND filearea='files'` check (standard Moodle)
also returns empty and CANNOT distinguish "no files" from "wrong area" —
always use the `qtype_coderunner`/`datafile` area.

Resolve the active prototype for a course:

```sql
SELECT q.id, qv.version, qc.contextid
FROM mdl_question_coderunner_options qco
JOIN mdl_question q ON q.id=qco.questionid
JOIN mdl_question_versions qv ON qv.questionid=q.id
JOIN mdl_question_bank_entries qbe ON qbe.id=qv.questionbankentryid
JOIN mdl_question_categories qc ON qc.id=qbe.questioncategoryid
WHERE qco.prototypetype<>0 AND qco.coderunnertype='python3_CS1302_prototype'
  -- then pick the one whose category context is available in the quiz context
```

## The decisive proof: historical attempt data

The same two questions existed in earlier semesters (same entry families):
old versions qids 1754/1756 (deployed in quizzes 32/33), and a newer set
10263-10268 (quiz 167). Query:

```sql
SELECT qa.questionid, COUNT(*) n, AVG(qa.minfraction) avgf,
       SUM(qa.minfraction >= 0.99) fullmark, SUM(qa.minfraction < 0.01) zeromark
FROM mdl_question_attempts qa
WHERE qa.questionid IN (...) GROUP BY qa.questionid;
```

Result: **389 attempts on 1754, 773 on 1756, avg fraction 0.000, 0 full
marks, 0 partial** — students have literally never scored on this question in
any semester. The files never existed in the production sandbox. Confirmed
bug, and the grading impact is historical (whole-quiz zero for the question
in every prior run).

## Do NOT do (wasted ~15 tool calls this session)

Trying to drive the live pipeline from CLI: `qtype_coderunner_question`
constructed manually + `grade_response($response, false, isvalidationrun=true)`.
On this 5.2 fork it needs: `question/engine/bank.php` (NOT
`lib/questionbank/lib.php` — doesn't exist), plus
`question/behaviour/behaviourbase.php` + `question/behaviour/adaptive/
behaviour.php` for `question_behaviour_with_multiple_tries` (the "multitries"
behaviour was folded into behaviourbase in 5.2; there is no
`question/behaviour/multitries/` directory). Even then, hydrating the class
instance from plain DB objects is fiddly. The static DB evidence above
reaches the same conclusion in 4 cheap queries. Only go the live-PHP route if
the question is NEW (no predecessor versions to query).

## Fix options to present to the instructor (none applied)

1. Attach `file1.txt` / `file2.txt` as support files to the question (or
   prototype) with the exact expected contents — makes tests pass as written.
2. Rewrite test1/test2 to create the files themselves (mirroring what
   test1/test3 of 3883 already do).
3. Drop the file-based shown tests entirely.
Option 2 is the least fragile (no binary/text attachment to keep in sync
across re-versions); the question family has a proven record of being
re-versioned, so any fix must be applied to the DEPLOYED version (entry 1032
v4 / entry 1033 v2), not the entry's other versions.
