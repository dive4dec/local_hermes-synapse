---
name: moodle-cross-quiz-cohort
description: "Cross-quiz student cohort: who attempted quiz X (e.g. a live CE-Quiz lab) but did NOT attempt quiz Y (e.g. the prior E-Quiz), or scored below a threshold on quiz Y. Live-lab-aware: moving-target in-progress set, off-schedule helpers, duplicate LTI accounts, gradebook-scale thresholds. Use for 'check students doing CE-Quiz N now who missed / failed E-Quiz N', 'who took the lab quiz without doing the prep quiz', any two-quiz attendance/pass cross-check."
---

# Cross-Quiz Cohort (current quiz vs prerequisite quiz)

Answer: which students **attempted quiz X** (usually a live CE-Quiz lab) but
**did not attempt quiz Y** (usually the one-week-earlier E-Quiz) — or attempted
Y but scored **below a threshold**. This is a *two-quiz* cross-check, distinct
from single-quiz cohorts (`moodle-equiz-student-status`: A/B/C on one quiz) and
question-level progress (`moodle-quiz-question-progress`).

Worked example (2026-09-28, course 3 cs1302a_26a): "students attempting CE-Quiz 3
(id 62) now who have not attempted E-Quiz 3 (id 61) or got below 50%." Result:
of 64 same-day starters, **3 real students** flagged (2 never did E-Quiz 3, 1 at
37.7%) + **2 helpers** also took it (excluded from the student cohort).

## Triggers

- "check students attempting CE-Quiz N now who have not attempted / failed E-Quiz N"
- "who took the lab quiz without doing the prep quiz"
- "students in the CE-Quiz who got below X% on the E-Quiz"
- Any "quiz A cohort filtered by quiz B outcome" request
- **Single-quiz roster variant:** "list the students in the LTI group sync who have not submitted E-Quiz N" — one quiz + the LTI roster universe (recipe below; NOT cohorts A/B/C of `moodle-equiz-student-status`)

## Inputs

- `quizA` = the **current** quiz (who's attempting it) — resolve id by (course, name).
- `quizB` = the **prerequisite/threshold** quiz — resolve id by (course, name).
- `courseid` (default 3 here).
- `threshold_pct` (default 50) — only relevant if "below X%" is asked.

## Procedure (PHP CLI — reliable; MCP `query` is truncated/flaky here)

Bootstrap: `define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php'); require_once('/var/www/html/public/lib/setup.php');
global $DB; $P = $DB->get_prefix(); date_default_timezone_set('Asia/Hong_Kong');`

1. **Resolve ids + scales.** `mdl_quiz` by (course, name) for both. The **threshold
   comes from quiz B's gradebook**: `finalgrade / mdl_quiz.grade` of quiz B. NEVER
   `sumgrades / quiz.grade` — `sumgrades` is on the question-mark scale (E-Quiz
   series = 23; gradebook = 80). See `moodle-mcp-db-query` "score reports" scale trap.

2. **Cohort = non-preview quiz-A attempts started in the window.**
   - If mid-session: `WHERE quiz=A AND preview=0 AND state='inprogress'`.
   - **This is a moving target.** Under the 45-min limit a whole lab cohort can
     flip `inprogress`→`finished` within minutes, and the live DB shifts between
     queries. When the session has ended, define the cohort as
     `WHERE quiz=A AND preview=0 AND timestart >= <start of today's lab window>`
     and state the window in the answer. Read `mdl_quiz_overrides` (quiz=A) for
     the day's lab slots to know which windows actually ran (e.g. T03 10:00–10:50,
     T01/TA1 15:00–15:50).
   - **Re-verify each flagged student's quiz-A attempt still exists at report time**
     (the set changes under you).

3. **For each cohort student, classify on quiz B:**
   - no attempt → **flag** ("no E-Quiz attempt").
   - attempt `inprogress` / `aborted` → **flag** ("not finished").
   - attempt `finished` + gradebook `finalgrade` NULL/'' → **flag with note**
     ("submitted, grade pending") — the gradebook **lags**; one read empty, next
     read populated. Don't count as not-attempted.
   - attempt `finished` + `finalgrade < threshold` → **flag**.
   - attempt `finished` + `finalgrade >= threshold` → OK.

4. **Filter the student cohort:**
   - **Pick the universe the question names — roster vs enrolled.** "Students in the
     LTI roster who …" ⇒ compute the set from `mdl_ltigroups_roster` (courseid-scoped,
     `userid` non-null) directly; do NOT substitute the enrolled-based cohort from
     `moodle-equiz-student-status` (helpers/test/manual enrolments make enrolled ⊋
     roster — 228 vs 203 in course 3, 2026-09-28 — even though the real-student
     not-attempted list happened to be the same 13 either way). Roster table schema +
     flaky-`IN` workaround: `moodle-php-cli-pitfalls` §8c.
   - Keep only users with the **student role** at the level-50 course context
     (`mdl_role` shortname `student`; `mdl_context` contextlevel 50, instanceid=courseid).
     If the role join returns **empty**, drop a `component='core'` filter before
     concluding "no roles" (see pitfall below).
   - **Exclude helpers** by group membership — match the `helpers` group by
     **name** (id 89 in course 3, verify per semester), not by id or by start time.
     Helpers open a week early with unlimited attempts, so off-schedule starts
     (01:23, 09:48) are normal — list them separately, don't flag them.
   - **Drop phantom LTI accounts** (see pitfall).
   - Non-student-role users (teachers) are timelimit/window-exempt — list separately.

5. **Enrich** flagged rows with the lab group (Lec `C01`/`CA1`, Lab `T0x`/`TA1`,
   project `groupNN`) via `mdl_groups_members` → `mdl_groups` (courseid-scoped),
   and the quiz-A start time.

## Output conventions

- State the **timestamp** and the **window** the cohort is defined over.
- Flagged list: `Name | email | lab group | E-Quiz status (pct + raw + gradebook)`.
- OK count (no names). Excluded helpers/teachers listed separately as
  "also took the quiz — helpers, not students".
- Note the gradebook-lag caveat if any flagged row is "grade pending".

## Single-quiz roster variant: "on the LTI group sync, did NOT submit quiz X"

Standing weekly ask (2026-10-05, "list the students in the LTI group sync but
have not submitted E-Quiz 4"). One quiz + the **LTI roster** as the universe.
This is NOT `moodle-equiz-student-status` cohort B (enrolled-not-attempted, which
also pulls helpers/test/manual enrolments) and not C (roster-but-no-account):
it is roster-with-an-account **minus** finished attempts.

1. **Roster universe:** `get_records('ltigroups_roster', ['courseid'=>$cid])`
   once (203 rows in course 3 — small; §8c: don't `IN (…)` this table). Keep
   rows where `userid` is non-null/`>0` (course 3: 0 unmapped). Schema:
   `id, courseid, eid, assignments, userid, timesynced, timecreated` — the
   student's email is `eid`, name comes from `mdl_user` via `userid`.
2. **Submitted set:** flat `SELECT userid, MAX(timefinish) mf FROM
   {quiz_attempts} WHERE quiz=<quizid> AND preview=0 GROUP BY userid`;
   **submitted** = `mf > 0`. (Starting-but-not-finished = not submitted.)
3. **Cohort = roster uids − submitted uids.** In-PHP set math (§1/§5: intersect
   flat id lists, then flip; don't `array_intersect` two `uid=>true` maps).
4. **Sanity:** `roster_with_account − submitted` must equal the list length
   (203 − 198 = 5 on 2026-10-05). Say the two raw numbers in the answer.
5. **Filter/report:** drop `helpers`-group members and `ltitest`/`@example.com`
   accounts (tag, don't delete); enrich with Lab/Lec from the roster
   `assignments` JSON (`{"Lec":"C01","Lab":"T02",...}`). Present name | email |
   Lab/Lec. Once the quiz window has CLOSED the list is final (state the close
   time); while it's still open, note it's a snapshot.

Verified result (E-Quiz 4, id 63, course 3, closed 2026-10-04): 5 real
students — HE Tsz Fei, HUANG Chenyue, LIU Xuan Lin, WANG Jia Hao, YERGANAT
Miras.

## Follow-up variant: "did these non-submitters attempt quiz Z?"

Recurring follow-up (2026-10-05: right after the E-Quiz 4 LTI non-submitter
list, asked "did these students attempt CE-Quiz 4?"):

1. **Resolve the sibling quiz by name.** Same-week pairing: CE-Quiz N is the
   lab-week quiz; E-Quiz N runs one week earlier (quiz-id table in
   `moodle-cequiz-schedule-propagation`).
2. **Per user:** `get_records('quiz_attempts', ['quiz'=>$zid, 'userid'=>$uid],
   'id ASC')` — **no explicit field list** (a field list containing
   `sumgrades`+`timestart`+`timefinish` fails persistently on this build, even
   8/8 retries — see `moodle-php-cli-pitfalls` §15). Wrap in a retry loop
   (sleep 3, ~8 tries) regardless; a bare query failure must never be
   reported as "no attempt".
3. **Classify:** no row = "no attempt yet"; `preview=1` ignored;
   `timefinish>0` = submitted; `timestart>0` without finish = started, not
   finished.
4. **Scales differ between the series** — E-Quiz raw `sumgrades` is on the 23
   scale (gradebook 80); CE-Quiz raw is 4 (gradebook 20, e.g. CE-Quiz 4
   `grade_items.grademax`=20). Report marks from the gradebook
   (`grade_grades.finalgrade` via `grade_items` itemmodule='quiz' /
   iteminstance=quizid), never raw/80.
5. **Check whether the student's group slot is still open before saying
   "they can catch up".** The global window can run the whole week (CE-Quiz 4
   → Sun) while the student's lab-group override closed hours earlier (T03
   10:00–10:50). A non-attemper whose group slot has ended has effectively
   missed it — flag them as "the one to chase" and note that make-up means a
   user override or group-override adjustment (instructor decision). Same-day
   result: 2/5 had already submitted CE-Quiz 4 (17.33/20, 20/20); 2 still had
   their T02 slot next day; 1 (T03) had missed both quizzes of the week.

## Pitfalls (all cost real re-runs on 2026-09-28 — see `moodle-php-cli-pitfalls` §13)

- **Duplicate LTI user accounts:** same student can hold 2+ `mdl_user` rows
  (same name+email, both `auth=lti`, `deleted=0`) — a phantom with no enrolment /
  no attempts + the real enrolled one. `get_record('user',['email'=>…])` returns
  the lowest id = the phantom, a "ghost" that appears/disappears between queries.
  `SELECT id, auth, deleted FROM mdl_user WHERE email=?` before trusting a row;
  flag the duplicate for cleanup.
- **`component='core'` can silently 0-out the role lookup** (63 rows without the
  filter, 0 with it) → everyone misclassified as "staff". Drop it if empty.
- **MCP `query` subquery conditions can return 0 rows with no error** — re-verify
  with a flat literal `IN (…)` or the PHP bootstrap before reporting "no rows".
- **`$DB->prefix` is protected** — `$P = $DB->get_prefix();`.
- **`php -r` quoting** — single-quote the shell string, no single-quote literals in
  PHP; silent exit 255 + empty output = a quoting clash, not a DB error.
- **Threshold scale** — quiz B's `%` is `finalgrade / mdl_quiz.grade` (gradebook),
  never `sumgrades / grade`.

## Reference

- cs1302a_26a course id = 3. Quiz ids shift per semester — resolve by name.
  CE-Quiz N runs the week of Lab N; E-Quiz N runs one week earlier (see
  `moodle-cequiz-management`).
- Helpers group = id 89 in course 3 (verify). Lab IPs = `175.159.202.0/24`.
