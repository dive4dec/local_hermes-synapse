---
name: coderunner-question-creation
description: Create Code Runner (python3) questions for mock exams / quizzes in the <coursecode> course bank on this Moodle 5.x fork. Covers where mock-exam questions live (qbank activity + per-exam categories), the two question "generations" (bare-python3/assert vs the <coursecode> prototype style), the three-table anatomy, the versioning model (each edit = a new question row, live = max version per entry), the verified hand-authored-XML import path (single AND bulk — generator-verify-emit), and the build's modified-schema gotchas. Use when asked to "create/add a code runner question" or "write a mock-exam question". Creation verified on the reference course (a new exam category + 19 questions).
---

# Code Runner question creation (mock exams / quizzes)

Build `qtype=coderunner` questions into the course question bank on this Moodle 5.x fork. This box runs `<coursecode>` — two course shells: course `<cid>` = `<coursecode>` (ref code `cs1302a_26a`) and course `<other-cid>` = `<other-coursecode>` (ref code `cs1302_25b`). Distinguish from the siblings: `coderunner-prototype-import` = *repair* a missing prototype; `moodle-quiz-question-review` = *validate* existing questions; this one = *author new* questions.

## The two "generations" — know which you're building (the key distinction)

Mock-exam questions come in two styles. **Replicate the NEWER one (Sem B) for new work** — it's what the instructor is currently doing.

| | Older — e.g. "<coursecode> Exam 25/26 **Sem A**" | Newer — "<coursecode> Exam 25/26 **Sem B**" ← build this |
|---|---|---|
| `coderunner_options.coderunnertype` | `python3` (bare built-in) | `python3_<coursecode>_prototype` (custom prototype) |
| Test style | **assert-based** `testcode` (e.g. `assert midpoint((1,1),(2,2))==(1.5,1.5)`), `stdin`/`expected` empty | **stdin → expected** (e.g. stdin `5` → expected diamond), `testcode` empty |
| `template` | empty (inherited from built-in `python3`) | empty (inherited from the <coursecode> prototype) |
| Feel | function-return grading | program-with-IO grading |

Both share the same three-table anatomy and versioning model below — only `coderunnertype` and the test representation differ. **Correction from live data (2026-10-22): the current live rows of this course's Sem B cat `<cat-semB>` are mostly ASSERT-BASED** (`testcode` = `assert f(...) == …`, `stdin`/`expected` empty) — only a few (e.g. `print_diamond` (ref q4072), `testcode` = `print_diamond(5)` → `expected` output) use the stdin/expected form. The table above describes the two *styles*, not a per-category guarantee: **mimic the exact test representation of the live row you're duplicating.** The assert form works perfectly with the harness (verified: 18 assert-based questions imported + all answers/tests verified in real Python).

## Where mock-exam questions live

- A **single course-level Question Bank activity** (module `qbank`, `module` id 16 in `mdl_modules`): course `<cid>` = instance `<cid>` / cmid `<qbank-cmid>` / **contextid `<ctx-main>`** (ref: 101 / 609); course `<other-cid>` = instance `<other-cid>` / cmid `<qbank-cmid-other>` / **contextid `<ctx-other>`** (ref: 2 / 18).
- Inside it, categories are organised **by exam and term** under a `top` category. Course `<cid>` (context `<ctx-main>`): `<coursecode> Exam 25/26 Sem A` = **cat `<cat-semA>`** (ref 116), `<coursecode> Exam 25/26 Sem B` = **cat `<cat-semB>`** (ref 167), plus `<coursecode> Midterm …`, and `makeup` sub-categories. A `CR_PROTOTYPES` category (cat `<cat-proto>` under `<ctx-main>`; cat `<cat-proto-other>` under `<ctx-other>`; ref 221 / 220) holds the prototype.
- Discover the concrete category/context/CMID map for YOUR instance via the queries in **references/headless-creation-recipe.md §0** (this skill is course-specific — the reference values are noted inline as "ref: N").

## Versioning model (the surprising part — read this before touching rows)

A "question" shown in the bank is a **bank entry** (`mdl_question_bank_entries.id`), NOT an `mdl_question` row. **Each edit does NOT modify the row in place** — it appends a new version:
- a NEW `mdl_question` row (new auto-increment id, `parent=0`),
- a NEW `mdl_question_versions` row sharing the SAME `questionbankentryid` with `version` incremented, `status='ready'`.

So cat `<cat-semB>` (ref 167) shows **19 bank entries** but **127 `mdl_question` rows** (e.g. `print diamond pattern` = versions 1–9, then `print_diamond` v10–11). **The LIVE question for an entry = the highest `version` per `questionbankentryid`** (`status='ready'`).

```sql
-- the live question(s) in a category
SELECT qv.questionbankentryid, MAX(qv.version) ver, qv.questionid
FROM {question_versions} qv
JOIN {question_bank_entries} qbe ON qbe.id = qv.questionbankentryid
WHERE qbe.questioncategoryid = <catid> AND qv.status='ready'
GROUP BY qv.questionbankentryid;
```

## Three-table anatomy (one question = these rows)

1. **`mdl_question`** — `qtype='coderunner'`, `name`, `questiontext` (Moodle format; `$$…$$` math renders), `defaultmark`, `parent=0`.
2. **`mdl_question_coderunner_options`** (one row, keyed `questionid`) — engine config. Relevant fields: `coderunnertype`, `prototypetype` (0 = *uses* a named prototype; 2 = *is* a hidden prototype), `precheck` (=2 here), `allornothing` (=0), `answerpreload` (starter code shown in the box, often ends with a `# YOUR CODE HERE` line), `answer` (the **model/reference solution**, stored for reference — NOT the student's answer), `answerboxlines`/`answerboxcolumns`, `template` (leave empty; inherited), `iscombinatortemplate` (prototype rows only).
3. **`mdl_question_coderunner_tests`** (one row per test case) — `testcode`, `stdin`, `expected`, `display` (`SHOW`/`HIDE`), `useasexample` (1 on the first/visible one), `mark`.

## The prototype (what makes Sem B work)

`python3_<coursecode>_prototype` is itself a **question** (e.g. q4281/q4282/q10659) in the `CR_PROTOTYPES` category. `prototypetype=2` (hidden from UI, still discoverable) + `iscombinatortemplate=1`. Its Twig `template` is the harness: it injects `{{ STUDENT_ANSWER }}` then loops `{% for TEST in TESTCASES %}{{ TEST.testcode }}` joined by a `SEPARATOR` marker — that's how stdin/expected cases run. Newer questions just set `coderunnertype='python3_<coursecode>_prototype'` and leave `template` blank. Prototype discovery is by `coderunnertype` NAME + `prototype_contexts()` (see `coderunner-prototype-import`) — a new question does NOT need to re-create the prototype.

## Creation recipe (authoring a new Sem-B Code Runner question)

NEVER raw-insert into `mdl_question` alone — you also need `question_bank_entries` + `question_versions`, and prototype inheritance is handled by `save_question_options`/`clean_question_form`. Two safe headless paths, in order of preference — **exact snippets, bootstrap `require`s, and the full stored shape of a mimic-target live in references/headless-creation-recipe.md**:

**Path A (preferred, VERIFIED 2026-10-22 — created cat `<cat-new>` (ref 668) `<coursecode> Exam 26/27 Sem A` + `count_vowels` (ref q12797), zero corruption): hand-author the import XML → import.** Do NOT use the exporter: the fork's `qformat_xml::exportprocess()` is buggy (with `setCattofile(true)` it dies on the id-0 category dummy question, "Can't find data record in database."; `setQuestions()` needs question row **objects**, not ids; a bare `get_record('question')` row exports with ALL option fields + `<testcases>` empty because options aren't loaded; and `presave_process()` already wraps the body in `<?xml?>`+`<quiz>` so don't double-wrap). Instead: dump the **live** reference question's DB rows (`question` + `question_coderunner_options` + `question_coderunner_tests`), hand-author the XML (root `<quiz>`; a `<question type="category">` switch line — literal `/` escaped as `//` — then the `<question type="coderunner">` with **every option field explicit** + `<testcases>`), then import via the exact sequence the web UI uses (`setCatfromfile(true)` so the category line creates the category under `top`; `importpreprocess`/`importprocess`/`importpostprocess`). Two-stage: **parse-only first** — `readquestions(file($xml))`, assert 0 `importerrors` and spot-check fields/testcases (zero DB writes), then run the real import. Battle-tested code path; handles entry + version + options + tests + events.

**Path B: `save_question` form flow.** `$q = new stdClass(); $q->category=<catid>; $q->qtype='coderunner'; $q->createdby=$USER->id;` then `$question = question_bank::get_qtype('coderunner')->save_question($q, $fromform)` with `$fromform->category="<catid>,<ctxid>"` and parallel arrays `testcode[]/stdin[]/expected[]/display[]/useasexample[]/mark[]`. For a new question, `save_question` ALWAYS creates the question row + bank entry + version v1 (no separate construct step in this build).

Content checklist (either path):
1. `questiontext` (with `$$` math) + `defaultmark` (1).
2. `answerpreload` (starter, e.g. `# YOUR CODE HERE`) and `answer` (model solution).
3. `coderunnertype = python3_<coursecode>_prototype`, `precheck=2`, `allornothing=0`, `penaltyregime='10, 20, ...'`, `template` left empty (inherited — `clean_question_form` nulls it).
4. Test cases: **mimic the representation of the live row you're duplicating.** The dominant current Sem B live style is **assert-based** — `testcode` = `assert f(args) == expected`, `stdin`/`expected` empty (this is what 16/18 of the new 26/27 questions used and it verified cleanly). A minority use the function-call form (`testcode` = `print_diamond(5)`) with `expected` output. First test `display=SHOW`/`useasexample=1`, add a `HIDE` case. `mark='1.000'`.
5. **Verify**: rows match the reference shape; functionally run the model answer through the question engine (Check path) against all tests; confirm it renders in the bank UI (`/question/edit.php?cat=<catid>,<ctx>&cmid=<qbank cmid>`) and is draggable into a quiz. `moosh -n cache-clear` after any write.

## Bulk creation (a batch of questions in one run — verified 2026-10-22, 18 questions into cat `<cat-new>` (ref 668))

For requests like "create more questions on the same topics as the previous mock exam, but new":

1. **Topic discovery** — dump every LIVE question of the reference category (name + questiontext + answer + all `testcode`) with a query that dumps every LIVE question of the reference category (name + questiontext + answer + all `testcode`) — see the versioning-model SQL above, widened to also select `questiontext`/`answer`/test rows. "Same topics, must be new" = **one brand-new question per topic**: change the function/formula/inputs, not just the name (e.g. prime factors → `num_divisors`; grid paths → staircase; BBS generator → countdown generator; gini impurity → majority proportion).
2. **Generator-verify-emit (MANDATORY order)** — write ONE Python script (skeleton: `templates/bulk_question_generator.py`) that (a) holds every question as data (name, questiontext, answer, 3+ testcases), (b) **execs each model answer then each test in real Python (venv `python3`) and ABORTS on any failure**, (c) only then emits the multi-question XML (root `<quiz>`, one category switch line, N coderunner questions, all text XML-escaped with `xml.sax.saxutils.escape`). Do NOT import before (b) passes — this caught a wrong expected value (poly_eval 57/112) before any DB write.
3. **One import for the whole file.** To append into an **already-created** category: `setCategory()` that existing category AND repeat the same `<question type="category">` switch line — the path resolves by name to the existing category (no duplicate is created). Parse-only stage first, as in xml-import-recipe.md.
4. **Verify as a batch**: one read-back query across the whole category (per question: version/status/coderunnertype/defaultmark/tests-count — see the read-back query pattern in **references/headless-creation-recipe.md §4**), then `moosh -n cache-clear`. Per-question spot-check via the bank UI **Check** button.

## Build gotchas (this modified Moodle 5.x fork)

- **No `mdl_quiz_questions` table; `mdl_quiz_slots` has NO `questionid`.** Quiz→question linkage for the *setup* is custom in this fork (`mdl_question_references.itemid = quiz_slots.id`, component `mod_quiz` — see `moodle-php-cli-pitfalls` §8a). Don't assume stock columns.
- **`mdl_question_usages` has only** `id, contextid, component, preferredbehaviour` (one row per quiz *attempt*, `component='mod_quiz'`) — NOT per-quiz setup; its `id` == `mdl_question_attempts.questionusageid`.
- **`mdl_context`** has `contextlevel`, `instanceid` (no `level`); **`mdl_course_modules`** `module` is a **numeric FK** (no `mod`/`modname`); **`mdl_modules`** maps id→name.
- **`mdl_question_categories`** has no `depth`; the live tree is found by `parent` chains under a `top` category sharing one `contextid`.
- Raw-DB last-step value column is `s.fraction` (+`state`) — there is NO `s.data` column.
- **`mdl_question` has NO `idnumber`, `category`, `hidden`, or `version` column** in this build — `idnumber` lives on `question_bank_entries`; category membership is via entries; version/hide state is in `question_versions`.
- **Headless CLI bootstrap**: `question_bank` (`question/engine/bank.php`), `get_question`/`get_question_bank_entry` (`lib/questionlib.php`), `qformat_xml` (`question/format.php` + `question/format/xml/format.php`) are NOT autoloaded — `require_once` each explicitly. Load coderunner via `question_bank::get_qtype('coderunner')` (raw-requiring `question/type/coderunner/questiontype.php` dies — its parent `question_type` isn't loaded). `question_contextlist` does NOT exist → `core_question\local\bank\question_edit_contexts($context)` (methods `all()/lowest()/having_one_edit_tab_cap()`, no `get_contexts()`). `SQL_MUST_EXIST` constant is undefined. Set `$USER`/`$COURSE` manually in CLI scripts.
- **Author identity for bank writes: `<author-uid>`** (the bank-author account, `<staff-email>` — every bank question is createdby=`<author-uid>`; ref uid 3). The Matrix-room uid (`<other-uid>`; ref 494) is the duplicate LTI account (`enrol_lti…`) that breaks author-tied lookups — do NOT use it.
- **CLI `grade_response()` cannot functionally validate a question here**: prototype discovery (`prototype_contexts()`) needs the course-context bank chain a bare CLI bootstrap doesn't reliably build, so even the working production question returns "Broken question (missing or duplicate prototype 'python3_<coursecode>_prototype'). Cannot be run." Diagnosis rule: if the new question fails in the CLI harness, run the known-good reference through the SAME harness — identical failure = harness issue, not the question. The definitive functional test is the bank UI **Check** button; independently verify test expectations with real Python first (venv python).
- **MCP db-query guard** rejects the keyword "CREATE" — columns like `createdby` trip it; run such queries via PHP.
- After any DB write: `cd <webroot> && moosh -n cache-clear`.
- General PHP/DB flakiness (get_records_sql first-column keying, correlated-subquery deaths, driver bare-errors) — see `moodle-php-cli-pitfalls`.

## Support files
- **references/headless-creation-recipe.md** — the safe headless authoring path: CLI bootstrap `require`s, the `save_question` alternative, canonical raw-insert order, the exact stored shape of live Sem B question q4072 (`print_diamond`) for faithful mimicry, and the import field contract (which option fields are explicit vs imported-default — set them ALL).
- **references/xml-import-recipe.md** — the VERIFIED end-to-end creation run (2026-10-22): two-stage (parse-only → import) PHP sequence, full worked XML template that produced cat `<cat-new>` (ref 668) + (ref q12797), and the post-import verification checklist.
- **templates/bulk_question_generator.py** — copy-and-edit skeleton for the generator-verify-emit step (question data → real-Python verification of every answer/test → multi-question XML emission).
