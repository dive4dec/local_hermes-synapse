---
name: moodle-php-cli-pitfalls
description: Pitfall bank for writing PHP CLI scripts against this Moodle (course rosters, quiz attempts, step traces, mail). The recurring PHP/DB gotchas that silently corrupt results — array_intersect keys-vs-values, get_records_sql keying/flakiness, php -l broken, where CodeRunner behaviour flags live. Consult BEFORE hand-writing any /tmp/*.php data script; pairs with moodle-db-access (bootstrap + table map).
---

# Moodle PHP CLI scripting pitfalls

Hand-written `/tmp/*.php` scripts are the reliable path for cohort reports, step
traces, and batch ops (MCP query tool truncates at 100 rows). But PHP has several
silent-corruption traps here. Check this list before writing data scripts.

## 1. `array_intersect` compares VALUES, not keys (cost 3 wasted runs, 2026-09-17)
Building "sets" as `uid => true` maps and intersecting them is broken in BOTH
directions:
- two all-`true` maps → intersection returns the ENTIRE first array (every value
  `true` "equals" every other) → false "everyone matches"
- `array_flip($ids)` (values `0`) ∩ `uid=>true` map (values `1`) → EMPTY (0≠1) → false "no one matches"

Demo: `array_intersect([502=>true,504=>true], [504=>true,505=>true])` returns 502 AND 504.
**Correct pattern** — intersect flat id lists, then flip:
```php
$enrolled = array_flip(array_intersect($roleUidList, $enrolUidList)); // uid => true
```
Same discipline for `array_diff`/`array_unique` on id lists.

## 2. `array_keys($records)` is the ROW id, not the user id
`$DB->get_records('role_assignments', …)` keys results by `id`. To get userids:
`array_column($ra, 'userid')`. Using `array_keys` quietly gives assignment row ids
(looked plausible, produced a 0-or-1 intersection).

## 3. `get_records_sql` keys by the FIRST selected column
Duplicate first-column values overwrite earlier rows. Always `SELECT id, …` (the
table's own id) first when iterating.

## 4. `get_records_sql` flakiness (known in this environment)
Can die with bare "Error reading from database" on nested subqueries or some column
combos, and can SILENTLY return wrong/incomplete rowsets. Keep queries flat (one
table or one simple join, no subqueries). For per-user membership (groups, role
assignments, enrolments) loop `get_records('table', ['userid' => $id])` — N calls is
fine for a few hundred users. When you must use multi-table SQL, cross-check at
least one entity via the hash API before reporting.

## 5. `array_merge()` / `usort()` reindex integer keys
`array_merge([5=>x, 7=>y], [3=>z])` → `[0=>x,1=>y,2=>z]`; `usort` on a map destroys
key→value association. Sort `array_keys($arr)` separately, or iterate explicitly.
Bit the E-Quiz audit twice (uid maps became 0,1,2… and lookups returned "0 students").

## 6. `php -l` is broken in this pod
Reports "Errors parsing … on line N" even for valid one-liners (`<?php function
f(){return 1;}` fails lint). Verify scripts by RUNNING them (read-only queries are
safe) and checking output — never trust the linter verdict.

## 7. Closures and globals
Top-level closures don't auto-bind `global $DB` — use `global $DB;` inside or
`use ($DB)`. A `t($label, $fn)` wrapper that catches `Throwable` and prints
`ERR <label>: <msg>` makes debugging chunked loops far faster.

## 8. Chunk big `IN (…)` lists
~100 ids per chunk. Never select columns that may not exist in this version —
probe `information_schema.columns` first (e.g. some versions have
`mdl_question_attempt_step_behaviour`, this one stores behaviour flags in
`mdl_question_attempt_step_data.attemptstepid/name/value`; CodeRunner Precheck =
step with `name='-precheck'`).

## 8a. Moodle 5.2 renamed/removed columns silently bite (4x in one session, 2026-09-21)
`mdl_question.questiontextformat` (NOT `questionformat`); `mdl_question_answers.question`
(NOT `questionid`); NO `mdl_quiz_questions`; NO `mdl_question_question_usages`; no
`uniqueid` in `mdl_question_usages`; the 5.2 `mdl_qtype_*_options` tables hold
SETTINGS only — MCQ/match/ordering choices
live in `mdl_question_answers` (keyed by column `question`). Quiz slots link to
questions via `mdl_question_references.itemid = quiz_slots.id` (component='mod_quiz'), NOT via
any usages table. A missing column surfaces either as a SQL error or a bare
"!!! Error reading from database !!!" from `$DB` — both mean "re-probe the
schema", never "retry the same query". Full 5.2 map + CodeRunner execution
semantics: `moodle-quiz-question-review` skill, `references/moodle52-schemas.md`.

## 8b. More 5.2 silent failures (E-Quiz 3 review, 2026-09-21)
- **Named params in `get_records_sql` WORK — the params-array keys must match the placeholder names EXACTLY.** The `ERROR: missing param "c" in query` observed earlier is a key mismatch (e.g. SQL says `:c`, array says `['cid'=>…]`), NOT a missing feature: on 2026-09-28, `:q`/`:u` named params in `get_records_sql` were used ~15× and worked every time. Inline literals remain simplest for small int ids.
- **`mdl_question_multichoice` does NOT exist in 5.2.** `get_record('question_multichoice',
  ['questionid'=>…])` → bare "Error reading from database". MCQ choices =
  `mdl_question_answers` (keyed by `question`); `mdl_qtype_multichoice_options`
  is settings-only.
- **`mdl_question_usages` DOES exist** (`id, contextid, component,
  preferredbehaviour`), one row per quiz attempt (`component='mod_quiz'`,
  `contextid` = quiz CM context). Its `id` == `mdl_question_attempts.questionusageid`
  but is NOT `mdl_quiz_attempts.id`. Do not join quiz_attempts.id to
  question_usage.id.
- **`mdl_question_attempts` has NO `mark` column.** ⚠️ CORRECTED (2026-09-24,
  KWOK partial-grade session): the old note "earned marks = minfraction *
  maxmark" is WRONG — `minfraction` is a per-question ASSIGNMENT setting (min
  fraction the question may award) and reads 0.0 even on questions graded full
  marks; it will report every question as 0. Authoritative per-question earned
  marks = LAST row of `mdl_question_attempt_steps` for that `questionattemptid`
  (`ORDER BY sequencenumber DESC, id DESC LIMIT 1`):
  `fraction * question_attempts.maxmark`. Verified: sum of last-step marks
  matched `quiz_attempts.sumgrades` exactly (22.666666 vs 22.66667).
  `mdl_quiz_attempts` has `sumgrades` but no per-question breakdown.
- **"Question N" is ambiguous — confirm before grading a single question.**
  Display numbering is sequential over ALL slots, and slot 1 is typically a
  0-mark "Information" description page, so "Question 10" may be the 10th of 17
  slots (a multichoice) or the 10th *scored* question (a coderunner). Check
  `mdl_quiz_slots.displaynumber` first (often NULL = auto-numbered), map the
  candidate to (slot, questionid, name) via `mdl_question_attempts`, and ask
  the user to confirm which one before applying any single-question mark.
- **`get_records_sql` first-column keying** bit hard: a slot→question join
  `SELECT s.slot, …` collapses every repeated `slot` (all questions on one page
  share a slot number) → silently drops 50 rows to 17. `SELECT DISTINCT
  qv.questionid …` into a qid-keyed map, or `get_recordset_sql` for the raw map.

## 8c. `mdl_ltigroups_roster` schema + flaky `IN (…)` (E-Quiz 3 roster cohort, 2026-09-28)
- **Exact columns: `id, courseid, eid, assignments, userid, timesynced, timecreated`** — NO
  `email`/`name`/`status` (the skill's old note "roster row has userid+email" was untested and
  wrong twice in one session: both dead with bare "Error reading from database"). Name/email
  come from `mdl_user` via `userid`. `assignments` is JSON: `{"Lec":"C01","Lab":"T02","exam":"m1"}`.
- **`IN (…)` on this table triggered the bare "Error reading from database" TWICE** (even with
  named params, even flat) while the identical logic via (a) one `get_records('ltigroups_roster',
  ['courseid'=>3])` fetch + in-PHP set ops, and (b) per-uid `get_record(…, ['courseid'=>3,
  'userid'=>$uid])` in a loop, both worked. When a table is flaky under `IN`, fetch the whole
  small table once (203 rows) and do the set math in PHP.
- Same "selecting a possibly-missing column" signature as §8a: a missing column here reads
  exactly like driver flakiness — probe the schema before retrying.

## 9. Bootstrap + run
```php
define('CLI_SCRIPT', true);
define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php');
require_once('/var/www/html/public/lib/setup.php');
global $DB;
```
Run: `cd /var/www/moodledata/.hermes && timeout 300 php -d display_errors=1 /tmp/x.php`.
If a script prints nothing, capture output to a file (`file_put_contents`) — stdout
can be swallowed under some wrappers.

## 10. Mail
No `sockets` extension; use `stream_socket_client`. Open campus relay
`smtp.cs.cityu.edu.hk:587`, no AUTH/STARTTLS — see the `email-student-group` skill.

## 11. grade_items / grade_grades keying (grading lookups, E-Quiz 2 audit 2026-09-22)
- **`grade_items` is looked up by `itemmodule` + `iteminstance` + `courseid`**, NOT by the
  course-module id. `get_record('grade_items', ['itemmodule'=>'quiz','iteminstance'=>$quizid,
  'courseid'=>$cid])`. Passing `['itemid'=>$cmid]` → bare "!!! Error reading from database !!!".
- **`grade_grades` is keyed by `itemid` = `grade_items.id`** (e.g. 61), NOT the cmid.
  `SELECT ... FROM {grade_grades} WHERE itemid=<cmid>` silently returns 0 rows — join on the
  grade-item id.
- **`grade_items.hidden` is a TIMESTAMP** (epoch) — the time the item becomes hidden (the close
  time), NOT a 0/1 flag. `date('Y-m-d H:i', (int)$gi->hidden)`.
- **`grade_items.maxgrade` is often blank/NULL** for quizzes (computed); the authoritative
  gradebook max is `grade_grades.maxgrade`, which equals `mdl_quiz.grade`.
- **Raw quiz marks are on a different scale than the gradebook.** `quiz_attempts.sumgrades` is the
  internal raw (E-Quiz series = 23 max); `grade_grades.rawgrade`/`maxgrade` is the gradebook scale
  (= `mdl_quiz.grade`, e.g. 80). A perfect raw 23/23 → rawgrade 80.0/80. So "slot marks don't sum
  to the quiz grade" is NOT a bug — Moodle auto-scales. Verify via `MAX(grade_grades.rawgrade)`.

## 11b. Quiz-attempt / step-table schema traps (E-Quiz 2 absent-zero batch, 2026-09-24)
- **`mdl_question_attempt_step_data.attemptstepid` → `mdl_question_attempt_steps.id`,
  NOT `mdl_question_attempts.id`.** Counting manual grades joined to question_attempts
  returned "0 steps" (false alarm that nearly flipped a committed grade back).
  Correct: `... WHERE d.name='-mark' AND d.attemptstepid IN (SELECT s.id FROM
  mdl_question_attempt_steps s WHERE s.questionattemptid IN (SELECT id FROM
  mdl_question_attempts WHERE questionusageid=<usid> AND slot>1))`.
- **`mdl_question_attempt_steps` has NO `name` column** (id, questionattemptid,
  sequencenumber, state, fraction, timecreated, userid). Step "names" live in
  step_data rows (`-mark`, `-comment`, `-finish`, `-_try` …). `s.userid` = actor.
- **`mdl_question_attempt_step_data` has ONLY** id, attemptstepid, name, value —
  no userid/timecreated (selecting them = "Unknown column").
- **MCP `query` tool blocks "CREATE"/"DELETE" substrings anywhere — INCLUDING in
  your aliases.** `timecreated` in a SELECT is rejected, AND `AS created` /
  `AS qcreated` also trip it (it scans the whole query text, not just column refs).
  Use a non-colliding alias (`s.timecreated AS tc`) or drop the column. The tool's
  parameter is `query` (not `sql`). Cost ~2 calls on 2026-09-28.
- `mdl_quiz_attempts`: no `grade`, no `maxgrade` columns (sumgrades, uniqueid,
  timefinish …). `mdl_quiz_slots`: no `questionid` (question lives on
  `mdl_question_attempts`).
- `mdl_question_usages` has only id, contextid, component, preferredbehaviour —
  NO `quiz`/`usageid`; its `id` == `mdl_question_attempts.questionusageid`.
- Internal messages in this fork = **`mdl_notifications`** (useridfrom, useridto,
  subject, fullmessagehtml, customdata.notificationiconurl, timeread);
  `mdl_message` is empty. Popup links:
  `mdl_message_popup_notifications.notificationid`. Re-attribution after a wrong
  sender: UPDATE useridfrom + regenerate notificationiconurl in customdata.
- `mdl_user` has no `shortname`/`fullname` (firstname/lastname); `mdl_config`
  mail rows: only `mailnewline` etc. here — relay is raw ESMTP (see mail skills).

## 11c. CodeRunner options schema + live-pipeline class loading (E-Quiz 7 file-question review, 2026-09-24)
- **`mdl_question_coderunner_options` has NO `prototype` / `prototypeno` column**
  (I guessed both and got "Unknown column" twice). It has: `coderunnertype`,
  `prototypetype` (0 = uses a named prototype; non-0 = IS a prototype),
  `precheck`, `allornothing`, `hidecheck`, `answerpreload`, `globalextra`,
  `answer`, `extractcodefromjson`, `twigall`, `templateparamslang`,
  `templateparamsevald`, `language`, `sandbox`, `sandboxparams`, `grader`,
  `attachments`, `iscombinatortemplate`, `combinatortemplate`, … Probe
  `information_schema.columns` / `SHOW COLUMNS` before selecting. The
  prototype is NOT a column — it's a *separate question* resolved by
  `coderunnertype` name (see `moodle-quiz-question-review`
  `references/coderunner-file-questions.md` for the resolution query).
- **Do NOT build a live `qtype_coderunner_question` + `grade_response` in CLI
  to "confirm" a CodeRunner bug** — on this 5.2 fork the class-loading is
  fragile and cost ~15 calls with no result. You need
  `question/engine/bank.php` (NOT `lib/questionbank/lib.php` — absent),
  `question/behaviour/behaviourbase.php` +
  `question/behaviour/adaptive/behaviour.php` (the old
  `question_behaviour_with_multiple_tries` is now a class INSIDE
  behaviourbase.php; there is NO `question/behaviour/multitries/` directory),
  then you still have to hand-hydrate the class instance from plain DB rows.
  Static DB evidence (support-file check + predecessor-version attempt
  fractions) reaches the same conclusion in 4 cheap queries. Only go the
  live-PHP route for a brand-new question with no predecessor versions.
- **Multi-line Python probes: write to a `.py` file and run it; don't pipe a
  heredoc through the terminal tool.** A `php/python <<EOF` heredoc came back
  empty twice (flag interception ate the body). `write_file` +
  `python3 /tmp/x.py > /tmp/out.txt` is reliable. Same discipline already in
  §9 for PHP stdout — apply it to Python too.

## 12. Attempt-forensics traps (answer-dispute session, 2026-09-28)
- **`questionusageid` = `quiz_attempts.uniqueid`, NOT `quiz_attempts.id`
  (correction to the earlier note — this one bit hard, 2026-09-28).** This fork's
  `mdl_quiz_attempts` has BOTH `id` and `uniqueid` and they DIFFER (attempt 16569:
  id=16569, uniqueid=16681). `mdl_question_attempts.questionusageid` == `uniqueid`.
  The earlier "returned the correct 17 rows via quiz_attempts.id" was WRONG: `id`
  coincidentally collided with a **stale/ghost `question_usage` of the same number**
  (16569) carrying a different quiz's set, so it returned 17 rows of the WRONG set
  and produced a false "snapshot trap / restored attempt" conclusion that cost the
  afternoon. Always resolve the usage as `quiz_attempts.uniqueid`, then cross-check
  the slot count vs `layout` and confirm the disputed qid is present. (Aligns with
  §11b: "do not join quiz_attempts.id to question_usage.id".)
- **Attempt state can change between passes** while the student is still in the
  window (16569 was `inprogress` in the morning, `finished` by the afternoon — the
  student came back at 13:55 and resubmitted). Re-read `state`/`timefinish`/
  `sumgrades` and the LAST step before reporting; a "ghost option" the student
  complained about may be a transient `todo` re-render that a later `complete` step
  already overwrote.
- **Attempt ≠ current quiz definition (snapshot/restore trap).** An attempt can
  carry a completely different question set than the quiz's current slots (quiz
  restored/re-edited after the attempt; or the attempt itself restored). Restored
  signals: step `timecreated` days EARLIER than `quiz_attempts.timestart`; attempt
  set == a different quiz's current set; `mdl_quiz.timecreated=0`. Always compare
  the attempt's qids vs the current `quiz_slots → question_references →
  question_versions → question` set BEFORE per-slot forensics.
- **logstore schema (this fork):** columns are `eventname, component, action,
  target, objecttable, objectid, contextid, contextlevel, contextinstanceid,
  userid, courseid, other(JSON), timecreated, origin, ip, realuserid` — NO
  `coursemodule`, NO `edata`, and NO `cm` — `WHERE cm = <cmid>` dies with a
  bare "Error reading from database" that looks exactly like driver flakiness
  (cost 2 runs, 2026-10-06 off-lab IP audit). Per-attempt activity (for
  in-window IP pulls) = `eventname LIKE '%attempt%'` (`attempt_viewed` /
  `attempt_updated` / `attempt_submitted`), `contextlevel = 70 AND
  contextinstanceid = <cmid>`; window each attempt by
  `[timestart, timefinish]`. There is NO per-question student
  submit/check event — only page-level `\mod_quiz\event\attempt_*`; raw
  choice data lives solely in `question_attempt_step_data`.
- **Timezone split:** PHP CLI `userdate`/`date()` = Asia/Hong_Kong; MCP `query`
  `FROM_UNIXTIME()` = UTC (8h apart). Print raw unix alongside any formatted time.
- **Multichoice storage here:** complete steps carry ALL `choice0..choiceN`
  explicitly as 0/1 (stock Moodle omits unchecked boxes) + `-submit`, `-_try`,
  `-_rawfraction`. Option letter = position in step-0 `_order` (comma answer-id
  list). `responsesummary`/`rightanswer` are stale text caches — raw step data
  wins.
- **MCP `query` tool**: param name is `query` (not `sql`); single statement
  (no `;` — "syntax error near SELECT" means you sent two).

## 13. Live lab-session cohort traps (CE-Quiz/E-Quiz cross-check, 2026-09-28)
Surfaced while answering "who attempted CE-Quiz 3 today but missed / failed E-Quiz 3" during a running lab. All of these cost real re-runs:

- **`php -r` inline quoting:** wrap the WHOLE script in single quotes for the shell and use **no single-quote literals inside the PHP** (double-quoted strings only). Quote-juggling like `implode("',", …)` breaks the shell. A double-quoted `-r` string needs `\$` for every PHP variable. **Silent exit 255 with zero output = a shell-quoting clash, NOT a PHP error** — fix the quotes before suspecting the DB. (Cost ~4 blind re-runs.) For anything non-trivial, `write_file` a `.php` and run it instead of `-r`.
- **`$DB->prefix` is protected** — use `$P = $DB->get_prefix();` in CLI/inline SQL. Interpolating `{$DB->prefix}` → "Cannot access protected property mariadb_native_moodle_database::$prefix".
- **`component = 'core'` on `mdl_role_assignments` can silently 0-out a role lookup.** A/B, same instant, same literal uid list: 63 rows WITHOUT `AND component='core'`, 0 rows WITH it. The level-50 course-context filter already scopes the assignment. If the student-role join returns empty while the component filter is on, drop the filter and re-run before concluding "no roles exist" (this misclassified all 34 in-progress lab students as "staff").
- **MCP `query` subquery conditions can return a bare 0-row result with NO error.** `WHERE … IN (SELECT …)` came back 0 rows while the expected rows demonstrably existed (a flat literal-uid-list query found them in the same session). A 0 from a subquery-condition query is indistinguishable from genuine absence — and worse when the underlying table is live-changing (attempts flipping `inprogress`→`finished` between queries). If a subquery-condition query returns 0 rows you didn't expect, re-verify with a FLAT literal `IN (1,2,3)` list (or the PHP bootstrap) before reporting "no rows".
- **Duplicate LTI user accounts:** the same student can hold 2+ `mdl_user` rows — same name + email, both `auth=lti`, both `deleted=0` (KHAMZA Rauan: phantom uid 61 with NO enrolments/attempts + real uid 739 enrolled and attempting). `get_record('user', ['email'=>…])` returns the LOWEST id = the phantom → a "ghost" student who appears and disappears between queries. Before reporting a student as anomalous: `SELECT id, auth, deleted FROM mdl_user WHERE email = ?` and confirm the uid that carries the attempt/enrolment is the real one. Flag the duplicate for cleanup (it confuses gradebook/roster tooling).
- **Helpers legitimately attempt CE-Quizzes OFF-schedule** (their override opens a week early, unlimited attempts): starts at 01:23 / 09:48 around a 10:00 lab is normal. Exclude helpers by group membership (match by **name** `helpers`; id 89 in course 3 — verify), NOT by start time. Don't flag off-window starts as anomalies for helpers/teachers.
- **`$DB->get_records_sql` has NO 100-row cap** (that's the MCP `query` tool) — a single `IN (…)` list of a few hundred ids is fine here; you only chunk when the list is huge.

The cross-quiz cohort procedure itself (current vs prerequisite quiz, the moving-target in-progress re-verify, report shape) lives in the `moodle-cross-quiz-cohort` skill.

## 14. More silent failures (dispute follow-up, 2026-09-28)
- **`$DB->get_fields()` does not exist** in this Moodle build →
  "Call to undefined method mariadb_native_moodle_database::get_fields()".
  Use `get_record()` (returns an object; guard with `isset($row->$c)`) or
  `get_record_sql()`.
- **`mdl_logstore_standard_log` has NO `realclient` / user-agent column.**
  Client info = `ip`, `origin`, `other` (JSON), only. Selecting `realclient` →
  bare "Error reading from database" (looks like flakiness, is a missing
  column — same signature as §8a).
- **`mdl_quiz_access_rules` reads can die** with bare "Error reading from
  database" (probe the columns first; SEB rule config may live in
  quiz_access_rules but the schema is version-fragile here — see
  `moodle-seb-quiz-access`).
- **Missing `$DB` methods / undefined constants in this build (2026-10-05):**
  `$DB->get_field_sql_array()` does NOT exist → fatal "Call to undefined
  method mariadb_native_moodle_database::get_field_sql_array()". Use
  `get_records_sql()` + `array_keys()` (or `array_column`). The
  `SQL_SELECT_LIMIT_FIRST` constant is also undefined (fatal "Undefined
  constant") — pass no limit arg to `get_record()`.

## 15. `sumgrades` + time columns: persistent failure, not transient (CE-Quiz 4 check, 2026-10-05)
Querying `mdl_quiz_attempts` with an **explicit field list** that includes
`sumgrades` together with `timestart`/`timefinish` (via `get_records_sql` with
`ORDER BY`, or the 4th-arg field list on `get_records`) failed **persistently**
— 8/8 retries with 3 s sleeps all died with the bare "!!! Error reading from
database !!!" — while `get_records('quiz_attempts', ['quiz'=>N,'userid'=>M],
'id ASC')` with **no field list** succeeded on the first try. This is NOT the
retry-and-it-works flakiness of §4: when a column combo is persistently dead,
the fix is to drop the field list (full-row fetch is fine for a handful of
rows) and keep a small retry loop (sleep 3, ~8 tries) only as a backstop.
Never report "no attempt" on the strength of a failed query.

## 16. Raw mysqli escape hatch + table-name traps (AI-misuse investigation, 2026-10-05)
- **When `$DB` dies persistently on specific tables** (this build: `quiz_slots` and question-attempt queries gave bare "!!! Error reading from database !!!" while `config`/`quiz`/`user`/`quiz_attempts` worked in the same script), bypass the Moodle DB layer with raw mysqli using `$CFG` credentials:
  ```php
  $m = new mysqli($CFG->dbhost ?: 'localhost', $CFG->dbuser, $CFG->dbpass, $CFG->dbname,
                  !empty($CFG->dbport) ? (int)$CFG->dbport : 3306);
  $m->set_charset('utf8mb4');
  ```
  Direct SQL on `mdl_*` then works and is fast (a `SHOW PROCESSLIST` confirmed no locks — it was a driver-layer problem, not the DB). This became the reliable path for question-attempt forensics on this build.
- **Table-name traps:** the per-question table is `mdl_question_attempts` (PLURAL). `get_records('question_attempt', …)` / queries on `mdl_question_attempt` fail with a bare DB error that looks exactly like driver flakiness. `mdl_question_grade` does NOT exist in this build — per-question earned marks come from the LAST step's `fraction * maxmark` (§8b).
- **`mdl_question_attempts.rightanswer` = the MODEL/reference solution** (answer key — identical for every student and every attempt of the same question), NOT the student's answer. The student's submitted code (CodeRunner) is in `responsesummary`. (The §12 "responsesummary/rightanswer are stale caches" note is about MCQ; for CodeRunner, `responsesummary` IS the submitted code.)

## 17. `$DB` returns STRINGS — never `!==` / `===`-compare a column to an int literal
`get_record` / `get_records_sql` / `get_recordset_sql` return column values as PHP
**strings**. A strict comparison to an int literal is therefore FALSE: `"3" !== 3`,
`"1" !== 1`. This produced a false `ABORT: quiz 47 not found or wrong course` in a
SEN-override script (the quiz was fine — `course="3"` compared `!== 3`). Coerce first:
`(int)$row->course === 3`, compare loosely `==`, or compare to the string `'3'`.
Same trap in a manual `foreach` + `!==` over DB string values. (`in_array($val, [3,4,5])`
is loose-by-default so it's fine — only hand-rolled strict comparisons bite.) 2026-10-06,
cost one aborted run + a re-diagnosis.

## 18. Correlated MAX subqueries die; use a derived-table GROUP-BY join (E-Quiz 5 audit, 2026-10-13)
To get each question's LAST step (max `sequencenumber`), the intuitive correlated form dies with a bare "!!! Error reading from database !!!" on this build:
```sql
... AND s.sequencenumber = (SELECT MAX(s2.sequencenumber) FROM {question_attempt_steps} s2
    WHERE s2.questionattemptid = qat.id)   -- DEAD
```
`... WHERE s.id IN (SELECT MAX(id) FROM {question_attempt_steps} GROUP BY questionattemptid)` is also DEAD. The RELIABLE replacement (used ~10× in one run, all worked) is a derived-table GROUP-BY join:
```sql
JOIN (SELECT questionattemptid, MAX(sequencenumber) m
      FROM {question_attempt_steps} GROUP BY questionattemptid) x
     ON x.questionattemptid = qat.id
JOIN {question_attempt_steps} s
     ON s.questionattemptid = qat.id AND s.sequencenumber = x.m
```
Bisect with a tiny 5-row probe first — a small variant of a dead shape can still work, which hid the pattern. (Complements §4 "keep queries flat / no subqueries" and §13 "MCP subquery conditions can return bare 0-rows".) Also from this run: the last-step VALUE column is `s.fraction` (nullable decimal) + `s.state` — there is NO `s.data` column (selecting it = bare error; see §11b schema list).

## 19. `role_assignments` two-condition reads die; single-condition + PHP-intersect works (2026-10-13)
- `$DB->get_records('role_assignments', ['roleid'=>4,'courseid'=>3])` → bare "Error reading from database" (2-condition array on this table is blocked).
- `SELECT ra.userid FROM {role_assignments} ra JOIN {role} r ON r.id=ra.roleid WHERE r.shortname='teacher' AND ra.courseid=3` → bare DB error (the `ra.courseid=3` predicate on the JOIN is blocked).
- WORKING: the plain shortname query with NO courseid (`... WHERE r.shortname='teacher'`) returns ALL teachers site-wide; then intersect in PHP with the course enrolment set (the `{user_enrolments}` + `{enrol}` join on `e.courseid=<cid>` works fine — that one is not blocked). `$DB->get_field('user','username',['id'=>$u])` in a 244-iter loop also worked fine, so the block is table/predicate-specific, not a blanket get_records failure. (Related: §13 `component='core'` 0-ing, §15 field-list column combos.)

## Pointer
The general DB-access layer (bootstrap variants, full table map, which `$DB`
methods work) lives in the `moodle-db-access` skill — this skill is the pitfall
overlay for when you're writing ad-hoc scripts.
