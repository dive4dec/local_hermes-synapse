---
name: moodle-quiz-question-review
description: "Review and validate Moodle quizzes and their questions for correctness before/after publishing: execute CodeRunner model answers against the real test suites, verify MCQ/match/ordering answer keys, check mark sums, function-name consistency, hidden Unicode chars, LaTeX rendering, and cross-quiz question-bank leakage. Use when asked to 'check the questions and their answers', review a quiz/mock for errors, audit question quality, or verify a bank before a live exam."
---

# Moodle quiz & question-bank integrity review

Class skill for reviewing a quiz (mocks, real quizzes, question banks) for
errors and improvement opportunities on this Moodle 5.2 box. This is a
HIGH-STAKES task — a wrong "there's a bug" report costs trust; so does
missing a real bug. **Default posture: prove, don't assume; report; wait for
explicit confirmation before changing anything** (the course-owner typically
asks for a report first).

## 0. Resolve each slot to its DEPLOYED question version FIRST (prevents the #1 false-bug)

**The single most common way to produce a wrong "there's a bug" report is to
evaluate a SUPERSEDED (retired) version of a question instead of the one the
quiz actually deploys.** On this Moodle 5.2 box a quiz slot does not point at a
single `mdl_question` row — it points at a **question-bank entry**, and an entry
can have **many immutable versions**. If you join `question_versions` on
`questionbankentryid` *without* a version filter, one slot fans out into ALL
historical versions of that entry, and you will (a) see "duplicate" questions
that are really the same entry's version history, (b) misread a fixed N-slot
quiz as a "random draw of many questions", and (c) flag a **stale v1/v2 answer
key as a live bug** even though the deployed (latest) version is correct.

This actually happened on E-Quiz 3: the short-circuit family is ONE entry
(qbank 947) with 7 versions (qids 3633–3639); the deployed version is the
latest (3639). Evaluating 3633/3634/3635 (retired) and flagging their keys as
broken was a **false alarm** — the owner had already fixed them by re-versioning.
Same for the compound-boolean entry 943 (deployed = 3628, not retired 3627).
**No change was made** because all four flagged keys were superseded versions.

### How to resolve the deployed version (always do this)

For each slot: read its `mdl_question_references` row (`component='mod_quiz'`,
`itemid = quiz_slots.id`). It gives `questionbankentryid` and an optional pinned
`version`. **Deployed version = pinned `version` if set, else `MAX(version)`
for that entry.** Use *that* version's `questionid` to read the live
stem/options/tests.

```sql
-- Resolve each slot of quiz $quizid to its DEPLOYED question version (no fan-out)
SELECT s.slot, s.maxmark, s.page,
       qv.id          AS deployed_version_id,
       qv.questionid  AS deployed_questionid,
       q.name, q.qtype, q.questiontext, q.generalfeedback
FROM {quiz_slots} s
JOIN {question_references} qr
  ON qr.itemid = s.id AND qr.component = 'mod_quiz'
JOIN {question_versions} qv
  ON qv.questionbankentryid = qr.questionbankentryid
 AND qv.version = COALESCE(
        qr.version,
        (SELECT MAX(version) FROM {question_versions}
          WHERE questionbankentryid = qr.questionbankentryid))
JOIN {question} q ON q.id = qv.questionid
WHERE s.quizid = $quizid
ORDER BY s.slot, s.page
```

Verify the join is 1:1 — the row count must equal the number of `quiz_slots`
rows for the quiz. If you get MORE rows than slots, you have a fan-out and the
version filter is wrong. **Never** join `question_versions` on
`questionbankentryid` alone in an audit. (If a slot's reference pins a specific
`version`, honour it; the COALESCE handles both pinned and follow-latest slots.)

### Self-check before you report ANY "wrong answer key"

When evaluation says a stored key disagrees with your computed truth, STOP and
ask: *am I on the deployed version?*
1. List all versions of the entry: `SELECT id, questionbankentryid, version, questionid FROM question_versions WHERE questionbankentryid=<entry> ORDER BY version`.
2. Confirm your audited qid == the deployed (latest-or-pinned) version's qid.
3. If NOT, re-extract the deployed version and re-evaluate. **Only a
   discrepancy that persists on the DEPLOYED version is a real bug.**
4. Cross-reference sibling versions: if a retired sibling has the "bug" but the
   deployed one doesn't, it was already fixed by re-versioning → **false alarm,
   do not report.**

## Non-negotiable process

1. **Extract everything first** to JSON. Start from
   `templates/extract_quiz.php` (parameterized:
   `php extract_quiz.php <quizid> <outtag>` → writes `<outtag>_data.json`). It
   does the §0 deployed-version resolution, prints the slot map, extracts full
   question data (coderunner options incl. `twigall`/`templateparamslang`/
   `templateparamsevald`, every test, MCQ `mdl_question_answers`), and runs the
   hidden-char scan in one shot. Schema map: `references/moodle52-schemas.md`.
2. **Execute every coderunner model answer against its test suite** in Python
   (venv: `<datadir>/.hermes/venv/bin/python3`). Harness template:
   `templates/run_model_answers.py`. Respect CodeRunner semantics
   (`references/moodle52-schemas.md` §Execution) — naive harnesses produce
   false failures (this session: 5 of 11 "failing" runs were harness artifacts).
3. **Verify every non-coderunner answer key** by evaluating each option's
   statement in Python (fractions must sum to 1.0 per question; negative
   fractions = wrong options). Use `templates/verify_mcq_keys.py` and read the
   "Verifying MCQ answer keys in Python — harness pitfalls" section FIRST —
   markdown stripping, eval-vs-exec, env binding, stdin shape, and
   timeout-vs-crash are the classic false-alarm sources.
4. **Run the structural detectors** (template script #2): cross-quiz
   question-bank overlap (exam leakage), hidden Unicode chars,
   text-vs-answer function-name consistency, test-mark sums vs slot maxmark.
5. **Render LaTeX through `format_text()`** before declaring any math broken.
6. **Quantify grading impact on an open quiz BEFORE reporting a fix** (see
   "Quantifying grading impact" below). A wrong key with 0 impact (no submitted
   attempt drew it) is still worth fixing if it's live, but the report must say
   so — it changes urgency and whether students need re-grading.
7. **Report** grouped 🔴 bugs / 🟠 integrity decisions-for-user / 🟡 cosmetic,
   with qid + question name + evidence for each item. End with explicit
   "no changes made — awaiting confirmation".

### Batch sizing — a multi-quiz review WILL exhaust the iteration budget if you don't bound it
When asked to review N quizzes (N≥6), do NOT try to do extraction + all
CodeRunner runs + all MCQ keys + structure + report in one unbounded pass.
That is what happened on the E-Quiz 4+ / CE-Quiz 3+ review (13 quizzes, 116
unique questions): ~90 tool calls burned on extraction + the 61 CodeRunner
runs + deep-dive on the 2 file questions, and the MCQ-key verification + final
report were never delivered. Plan for it:
- **Do the cheap high-yield sweep first** for the WHOLE batch (deployed-version
  extract + hidden-char scan + all-CodeRunner model runs + structural
  detectors in one or two scripts), collect ALL the raw findings to disk.
- **Then spend the deep-verification budget only on the small set of
  flagged/suspect items** (a wrong MCQ key, a CodeRunner harness failure, a
  file-dependency). Never deep-dive a passing question.
- **Write the grouped report to a file the moment the sweep is done** (even
  provisional), so the deliverable exists even if you run short of turns.
- If N is large, tell the user up front you're doing sweep-then-verify, and
  offer to split the batch if the flagged set is bigger than a few items.
- Merge per-quiz JSON in Python: cast keys to the SAME type before joining
  (this session's merge silently dropped every `maxmark` because the PHP
  extract emitted string qids but the slotmap map was keyed by int — a
  `marks[str(qid)]` mismatch, not a crash, so it looked "fine" and every
  structural mark-sum check then ran on zeros).

## Execution semantics that decide bug-vs-artifact

- Each test is a **fresh process**: `answer code + test code` in one script,
  no shared namespace across tests → an `import` in test 2 does NOT persist
  into test 3. A hidden test missing its own `import math` is a REAL bug the
  model answer also fails (found live: Mock 23A "Spherical to Cartesian",
  qid 3004).
- **EqualityGrader**: per-line trailing whitespace stripped, then byte-for-byte
  compare. Empty `expected` ⇒ pass iff exit 0 and empty stderr (assert-style).
- Answer formats: plain Python; Scratchpad JSON (extract `answer_code[]` and
  join); Twig (render `{{ STUDENT.firstname }}` etc. with a dummy student);
  Twig templateparams (`{{ fix }}` from a JSON blob); combinator templates
  (order = testcode THEN student answer — the 2702 "Print my info" question).
- **Double backslashes in stored text are NOT a LaTeX bug** when the question
  format is "Mobile" (4) — they render to single backslashes. Verify with
  `format_text()`, never by eyeballing raw bytes.
- **Short-circuit call-counting questions** ("which evaluate to True AND call
  `check()` exactly once"): wrap `check` in a counter (redefine it in the eval
  globals so calls are tallied per option) and `eval()` each option with
  `x,y,z` bound; an option is correct iff `bool(val) is True AND calls==1`.
  If a question yields **0 correct options**, that is the signature of a
  copy-paste stem-operator mismatch among siblings sharing an option set — but
  **apply §0 first**: confirm you are on the DEPLOYED version. On E-Quiz 3 the
  short-circuit family is one entry (qbank 947, versions 3633–3639); the
  *retired* v1 (3633, `return a > b`) looked unanswerable, but the owner had
  already fixed it by re-versioning — the **deployed** latest version (3639,
  `return a < b`) is correctly keyed. So "0 correct options" on a *retired*
  sibling is a re-versioning artifact, NOT a live bug. Only report it if the
  DEPLOYED version is the one that's unsolvable.

## Real bug patterns found (use as a checklist)

1. Hidden test missing its own import (3004) — students capped below maxmark.
2. Text says write `foo(...)` but answer/template/tests use `bar(...)`
   (2161 `wavelength` vs `calculate_wavelength`) — literal-following students score 0.
3. Hint/prose references a parameter name that doesn't exist in the signature
   (2698 "convert `x`" but function is `is_palindromic(n)`).
4. Zero-width spaces (U+200B) inside code in the question text — copy-paste
   breaks (2696 `interior_angle(n​)`, 2698 `is_palindromic(​n​)`); also U+00A0
   instead of space (3040).
5. Copy-paste description error between sibling questions (4056: "returns the
   **exponential** linear unit function" on the inverse-square-root question).
6. **Cross-quiz question-bank overlap**: compare shared `questionbankentryid`s
   across quizzes — Mock 25B was 8/8 identical to the real Midterm (leak if
   unintentional); the makeup was correctly 0-overlap. **Resolve each shared
   entry to its deployed qtype before calling it a leak**: a shared
   `description` (the unscored "Information" page, e.g. qid 12781 shared by the
   whole E-Quiz series with the midterm + all mocks) is NOT scored-content
   leakage. Only shared *scored* (multichoice/coderunner/…) entries are a real
   leak.
7. Stale working names still on live questions ("Taylor for exp (seems to
   appeared) (copy)").
8. Course-structure orphaning: section rows beyond the max stored in
   `mdl_course_sections` still work (quizzes in section 21 with no section
   row), but the heading named "Midterm Quiz" (section 13) was EMPTY while
   the real quizzes sat in the unnamed orphan section.
9. **Copy-pasted option set with a mismatched stem condition** (E-Quiz 3
   qid 3633): sibling questions share an identical option list but one stem
   differs (`check: return a > b` vs `a < b`); the differing one keeps the
   family's answer key and becomes unsolvable or mis-keyed. When several
   questions share near-identical options, evaluate EACH against its OWN stem.
10. **Stale/wrong key on a single option** — one option's fraction is the
    inverse of its true value (e.g. a `-5 and -10` trick that evaluates True
    but is marked wrong, or a False option marked correct). Always re-derive
    the full correct-set by evaluation, don't just spot-check the
    "obviously right" options. ⚠️ **CORRECTION (E-Quiz 3 false alarm):** items
    9 & 10 were originally reported against qids 3627/3633/3634/3635 and were
    confirmed by the owner to be **FALSE ALARMS** — those are SUPERSEDED
    versions of entries 943/947 whose DEPLOYED (latest) versions (3628, 3639)
    are already correct. The pattern above is a *general* warning; the E-Quiz 3
    instances specifically were resolved by re-versioning, not by editing the
    live key. **Do not cite 3627/3633/3634/3635 as live bugs.** Always apply
    §0 (resolve to deployed version) before flagging any key.
11. **"Random draw" illusion** (E-Quiz 3/4): if it looks like a quiz serves
    "more questions than it has slots" or "a different set per student", check
    for the version fan-out (§0) FIRST — that is almost always the cause, not
    question randomization. The E-Quiz series on this course are
    **fixed-slot quizzes** (17 slots; every attempt gets the same deployed
    question set). Consequently, when a flagged qid "appears in no submitted
    attempt", the usual cause is that the flagged qid is not the DEPLOYED
    version — re-verify with §0, then re-run the impact query with the real
    deployed qid. Only after that is "no submitted attempt touched it" a
    legitimate finding.
12. **CodeRunner question depends on files that never exist in the sandbox**
    (E-Quiz 7 review, 2026-09-24 — qid 3881 `read_first_line`, 3883 `read_lines -
    generator`, both in E-Quiz 7 + the generator one in CE-Quiz 7): the tests read
    `file1.txt`/`file2.txt` that no test creates, and neither the question nor its
    prototype carries support files, so every student gets `FileNotFoundError` on
    the shown tests and the question is effectively unpassable (the hidden test
    that creates its own file still fails because `allornothing=1` zeroes the
    whole question). A raw harness is double-blind here: supply the files yourself
    and the model answer "passes"; don't supply them and you get a failure you
    might misfile as a harness artifact. Verification recipe (case file:
    `references/coderunner-file-questions.md`):
       a. Check support files in the REAL area: `mdl_files` with
       `component='qtype_coderunner'`, `filearea='datafile'`, `contextlevel=75`
       for the question's id — NOT `core_question`/`files` (wrong area returns
       empty and looks the same as no-files; the `qtype_coderunner`/`datafile`
       check is what's definitive).
       b. If the question is a prototype question
       (`question_coderunner_options.prototypetype<>0`), also check the
       prototype's context: `get_files()` merges prototype support files.
       Resolve the prototype: latest version with `prototypetype<>0 AND
       coderunnertype=<name>` whose category context is available in the quiz
       context (see the reference file's query).
       c. Confirm the sandbox kind in `mdl_config_plugins` (here
       `jobesandbox_enabled=1`, ideone off) and read the sandbox's file-seeding
       code (localsandbox `load_files()` writes ONLY the question file map into a
       fresh temp dir — nothing else is pre-seeded; a Jobe sandbox runs remotely
       with the same file map, so the conclusion is identical).
       d. DECISIVE: query the minfraction distribution on predecessor versions
       (same question text, earlier semester) in `mdl_question_attempts`.
       All-zero marks (here: 389 + 773 attempts, avg fraction 0.000) prove the
       files never existed in production — confirmed bug, not harness.
       Do NOT spend budget constructing a live `qtype_coderunner_question` +
       `grade_response` in CLI on this 5.2 fork: the questionbank lib paths and
       behaviour-class loading are fragile, and the DB evidence above is cheaper
       and equally conclusive. (Full case + queries:
       `references/coderunner-file-questions.md`; CLI class-loading details:
       `moodle-php-cli-pitfalls` §11c.)

## Quantifying grading impact on an open quiz

Before telling the owner a key is wrong, find out whether any *submitted*
student already lost/won marks because of it. (Fixed-slot quiz: the buggy
question appears in every attempt, so impact = the sum of `minfraction*maxmark`
on that qid across all finished usages. Draw quiz: the qid may be absent from
some or all attempts — 0 can mean "nobody drew it" OR "wrong qid audited";
re-verify the deployed qid via §0 before trusting a 0.)

```php
// buggy qids = the question_ids with wrong keys
// contextid = course-module context of the quiz (contextlevel=70, instanceid=cmid)
$ctx = $DB->get_record('context', ['contextlevel'=>70, 'instanceid'=>$cmid]);
$uids = $DB->get_records_sql(
  "SELECT id FROM {question_usages} WHERE component='mod_quiz' AND contextid=".$ctx->id);
foreach ($uids as $u) {
  $buggy = $DB->get_record_sql(
    "SELECT COALESCE(SUM(minfraction*maxmark),0) g, COALESCE(SUM(maxmark),0) m
       FROM {question_attempts}
      WHERE questionusageid=".$u->id." AND questionid IN (".implode(',', $buggy_qids).")");
  // $buggy->g > 0  => a student earned marks on a buggy question => re-grade impact
}
```
Notes:
- `mdl_question_attempts` rows carry `questionusageid` + `questionid` +
  `minfraction` + `maxmark`; earned marks = `minfraction * maxmark`. (There is
  no `mark` column on `mdl_question_attempts` in this build.)
- `mdl_question_usages` DOES exist and is keyed by quiz attempt (one row per
  attempt, `component='mod_quiz'`, `contextid` = the quiz CM's context).
  Its `id` is NOT the same id space as `mdl_quiz_attempts.id` — do not assume
  `questionusageid == quiz_attempts.id`. Group by `questionusageid`.
- If total `g == 0` across all usages: **no submitted student drew the buggy
  questions** → report "currently 0 grading impact, but the pool is live".

## PHP-DB access gotchas (5.2) — read before writing /tmp/*.php

- **`get_records_sql()` keys by the FIRST selected column** and silently
  collapses duplicate first-column values. A slot→question join where the
  first column is `slot` (which repeats across a page) will DROP rows. Always
  `SELECT DISTINCT` into a `questionid`-keyed map, or fetch the full raw
  mapping with `get_recordset_sql()` (no keying) and build your own array.
- **Named parameters (`:c`, `:id`) are NOT supported** by
  `mariadb_native_moodle_database::get_records_sql` here — it throws
  `missing param "c"`. Inline literals (the `$quizid`/`$cmid` ints are
  server-controlled, so safe) or use `get_recordset_sql` with inline values.
- **`mdl_question_multichoice` does NOT exist** in 5.2. MCQ answer choices are
  in `mdl_question_answers` (see schema ref); `mdl_qtype_multichoice_options`
  is settings-only. Using `get_record('question_multichoice', …)` →
  `Error reading from database`.
- `get_record(...)` returning `false` (no row) then being indexed throws the
  generic "Error reading from database" — guard with `if ($x)` before use.
- The **answer key you must flip is `mdl_question_answers.fraction`**
  (positive = correct, negative = wrong; multi-select correct set sums to 1.0).
  To flip one option: `set_field('question_answers','fraction',±0.25,'id',$aid)`.
  Bump `mdl_question.timemodified`/`stamp` and purge `core/questiondata`
  (+ `question_finder::get_instance()->uncache_question($qid)`) after edits.

## Verifying MCQ answer keys in Python — harness pitfalls (false alarms live here)

Evaluating every option in the course's venv Python is the right way to check a
key, but each of these produced a FALSE "wrong key" flag in this session. Fix
the harness before reporting anything:

1. **Strip ALL markdown from option text before evaluating.** Options come as
   `` `expr` ``, ``` ` ``` blocks, or plain prose. An expr wrapped in single
   backticks (`` `x == 0 or 10 / x > 1` ``) makes `eval`/`compile` throw
   `SyntaxError`, and a whole option set looks "impossible/wrong". Strip ```
   fences, surrounding backticks, then whitespace. For snippet options
   (multi-line `if` blocks) the SAME strip works but you must `exec`, not
   `eval`.
2. **`eval` vs `exec` per option shape.** One-line expressions → `eval(expr,
   env)`. Snippet options (statements, assignments, `for`/`if` blocks) →
   `exec` and capture `stdout`; `eval` on a snippet = `SyntaxError` = false
   "wrong". CodeRunner "prints X" MCQs (loop output, break/continue) must run
   the snippet and compare the captured stdout to the claim.
3. **Bind the question's variables in the env** (`x=5, y=10, z=15` for the
   short-circuit family; `x=0` for the divide-by-zero family; `age`,
   `has_ticket` for the grid questions). Forgetting the prelude gives
   `NameError` on every option → the whole question looks broken.
4. **Input-driven questions: feed input the shape the code reads.**
   `int(input())` inside a `while` loop consumes **one value per line** — feed
   `5\n0\n8\n-1\n`, NOT `5 0 8 -1` on one line (space-separated reads `5 0 8
   -1` as one int → `ValueError` → false "crash"). For-`else` budget questions:
   feed the budget line first, then the prices.
5. **Timeout ≠ correct behaviour.** "Which loops are infinite" MCQs: a snippet
   that CRASHES (or exits) also returns quickly — the test must distinguish
   `TimeoutExpired` (infinite) from a fast exit (finite). Run cleaned code with
   a short timeout and treat ONLY the timeout as infinite. (Feeding
   uncleaned ```-fenced text crashes instantly and misclassifies all options.)
6. **`not` binds tighter than `-`.** `not x - 5` is `(not x) - 5`, not `not (x
   - 5)` — a deliberate trap this course uses. Let Python decide; do not
   reason about it by hand when you've already flagged it.
7. **Multi-select fractions:** the correct set's positive fractions should sum
   to ~1.0; negatives are wrong options. After computing the true correct set,
   diff it against the stored key option-by-option — report the exact option
   letters and both values.
8. **Re-run one suspicious option by hand** (print the full value + call count)
   before putting it in the report; several "mismatches" this session were the
   harness, not the key.

Reusable harness: `templates/verify_mcq_keys.py` (strips markdown, dispatches
eval vs exec, binds a per-question env, handles timeout-infinite and
newline-separated stdin; prints per-option stored-vs-computed with mismatch
flags).

## Known false positives (do not report)

- `\\` doubled backslashes in Mobile-format text (correct escaping).
- Per-test marks not summing to slot maxmark — CodeRunner auto-scales the
  award to the quiz mark; it's a hygiene smell, not a grading bug.
- Test code calling `math.isclose` etc. — test code does its own imports.
- `extractcodefromjson`/JSON-shaped answers failing in a naive harness.
- **Twig-template-string model answers are a raw-harness blind spot.** A
  question whose `twigall=1` / `templateparamslang=twig` and whose model answer
  is itself a Twig template string (e.g. `print('{{ STUDENT.lastname ~ ' ' ~
  STUDENT.firstname }}')`) will NOT run correctly through a plain-Python
  harness: adjacent-literal concatenation strips the embedded `' '` and the
  `{{ }}`, so it "fails" against an expected that still contains them. You
  cannot resolve Twig-vs-plain semantics from the CLI. When the ONLY harness
  failure is such a question, inspect its Twig config, then report it as
  **"unverified in raw harness — needs a manual CodeRunner check"** — do NOT
  report it as a confirmed bug, and do NOT silently count it a confirmed pass.
  (E-Quiz 1 qid 3503 was exactly this.)
- **"Internal slot marks don't sum to the quiz grade" is NOT a bug.** The
  E-Quiz series sums to **23 raw slot marks** (9×1 MCQ + 7×2 CodeRunner + 1
  unscored Information) but the grade item is on a **0–80** scale; Moodle
  auto-scales raw→gradebook (23/23 → 80/80 = 100%). Confirm it's by design with
  `grade_grades.maxgrade == mdl_quiz.grade` (both 80) and `MAX(grade_grades.
  rawgrade)` reaching that max. See `moodle-php-cli-pitfalls` §11.

## Report format (course owner's preference)

Grouped list, NO tables (Matrix rendering): 🔴 Bugs (with qid, question name,
evidence, suggested fix), 🟠 Integrity concerns needing a decision, 🟡
Cosmetic/improvement, ✅ Verified-correct section. Close with: "No changes
made — awaiting your confirmation" and, for each ambiguous fix, state which
variant was chosen (e.g. which name is canonical).
