---
name: moodle-absent-zero-grade
description: Mark quiz grade zero for absent students (all questions) OR for a single question a present student failed to explain — per-question manual 0 + comment + gradebook recompute; compare E-Quiz vs CE-Quiz activity to decide what a notice may say; send individualized or simple notice emails. Use when the user asks to "mark zero", "zero the absentees", "mark question N as 0", or email students about such grade changes.
---

# Zero-grade absent quiz students + individualized notices

Full pipeline that worked for <coursecode> E-Quiz 2 (2026-09-24): per-question manual
zero with a standard absence comment, gradebook recompute, E-Quiz vs CE-Quiz
activity comparison per student, and individualized urgent emails.

## Step 0 — verify the bound Moodle account (costs 1 wrong sender, 2026-09-24)
The agent's Moodle identity can be stale: `$HERMES_HOME/.moodle_identity` is
last-writer-wins and any other admin's LTI chat overwrites it. Before ANY
attribution-sensitive action (sending messages/email as the teacher, grading):
- `moodle_get_my_courses` → confirm the expected account (e.g. <Instructor-Name>, uid 494).
- If wrong: write the per-session file
  `$HERMES_HOME/run/identity/$HERMES_SESSION_KEY.identity.json` as
  `{"username":"<LTI username>","userid":"<id>"}` AND fix the legacy
  `.moodle_identity` the same way. LTI username =
  `SELECT username FROM mdl_user WHERE id=<id>` (starts `enrol_lti...`).

## Step 1 — resolve students + attempts (read-only)
- Resolve names to userids via course roster:
  `SELECT u.id,u.firstname,u.lastname,u.email,u.suspended FROM mdl_user u
   JOIN mdl_user_enrolments ue ON ue.userid=u.id JOIN mdl_enrol e ON e.id=ue.enrolid
   WHERE e.courseid=<cid> AND u.firstname LIKE ... OR u.lastname IN (...)`.
  First names are usually unique — disambiguate with `SELECT id,firstname
  FROM mdl_user WHERE lastname='LI'`.
- Attempts: `SELECT id,userid,uniqueid,sumgrades,state FROM mdl_quiz_attempts
  WHERE quiz=<quizid> AND userid IN (...)`. `uniqueid` = the question usage id
  used by `mdl_question_attempts.questionusageid`.
- Per-student scored question count (skip description questions):
  join `mdl_question_attempts.questionid` → `mdl_question.qtype`.
- **Guard**: abort if `state` is not finished, or if manual `-mark` steps already
  exist (avoid double-grading). Pre-existing manual-mark check (CORRECT join, see
  pitfalls):
  ```sql
  SELECT COUNT(*) FROM mdl_question_attempt_step_data d
  WHERE d.name='-mark' AND d.attemptstepid IN
    (SELECT s.id FROM mdl_question_attempt_steps s
     WHERE s.questionattemptid IN
       (SELECT id FROM mdl_question_attempts
        WHERE questionusageid=<usid> AND slot>1))
  ```

## Step 2 — apply the manual zero (PHP CLI, dry-run first)
The ONLY reliable way (verified): `question_attempt::manual_grade()` + engine save,
then force the quiz total + recompute the gradebook. Key facts:
- The attempt's `questions_usage` object is the PRIVATE `quba` property of
  `\mod_quiz\quiz_attempt` — read it via ReflectionProperty (setAccessible).
  Do NOT rebuild a fresh usage — it detaches from the attempt's observer.
- `manual_grade($comment, 0, FORMAT_MOODLE, time(), $byuserid)` on
  `$ao->get_question_attempt($slot)` works per slot; it appends a step with
  `-mark`, `-maxmark`, `-comment`, `-commentformat` and sets state `mangrwrong`.
- Persist with `question_engine::save_questions_usage_by_activity($quba)`.
- Then: `set_field quiz_attempts sumgrades='0'`, `timemodified=time()`, and
  `\mod_quiz\quiz_settings::create($quizid)->get_grade_calculator()->recompute_final_grade($userid)`.
- Grade item for the gradebook: `get_record('grade_items', ['itemmodule'=>'quiz',
  'iteminstance'=>$quizid, 'courseid'=>$cid])` → its `id` is the `itemid` used
  in `grade_grades` (NOT the cmid).
- Fire `\mod_quiz\event\question_manually_graded` per slot (objectid=questionid,
  other: quizid/attemptid/slot, course/module context) so logs are complete.

Safety pattern (MUST follow — a real incident left 0/80 without steps once the
wrong verification join gave false "0 steps" alarms):
1. **Backup** all rows to be touched (attempt row, grade_grades row) to
   `/tmp/<quiz>_<batch>_backup.json` BEFORE the transaction.
2. One delegated transaction per student; inside it: apply all slots, save,
   **re-count manual `-mark` steps from the DB using the CORRECT join** (Step 1)
   and abort+rollback if not exactly `n_scored`; set sumgrades; recompute; read
   back `sumgrades`/`rawgrade` in-transaction.
3. Dry-run pass (rollback at end) over ALL students first, then `--commit` pass.
4. **Post-commit** re-verify from a fresh DB read (separate MCP query), then
   `purge_caches()` and `moosh -n cache-clear`.

Bootstrap + run:
```
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('<webroot>/config.php'); require_once('<webroot>/lib/setup.php');
require_once('<webroot>/mod/quiz/locallib.php');
require_once('<webroot>/mod/quiz/classes/quiz_attempt.php');
require_once('<webroot>/question/engine/lib.php');
require_once('<webroot>/question/engine/datalib.php');
```
`cd <datadir>/.hermes && timeout 300 php -d display_errors=1 /tmp/x.php`

Standard comment used (approved by instructor, 2026-09-24):
"Marked 0: the student was absent from the lecture session where answers were
sampled for explanation and could not explain the working. Awarded 0 per course
policy."

Single-question variant (present student who failed to explain ONE question,
2026-09-24): same mechanism, but loop over ONE slot only. Compute the new
sumgrades as old − that question's current earned marks (set it explicitly in the
script — do NOT hardcode 0), keep the recompute, and use a "present but could
not explain" comment. In-tx guard becomes: exactly 1 manual `-mark` step on that
question attempt AND 0 on every other slot. Email tone: non-urgent (student was
present), no attendance warning, "feel free to contact me".

## Step 3 — E-Quiz vs CE-Quiz activity comparison (per student)
INSTRUCTOR NUMBERING RULE (2026-09-24): "Question N" = the N-th SCORED question —
the first slot is the Information/description page and is NOT Question 1. For the
E-Quiz 2 layout (16 scored slots after slot 1): MCQs = Questions 1–9 (slots 2–10),
coderunner = Questions 10–16 (slots 11–17). "Question 10" = Quotient (slot 11),
NOT "float division" (slot 10). Always show the mapping and confirm with the
instructor before acting on a question-number reference.
Used to decide what the notice may claim about whether the student did the work.
- "Checks" = CodeRunner test runs = count of `mdl_question_attempt_step_data`
  rows with `name='-_try'` for the question's `questionattemptid`.
- The two quizzes usually share only ONE question (E-Quiz 2 vs CE-Quiz 2 shared
  qid 3601 "Temperature transformation"). Find overlap:
  ```sql
  SELECT n.id,n.name FROM mdl_question n
  WHERE n.id IN (SELECT questionid FROM mdl_question_attempts WHERE questionusageid=<e_usid>)
    AND n.id IN (SELECT questionid FROM mdl_question_attempts WHERE questionusageid=<ce_usid>)
    AND n.qtype<>'description';
  ```
- Compare that question's `-_try` count in the E-Quiz vs the CE-Quiz attempt.
- Student may have NO CE-Quiz attempt at all → no comparison possible; the email
  must omit any activity-record paragraph.

## Step 4 — individualized notice emails
Instructor rules (2026-09-24, after two corrections — do not regress):
- **Do NOT** accuse the student of not doing the work unless the evidence is
  paramount; phrase lower check counts as "consistent with the work not having
  been carried out during the session" (inference, not finding).
- **Do NOT** claim "repeated offence" without a documented prior incident.
- **Do NOT** threaten expulsion (course-level zero notices) unless instructed.
- **Do NOT** demand immediate contact; instead tell them to attend coming
  lectures, that they are likely to be sampled again, and that the E-Quiz grade
  is a significant part of continuous assessment.
- Each student's email must be different: tailor the activity paragraph from the
  Step 3 result (e.g. "7 test runs in E-Quiz 2 against 5 in CE-Quiz 2" — and note
  the zero is due to absence, not missing work, when E-Quiz activity is healthy).
- Urgent tone, factual, signed with the instructor's name.

Send via the `email-student-group` / `campus-smtp-email` skills (raw ESMTP to
`<smtp-host>:587`, From `<staff-email>`), one private email
per recipient, check `emailstop` first, ~1s pacing, collect `250 2.0.0 <queueid>`
lines. Present the drafts and get explicit confirmation before sending.

## Pitfalls (learned the hard way, 2026-09-24)
- **`question_attempt_step_data.attemptstepid` → `question_attempt_steps.id`,
  NOT `question_attempts.id`.** Joining to question_attempts gave "0 manual
  steps" false alarms (and one near-miss inconsistent grade state). Always
  verify steps through the steps table (pattern in Step 1).
- `mdl_question_attempt_steps` has **no `name` column** (only id,
  questionattemptid, sequencenumber, state, fraction, timecreated, userid) —
  inventing `s.name` fails; step semantics come from step_data names.
- `mdl_question_attempt_step_data` has ONLY id, attemptstepid, name, value — no
  userid/timecreated (actor/timestamp live on the step row).
- MCP `query` tool rejects "CREATE"/"DELETE" substrings — `timecreated` in a
  query is blocked; alias it away (`s.timecreated AS tc`) or drop it.
- `mdl_quiz_attempts` has no `grade` column; `mdl_quiz_slots` has no
  `questionid` (it's on `mdl_question_attempts`).
- Internal messages in this fork live in `mdl_notifications` (useridfrom,
  useridto, subject, fullmessagehtml, customdata.notificationiconurl) —
  `mdl_message` is empty; popup links:
  `mdl_message_popup_notifications.notificationid`. Re-attribution after a wrong
  sender = update `useridfrom` + regenerate the icon URL in customdata.
- Moodle-native email is dead on this pod (no SMTP config, sendmail→busybox);
  raw ESMTP is the only outbound mail path.
