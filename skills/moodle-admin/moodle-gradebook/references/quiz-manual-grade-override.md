# Per-question quiz manual override (mark + comment) — full recipe

Worked session: 2026-09-22, zeroing E-Quiz 2 (quiz 59, cs1302a_26a) for one
student (absent from the sampled-answer explanation; owner required all 16
scored questions marked 0 **with an explanatory comment**). The mechanism is
stock Moodle's question-engine manual grade — the same code path the
"Edit comment or grade" popup (`mod/quiz/comment.php`) drives.

## Where the data lives on this build

- Manual mark + comment are **question-attempt STEP variables**, not columns:
  each `manual_grade()` call appends a step row to `mdl_question_attempt_steps`
  plus rows in `mdl_question_attempt_step_data` with behaviour vars `-mark`,
  `-maxmark`, `-comment`, `-commentformat` (format = `FORMAT_MOODLE`).
- `mdl_question_attempts`: columns here are
  `id, questionusageid, slot, behaviour, questionid, variant, maxmark,
  minfraction, maxfraction, flagged, questionsummary, rightanswer,
  responsesummary, timemodified`. **No `manualmark`, no `usercomment`, no
  `gotmark`.** Earned mark = `minfraction × maxmark`.
- **Step table shapes (verified `SHOW COLUMNS` 2026-09-24):**
  `mdl_question_attempt_steps` = `id, questionattemptid, sequencenumber,
  state, fraction, timecreated, userid` — **NO `name` column**.
  `mdl_question_attempt_step_data` = `id, attemptstepid, name, value` —
  **NO `userid`, NO `timecreated`**. When/who applied a step lives on the
  parent step row: `steps.userid` = grader (e.g. 2/admin), `steps.state` =
  `mangrwrong` for a manual mark below max ("mangr" = manually graded).
- **FK chain (the #1 verification trap):**
  `question_attempts.id` → `question_attempt_steps.questionattemptid` →
  `question_attempt_step_data.attemptstepid` (i.e. `attemptstepid` =
  `question_attempt_steps.id`, **NOT** `question_attempts.id`). The id
  spaces are disjoint, so joining step_data straight to question_attempts
  ids returns 0 and fakes "nothing was written" (bitten 2026-09-24 — led to
  a spurious half-revert; see Pitfalls).
- `mdl_quiz_grades` (`id, quiz, userid, grade, timemodified`) = the grade
  calculator's **cached** per-user best grade, rewritten by
  `recompute_final_grade()`. **Not** a manual-override store; no comment column.
- The comment shows in the attempt review / grading report via
  `question_attempt::get_manual_comment()` → `[comment, format, step]`.

## API surface that exists here (CLI-verified)

- `\mod_quiz\quiz_attempt::create($attemptId)` → attempt object.
  (`quiz_create_attempt_handling_errors()` does NOT exist on this build.)
- `$attemptobj->get_attempt()` (row: `sumgrades` etc.), `get_userid()`,
  `get_quizid()`, `get_uniqueid()` (== `question_attempts.questionusageid`),
  `get_question_usage()`, `get_courseid()`, `get_quizobj()->get_context()`,
  `get_slots('all')`, `get_question_attempt($slot)`, `is_finished()`,
  `recompute_final_grade()`, `process_submitted_actions($ts)`.
- `question_attempt`: `manual_grade($comment, $mark, $format, $ts, $userid)`,
  `get_mark()`, `get_max_mark()`, `get_min_fraction()`, `get_max_fraction()`,
  `get_question_id()`, `get_database_id()`, `get_current_manual_mark()`,
  `has_manual_comment()`, `get_manual_comment()`, `get_sequence_check_count()`,
  `get_field_prefix()` = `q{usageid}:{slot}_`.
  **No** `get_grade()`, `get_id()` on question_attempt.
- `question_definition`: no `get_name()`/`get_qtype()` (at least not on the
  description qtype) — join `mdl_question` for `qtype`/`name`.
- `question_engine::save_questions_usage_by_activity($quba)`.
- Event: `\mod_quiz\event\question_manually_graded`
  (`objectid`=questionid, `courseid`, `context`, `other`={quizid, attemptid, slot}).

## Recommended flow

1. Locate the attempt: `mdl_quiz_attempts WHERE quiz=<qid> AND userid=<uid>`
   → `id` = attemptid. Confirm `state='finished'`.
2. Read-only inspection: list every slot with qtype, `maxmark`, `get_mark()`,
   `has_manual_comment()` — show the owner the current per-question marks and
   the current total (raw + gradebook scale) BEFORE applying.
3. Confirm the exact comment wording with the user (clarify tool) — it becomes
   part of the permanent audit trail.
4. **Pre-state backup** (see format below) → `/tmp/<tag>_backup_pre.json`.
5. **Dry-run pass**: run the whole apply inside a delegated transaction,
   then ROLL it back and confirm `sumgrades` is back to its original value
   and no manual steps exist (verified 2026-09-24 — delegated dry-runs are
   safe when the transaction is always closed; see Pitfalls). Keep the raw
   backup as last-resort restore.
6. **Commit pass**: apply, save, recompute, fire events.
7. Verify **two ways**: (a) the three grade fields agree
   (`sumgrades`, `quiz_grades.grade`, `grade_grades.rawgrade`), and (b) the
   per-slot step data is ACTUALLY in the DB — re-read via the correct FK
   chain (3-table join; do NOT join step_data straight to question_attempts
   ids) with the authorship filter, and confirm the exact comment string.
   Run (b) through the `moodle_db` MCP tool (separate connection, sees
   committed data, gives real SQL error text) rather than only re-querying
   inside the PHP write script — an in-script check on a bad join reads 0
   even when the commit succeeded (2026-09-24 false alarm). `moosh -n
   cache-clear` and spot-check the grading report.
8. Keep the backup file; mention its path in the final report.

## Apply core (dry-run and commit share this)

```php
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php'); require_once('/var/www/html/public/lib/setup.php');
global $DB;
require_once('/var/www/html/public/mod/quiz/locallib.php');
require_once('/var/www/html/public/mod/quiz/classes/quiz_attempt.php');

$attemptobj = \mod_quiz\quiz_attempt::create($attemptid);
$usageid    = $attemptobj->get_uniqueid();          // == question_attempts.questionusageid
$byuser     = <grader uid>;                          // e.g. 2 (admin)
$comment    = '...exact wording confirmed by owner...';

$scoreslots = [];
foreach ($attemptobj->get_slots('all') as $slot) {
    $qtype = $DB->get_field('question', 'qtype', ['id' => $attemptobj->get_question_attempt($slot)->get_question_id()]);
    if ($qtype !== 'description') $scoreslots[] = $slot;
}

$ts = time();
foreach ($scoreslots as $slot) {
    $qa = $attemptobj->get_question_attempt($slot);
    $qa->manual_grade($comment, 0, FORMAT_MOODLE, $ts, $byuser);
}
question_engine::save_questions_usage_by_activity($attemptobj->get_question_usage()); // BEFORE recompute!
$attemptobj->recompute_final_grade();                                                  // quiz_grades + gradebook
// optional, per slot (the popup fires this):
$ctx = $attemptobj->get_quizobj()->get_context();
foreach ($scoreslots as $slot) {
    \mod_quiz\event\question_manually_graded::create([
        'objectid' => $attemptobj->get_question_attempt($slot)->get_question_id(),
        'courseid' => $attemptobj->get_courseid(),
        'context'  => $ctx,
        'other'    => ['quizid' => $attemptobj->get_quizid(), 'attemptid' => $attemptid, 'slot' => $slot],
    ])->trigger();
}
```

## Pre-state backup format (raw rows for lossless restore)

```php
$backup = [
  'ts' => date('c'), 'attemptid' => $attemptid, 'uniqueid' => $usageid,
  'attempt'        => <quiz_attempts row: sumgrades,state,timemodified,currentpage,timefinish>,
  'question_attempts' => [qa.id => <ALL columns: slot,behaviour,questionid,variant,
                    maxmark,minfraction,maxfraction,flagged,questionsummary,
                    rightanswer,responsesummary,timemodified>],   // WHERE questionusageid=$usageid
  'step_data'        => <ALL rows of question_attempt_step_data WHERE
                    questionattemptid IN (<qa ids>), ordered by id>,
  'grade_grades'     => <row for (itemid=<grade_items.id>, userid) or null>,
  'quiz_grades'      => <row for (quiz, userid) or null>,
];
json_encode(..., JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES)
```
Restore: `update_record` each `question_attempts` row; `delete_records_select`
`question_attempt_step_data` for the qa ids then `insert_record` the originals
**with their ids**; restore `quiz_attempts`, `grade_grades`, `quiz_grades`;
then `recompute_final_grade()` on a fresh attempt object + save usage; confirm
`sumgrades` equals the pre value.

## Alternative: drive the real form path (only needed if exact UI parity matters)

`process_submitted_actions($ts)` reads `$_POST`; in CLI set
`$_POST = ['slots' => '2,3,...', <per slot>: 'q{usageid}:{slot}_:sequencecheck'
= get_sequence_check_count(), '..._-mark'='0', '..._-maxmark', '..._:minfraction',
'..._:maxfraction', '..._-comment', '..._-commentformat']=FORMAT_MOODLE]`, then
call it on the attempt object (it persists + recomputes). Equivalent result,
more moving parts — prefer the `manual_grade()` loop.

## ⚠️ Build delta (verified 2026-10-06, CE-Quiz 4 zero-out) — `recompute_final_grade()` is PROTECTED and does NOT touch `sumgrades`
In this Moodle 5.x build the recipe above needs two changes or you end up with a
**desync: per-question manual marks = 0 but the total/gradebook still show full marks**:
1. `mod_quiz\quiz_attempt::recompute_final_grade()` is `protected` (not public) — call it
   via reflection: `$m = (new ReflectionObject($attemptobj))->getMethod('recompute_final_grade'); $m->setAccessible(true); $m->invoke($attemptobj);`
2. `recompute_final_grade()` only refreshes `quiz_grades` + `grade_grades` **from
   `quiz_attempts.sumgrades`** (`grade_calculator::compute_final_grade_from_attempts()`
   reads `$attempt->sumgrades`). The manual-grade path sets per-question
   `minfraction=0` but **NEVER updates `sumgrades`** — that only happens inside
   `process_submitted_actions()` (`$this->attempt->sumgrades = $quba->get_total_mark();`).
   So after saving the quba, ALSO: `$quba = <reflection on protected $quba>;
   $attemptobj->get_attempt()->sumgrades = $quba->get_total_mark();
   $DB->update_record('quiz_attempts', $attemptobj->get_attempt());` then invoke the
   recompute. After that all four agree (`sumgrades=0`, `quiz_grades.grade=0`,
   `grade_grades.rawgrade=0`, `finalgrade=0`), verified via the MCP tool. Finish with
   `grade_regrade_final_grades($courseid)` (needs `require_once lib/gradelib.php`) +
   `moosh -n cache-clear`.
3. Alternative `$_POST` + `process_submitted_actions()` path: works, BUT `-comment` is
   declared `paramrawfiles` in `get_expected_data()` (draft-file based), so the plain
   text comment is silently DROPPED on the form path (only `-mark`/`-commentformat`
   capture). Use the `manual_grade()` API for mark+comment. Also note the method reads
   `$_POST` internally when `$simulatedresponses` is null — a local `$post` array that
   is never assigned to `$_POST` results in a silent no-op (slots skipped, nothing saved).
4. `question_usage::get_question_usage()` on quiz_attempt is unit-test-guarded
   (`coding_exception` in CLI) — reach the protected `$quba` property via reflection;
   `question_engine::save_questions_usage_by_activity($quba)` is fine with it.

## Pitfalls

- **Delegated transactions are FINE when closed (corrected 2026-09-24 — supersedes the 09-22 claim):** the earlier "delegated transaction wraps fail / active database transaction detected during request shutdown" was an **UNCLOSED** transaction at script exit (dry-run path never called `rollback()`/`allow_commit()`), NOT an engine incompatibility. 2026-09-24 ran 4+ delegated transactions — dry-run rollbacks AND a full `allow_commit()` apply — all clean. Preferred pattern: `start_delegated_transaction()` → apply (manual_grade loop + `save_questions_usage_by_activity` + grade recompute) → verify step count **inside the transaction** → `allow_commit()` (or `rollback()` for a true no-op dry run). Add a `--commit` flag so the default run is a safe rollback. Keep raw pre-state backup as the last-resort restore.
- **The verification trap (2026-09-24, caused a spurious half-revert):** a fully successful commit reported "0 manual steps" because the check joined `question_attempt_step_data.attemptstepid` to `question_attempts.id` — wrong FK (attemptstepid → `question_attempt_steps.id`). Convinced the steps were lost, the "restore" reset only the 3 grade fields while the manual marks/comments stayed in the DB → inconsistent state (gradebook 70% vs stored manual marks of 0). Recovery: the manual steps were intact; just recompute the total from them (`set sumgrades` + `recompute_final_grade`). **Never "restore" based on an in-script step count — re-verify via the correct join, ideally the MCP tool (separate connection, real error text), before undoing anything.** A partial restore (grade fields only, steps untouched) is exactly how you desync total vs per-question marks.
- **Verification query that WORKS (correct join + authorship filter)** — `steps.userid` is who applied it (admin = 2); `state='mangrwrong'` = manual mark below max. Run via MCP (param `query`); avoid `timecreated` in the text (keyword filter rejects "CREATE"):

```sql
SELECT s.questionattemptid, s.id AS stepid, s.userid, s.state, d.name, d.value
FROM mdl_question_attempt_steps s
JOIN mdl_question_attempt_step_data d ON d.attemptstepid = s.id
WHERE s.questionattemptid IN (SELECT id FROM mdl_question_attempts
       WHERE questionusageid = <uniqueid> AND slot > 1)
  AND d.name IN ('-mark','-comment')
ORDER BY s.questionattemptid, s.id;
```
Expect 2 rows (a `-mark` and a `-comment`) per scored question attempt. For an exact-comment count use the literal string in `WHERE d.value = '...'` (it round-trips through MCP fine).
- **Step-table schema traps:** `mdl_question_attempt_steps` has **no `name` column** (state is a value like `mangrwrong`); `mdl_question_attempt_step_data` has **no `userid`** and no `timecreated` (those live on the parent step row). Selecting either of those phantom columns → swallowed "!!! Error reading from database !!!" (dml_read_exception hides the real error) — 5+ wasted probes 2026-09-24. Confirm schema with `SHOW COLUMNS` (MCP) before writing join queries.
- **`$DB->get_records_sql` nested-subquery flakiness:** the same multi-table `IN (SELECT … IN (SELECT …))` count dies with a bare "Error reading from database" in the PHP bootstrap even though it works verbatim through the MCP connection (2026-09-24). For final verification of question-engine state, prefer the MCP read tool; keep PHP-side checks to simple single-table queries.
- **String vs int comparison**: DB values are strings; `$row->userid !== $uid`
  is a false positive. Use `!=` or cast.
- **Missing methods**: `get_grade()`, `get_id()` (question_attempt), and
  question `get_name()`/`get_qtype()` → use `get_mark()`, `get_database_id()`,
  and an `mdl_question` join.
- **Don't skip the save before recompute**: `manual_grade()` is in-memory until
  `save_questions_usage_by_activity()`; recomputing before saving reads stale
  fractions.
- **Skip description slots** (the 0-mark Information page) — marking them is
  harmless but pointless; `manual_grade` on a 0-max question has no mark field.
- **Attribute the action**: pass the grader's uid (e.g. 2 = admin /
  chung.chan) as the `$userid` in `manual_grade()` so the step audit trail
  credits the right person.
- Raw vs gradebook scale: `sumgrades`/`quiz_grades.grade`/`grade_grades.rawgrade`
  all end up 0 here, but for partial overrides remember the gradebook max is
  `mdl_quiz.grade` (e.g. 80) while slot marks sum to the internal raw (23).
