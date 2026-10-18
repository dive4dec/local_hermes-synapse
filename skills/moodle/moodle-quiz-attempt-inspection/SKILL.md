---
name: moodle-quiz-attempt-inspection
description: "Inspect quiz attempts on dive.cs.cityu.edu.hk (Moodle 5.x): count attempts by state, track in-progress attempts with last-activity liveness, and cross-check sessions/IPs during live quiz sessions."
---

# Moodle Quiz Attempt Inspection

Inspect who attempted a quiz, who is currently in progress, how far they've gotten, and where they're connecting from. All queries verified 2026-09-14 against CE-Quiz 1 (quiz id 58, cs1302a_26a).

## Triggers

- "How many students attempted <quiz>?"
- "Who is in progress / still in the session?"
- "List the students with difficulties in each question"
- "Why did <student> lose marks on <question>?"
- Monitoring a live CE-Quiz lab session
- Checking liveness (last activity) of an in-progress attempt

## Core facts

- Attempts: `mdl_quiz_attempts` — `state` is a **VARCHAR** (`'inprogress'`/`'finished'`/`'aborted'`), all times are **UTC epoch ints** (`timestart`, `timefinish`, `timemodified`).
- Join chain to question-level data (verified): `mdl_quiz_attempts.uniqueid = mdl_question_usages.id` (NOT a `questionusageid` column on quiz_attempts — there is none) → `mdl_question_attempts.questionusageid = mdl_question_usages.id`.
- `mdl_question_attempts` has **no state column** — per-question activity is in `mdl_question_attempt_steps` (state varchar: 'notflagged'/'flagged'/'finished' etc.; per-question `timemodified` also works).
- Group membership: `mdl_groups_members` (a user can be in multiple groups — one group per row; lab students are in exactly one).
- Session/IP: `mdl_sessions` (`userid`, `firstip`, `lastip`, `timemodified`). No row = not currently logged in.
- Log store: `mdl_logstore_standard_log` — quiz events have `component='mod_quiz'` (no `modulename` column), `objectid` = quiz id, `courseid` = course id, plus `ip`. Event names: `attempt_started`, `attempt_viewed`, `attempt_updated`, `attempt_autosaved`, `attempt_submitted`, `attempt_graded`, `attempt_reviewed`, `attempt_deleted`, `attempt_preview_started`.
- Teachers (editing/non-editing) are **not bound by quiz timelimit** — an in-progress teacher attempt sitting open for hours/days is normal, not a red flag. Helpers (group 89) and test accounts (e.g. "Adam LTITEST" uid 502) are also legitimate.

## Query templates (moodle_db MCP, param name `query`, limit 100 rows)

### 1. Count attempts by state

```sql
SELECT COUNT(*) AS total,
       SUM(CAST(state='inprogress' AS UNSIGNED)) AS in_progress,
       SUM(CAST(state='finished' AS UNSIGNED)) AS finished,
       SUM(CAST(state='aborted' AS UNSIGNED)) AS aborted,
       COUNT(DISTINCT userid) AS distinct_users
FROM mdl_quiz_attempts WHERE quiz = 58
```

(Use `CAST(state='...' AS UNSIGNED)` — bare `SUM(state=0)` works but string states make CAST the explicit form.)

### 2. Attempt list with identity + group

```sql
SELECT qa.id AS attempt_id, u.id AS userid, u.firstname, u.lastname, g.name AS groupname,
       qa.timestart, qa.timefinish, qa.state, qa.timemodified
FROM mdl_quiz_attempts qa
JOIN mdl_user u ON u.id = qa.userid
LEFT JOIN mdl_groups_members gm ON gm.userid = qa.userid
LEFT JOIN mdl_groups g ON g.id = gm.groupid
WHERE qa.quiz = 58
ORDER BY qa.timestart
```

### 3. Liveness / progress (per attempt, last activity)

```sql
SELECT qa.id AS attempt_id, u.firstname, u.lastname, g.name AS groupname,
       qa.timestart, qa.state,
       COUNT(DISTINCT qs.questionid) AS questions_in_quiz,
       MAX(qs.timemodified) AS last_activity
FROM mdl_quiz_attempts qa
JOIN mdl_user u ON u.id = qa.userid
LEFT JOIN mdl_groups_members gm ON gm.userid = qa.userid
LEFT JOIN mdl_groups g ON g.id = gm.groupid
JOIN mdl_question_usages qu ON qu.id = qa.uniqueid
JOIN mdl_question_attempts qs ON qs.questionusageid = qu.id
WHERE qa.quiz = 58
GROUP BY qa.id, u.firstname, u.lastname, g.name, qa.timestart, qa.state
ORDER BY qa.timestart
```

Compare `last_activity` against `UNIX_TIMESTAMP()` (query it separately: `SELECT UNIX_TIMESTAMP() AS now_epoch`) — elapsed = now - last_activity. A student active a few minutes ago is live; an in-progress row with no `mdl_sessions` entry is an abandoned/stale attempt.

### 4. Per-question drill-down for one attempt (given its question_usages id)

```sql
SELECT qs.id AS question_attempt_id, qs.slot, qs.questionid, qs.timemodified,
       COUNT(qas.id) AS steps, MAX(qas.sequencenumber) AS last_seq, MAX(qas.state) AS last_step_state
FROM mdl_question_attempts qs
JOIN mdl_question_attempt_steps qas ON qas.questionattemptid = qs.id
WHERE qs.questionusageid = <qu.id>
GROUP BY qs.id, qs.slot, qs.questionid, qs.timemodified
ORDER BY qs.slot
```

Find the `qu.id` first: `SELECT qu.id FROM mdl_question_usages qu JOIN mdl_quiz_attempts qa ON qa.uniqueid = qu.id WHERE qa.id = <attempt_id>`.

### 5. Is the user currently logged in (session IP)?

```sql
SELECT s.userid, u.firstname, u.lastname, s.firstip, s.lastip, s.timemodified
FROM mdl_sessions s JOIN mdl_user u ON u.id = s.userid
WHERE s.userid = <userid>
```

Campus/lab IPs for CS1302: `175.159.202.0/24` (on-site lab, not VPN).

### 6. Per-question difficulty (who struggled on each question)

Final state + fraction per (attempt, question) = the **last step** (`MAX(sequencenumber)`) of `mdl_question_attempt_steps`:

```sql
SELECT u.lastname, u.firstname, qa.timestart, qa.state AS attempt_state,
       qs.slot, q.name AS question, qas_final.state AS final_state, qas_final.fraction
FROM mdl_question_usages qu
JOIN mdl_quiz_attempts qa ON qa.uniqueid = qu.id
JOIN mdl_user u ON u.id = qa.userid
JOIN mdl_question_attempts qs ON qs.questionusageid = qu.id
JOIN mdl_question q ON q.id = qs.questionid
JOIN (SELECT questionattemptid, MAX(sequencenumber) AS maxseq
      FROM mdl_question_attempt_steps GROUP BY questionattemptid) f
  ON f.questionattemptid = qs.id
JOIN mdl_question_attempt_steps qas_final
  ON qas_final.questionattemptid = qs.id AND qas_final.sequencenumber = f.maxseq
WHERE qa.quiz = 58 AND qs.maxmark > 0
ORDER BY qs.slot, qa.timestart
```

Final-step states seen in practice (Code Runner, `adaptive_adapted_for_coderunner` behaviour):
- `gradedright` (fraction ~1) = solved; `gradedpartial` = partial credit from some passing tests; `gaveup` = student gave up (0); `complete` = code ran but question not yet closed (in-progress attempts); `todo` = never touched.
- **Difficulty flags:** `gaveup` or fraction 0 = struggled; `gradedpartial` with fraction < 1 = partially got it; `gradedpartial` with fraction 1.0 = full marks but state label stuck (harmless adaptive-behaviour quirk); `todo` on a finished attempt = skipped.
- `AND qs.maxmark > 0` excludes description/information slots.
- For "struggled" list: `WHERE ... AND (qas_final.state IN ('gaveup','gradedpartial') OR qas_final.fraction < 1)`; group by question and count distinct users.
- Multiple attempts per user: report the latest (or the user's best/worst per policy); helpers have unlimited attempts, so dedupe with a `MAX(qa.timestart)` subquery per user if needed.

### 7. Why a student lost marks on a Code Runner question (step-data forensics)

Code Runner stores everything per step in `mdl_question_attempt_step_data` (`attemptstepid`, `name`, `value`). Keys worth knowing:
- `answer` — the student's code at that step
- `_testoutcome` — a **PHP-serialized** `qtype_coderunner_testing_outcome` with `maxpossmark`, `actualmark`, and a `testresults` array: per-test `testcode`, `stdin`, `expected`, `got`, `mark`, `awarded`, `iscorrect`, plus `errormessage`. Grep for `NameError`/`***Run error***` in `got` to see the exact failure.
- `-_rawfraction` — raw fraction from that submit (vs `qas.fraction`, which the **adaptive behaviour** adjusts by the fraction used).
- `-_try`, `-_precheck` — try counter and whether the step ran precheck tests only.
- `_STUDENT` — serialized student identity (incl. `canviewhidden`).

Query pattern (per attempt + slot):

```sql
SELECT qas.sequencenumber, qas.state, qas.fraction, qad.name, qad.value
FROM mdl_question_usages qu
JOIN mdl_question_attempts qs ON qs.questionusageid = qu.id
JOIN mdl_question_attempt_steps qas ON qas.questionattemptid = qs.id
JOIN mdl_question_attempt_step_data qad ON qad.attemptstepid = qas.id
WHERE qu.id = <usageid> AND qs.slot = <slot>
  AND qad.name IN ('answer','-submit','-_rawfraction','-_try','-_precheck')
ORDER BY qas.sequencenumber
```

Interpretation rules:
- **`rawfraction < 1` with `actualmark == maxpossmark`** on a later submit means the student eventually solved it; the earlier submits show exactly what broke (read `_testoutcome` `got`/traceback).
- **Final `fraction` = 0.9 with all tests `awarded 1.0` and `_rawfraction 1`** = adaptive-behaviour deduction for having consumed earlier tries (100% on attempt 2 of a 2-try budget), NOT a mark deducted from the final code.
- **Final state `gradedpartial` with `fraction 1.0`** = highest raw fraction across submits was a partial; state label is the last submit's, fraction is the best. Harmless for grading.
- To see what the hidden tests actually require, read the question stem (`mdl_question.questiontext`) — the stem may require specific variable names that only the hidden tests enforce (see CS1302 `print - concat to get url`, qid 3562: hidden tests run `assert domain == "..."`, so the input MUST be stored in a variable literally named `domain`; the visible example test only checks stdout).

### 8. Log-store IP/history — PHP bootstrap only

MCP **cannot** query the log store by time or `timecreated` (keyword filter, see Pitfalls). Use the PHP bootstrap (see `moodle-db-access` skill):

```php
define('CLI_SCRIPT', TRUE);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/fix.php';
require_once('/var/www/html/config.php');
date_default_timezone_set('Asia/Hong_Kong');
$rows = $DB->get_records_sql("
    SELECT eventname, userid, ip, timecreated
    FROM {logstore_standard_log}
    WHERE courseid = 3 AND component = 'mod_quiz' AND objectid = 58
      AND eventname IN ('\\mod_quiz\\event\\attempt_started', '\\mod_quiz\\event\\attempt_submitted', '\\mod_quiz\\event\\attempt_viewed')
    ORDER BY timecreated DESC LIMIT 100");
foreach ($rows as $r) { echo date('m-d H:i:s', $r->timecreated), ' ', $r->eventname, ' uid=', $r->userid, ' ip=', $r->ip, PHP_EOL; }
```

## Pitfalls

- **MCP SQL keyword filter is substring-based**: any SQL containing "CREATE", "DELETE", "REPLACE" is rejected. That blocks `timecreated` (contains CREATE) and `deleted` columns in SELECT/WHERE, plus DELETE statements. Workarounds: use `timemodified`/`sequencenumber` instead of `timecreated`; use the PHP bootstrap when you truly need those columns (log-store time filters, log `ip` history).
- **`NOW()` arithmetic is broken via MCP**: `(NOW() - timestart)` casts NOW() to a number like 20260914010114 → garbage. Get "now" with `SELECT UNIX_TIMESTAMP()` and do arithmetic in post-processing or `UNIX_TIMESTAMP() - timestart`.
- **`FROM_UNIXTIME(x, fmt)` format arg is stripped by MCP** — results come back as UTC strings; convert in post-processing.
- **MariaDB: no `LIMIT` inside `IN (SELECT ...)` subquery** — wrap in a derived table instead.
- **Teachers' long-open in-progress attempts are normal** (timelimit not enforced for them); no `mdl_sessions` row = session gone, attempt just never submitted.
- **Distinct users < total attempts** is expected (helpers/teachers have unlimited attempts).
- MCP returns at most 100 rows — for "all attempts of a large quiz" add `GROUP BY` aggregates or filter by state/time.
- `state` comparisons must use the string values (`'inprogress'`), not 0/1/2 — although numeric casts happen to match, string form is correct.

## Reference (cs1302a_26a, course id=3)

- CE-Quiz 1 = quiz 58: 5 questions, `timelimit=2700`, `attempts=1`. Group sizes: T03=65, T01=59, T02=69, TA1=10, helpers=22.
- Ziyu ZHUANG (uid 726, LTI) is a non-editing teacher — her attempts are legitimate.
