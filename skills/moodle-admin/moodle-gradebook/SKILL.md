---
name: moodle-gradebook
description: "Moodle gradebook work on <moodle-host> (Moodle 5.x): inspect grade structure, weight semantics (aggregationcoef2), version-specific aggregation constants, add manual grade items, grade per group via member propagation, and per-question quiz manual override (mark + comment) via the question engine."
---

# Moodle Gradebook (Moodle 5.x, <moodle-host>)

## Triggers

- "Set X% of the grade to <component>" / reweight items / add a manual grade item (e.g. a project grade)
- Entering grades manually, especially **per group**
- "Mark all of a student's questions 0 / override a quiz grade with an explanation comment" — per-question manual override
- "Why doesn't the total add up" / weight sums / hidden items
- "Score distribution / histogram of <quiz>" — who completed it, what marks, on what scale
- Inspecting a course's gradebook structure
- Configuring quiz completion "Receiving a grade" / "Receiving a passing grade" (+ its pass mark)

## Data model (verified on this site)

`mdl_grade_items` — one row per gradeable column:
- `itemtype`: `course` | `mod` | `manual` | `category` (plus outcome/import/calculated)
- Course item: query `['courseid' => $cid, 'itemtype' => 'course']` — its `iteminstance` is **NOT the course id** (observed: course <cid>'s course item has `iteminstance=2`)
- **Weight is `aggregationcoef2`** as a fraction (0.05 = 5%). There is **no `weight` column**. `aggregationcoef` is used by other aggregation types.
- `gradetype`: 1 = value. `grademax` / `grademin`.
- `hidden`: 0 = visible, 1 = hidden, >1 = timestamp — item **visible after** that time (hide-until). Verified 2026-08-27: E/CE-Quiz items carry their quiz CLOSE timestamps (e.g. Demo CE-Quiz hidden=1789315199 = 2026-09-13 23:59 → hidden until the quiz closed; all now visible). Test with `(int)$hidden > 0`.
- `categoryid = NULL` = top level.

`mdl_grade_grades` — unique `(userid, itemid)`; `rawgrade`, `finalgrade`, `aggregationweight`, `overridden`, `excluded`. **No group column** — a per-group grade must be written to each member's row.

`mdl_grade_categories` — `aggregation` is an int constant. **The mapping is version-specific: read `lib/grade/constants.php`** (this site: `13 = GRADE_AGGREGATE_SUM` "Natural"). Old core numbering (SUM=5) does NOT apply.

`lib/grades/` does not exist in this version — the code lives in `lib/grade/` (`grade_item.php`, `grade_grade.php`, `grade_category.php`, `constants.php`).

## Inspecting a course gradebook (CLI PHP bootstrap, see `moodle-db-access`)

1. Course item: `$DB->get_record('grade_items', ['courseid' => $cid, 'itemtype' => 'course'])` — `grademax` hints at the display scale (100 = percentage, 1025 = raw Natural/SUM total; confirm with the user). A **Natural/SUM** course item's `grademax` is the SUM of its counted children's grademaxes (course <cid> = 100+20+5+9×80+9×20 = **1025**), so the total is shown as raw points unless the item's `display` column is set to a percentage type.
2. Items: `get_records('grade_items', ['courseid' => $cid, 'itemtype' => 'mod'], 'sortorder')` plus `'itemtype' => 'manual'`.
3. Sum `aggregationcoef2` over visible items; the sum must equal 1.0 (or the intended drift if retake items carry weights — investigate before recommending). Course-3 verified state 2026-08-27: Exam 0.5, Midterm 0.2, 9×E-Quiz 0.02222 (=0.2), 9×CE-Quiz 0.00556 (=0.05), Project 0.05 → **sums to exactly 1.0**; see `references/course-3-gradebook.md`.
4. Sample a graded student: pull `grade_grades` for those itemids, sum `finalgrade`, compare with the course-item row.
5. Group data: `groups` / `groups_members` / `groupings` / `groupings_groups` (both words plural in the join table).

## Adding a manual item (e.g. "Project (5%)")

1. **Confirm the scale with the user first** (is the total shown /100 or as raw points?) and whether to rebalance existing weights or let the sum drift. Never guess — changing weights changes every student's final grade. List exact changes and wait for confirmation (user's standing rule).
2. Prefer the gradebook UI ("Add a new item"). If doing it programmatically, mirror `grade/classes/form/add_item.php`:
```php
$item = new grade_item(['courseid' => $cid, 'itemtype' => 'manual', 'itemname' => 'Project (5%)'], false);
$item->gradetype = 1;            // GRADE_TYPE_VALUE
$item->grademax = 5;             // points, when the total is /100
$item->aggregationcoef2 = 0.05;  // 5%
$item->insert();
// optionally move into a category afterwards
```
3. Set `needsupdate = 1` on the course item (and containing category) so totals recalculate; `moosh -n cache-clear`.
4. Verify: item row exists with the right coef; re-sum weights; recompute a sample student's total if any student is graded.

## Show the total as a percentage (Natural/SUM courses)

When the user says "normalize the total to a percentage, but don't change the individual
activity grades or the weightings": change **only the course item's `display` column to
`GRADE_DISPLAY_TYPE_PERCENTAGE` (2)** (`$DB->set_field('grade_items','display',2,['id'=>$courseItemId])`,
then `needsupdate=1` + `moosh -n cache-clear`). No `rawgrade`/`finalgrade`, `aggregationcoef2`,
or item `grademax` changes — students see `80%` instead of `820 / 1025`. Full mechanics,
the correct recalc API, and a backup→test→restore recipe on the LTI test users:
`references/grade-aggregation-sum.md`.

## Missing gradebook column — `gradetype = 0` (no value type)

Symptom: an activity (quiz) shows in the course view but has **no column** in the gradebook.
Diagnosis (read-only SQL; `module` is the numeric FK — quiz = 17):

```sql
-- the item
SELECT id, itemname, itemmodule, iteminstance, gradetype, grademax, hidden, aggregationcoef2
FROM mdl_grade_items WHERE itemmodule='quiz' AND iteminstance = <quizid>;
-- the quiz's own max grade (Moodle 5.x: the column is `grade`, NOT `maxgrade`)
SELECT id, name, course, grade FROM mdl_quiz WHERE id = <quizid>;
-- attempts (data-risk check before touching anything)
SELECT COUNT(*) FROM mdl_quiz_attempts WHERE quiz = <quizid>;
```

**Root cause found in the wild (2026-08-27, Mock Exam 25B in <coursecode>, quiz 76):** a quiz
created/saved with **max grade 0** syncs its grade item to `gradetype = 0` (`GRADE_TYPE_NONE`);
the item keeps a stale `grademax` (e.g. 100) and may carry leftover `aggregationcoef2` /
`hidden` from a prior config. Every normal quiz item is `gradetype = 1`.

Fix: correct the **quiz's max grade first** (edit the quiz via the standard quiz edit form or a
PHP `$quiz->update()` through the bootstrap) — that save runs Moodle's own grade-item sync and
restores `gradetype = 1` / `grademax` automatically. Then clean up the item if the sync left
anomalies (compare against a healthy sibling item: `hidden`, `aggregationcoef2`). Never just
`UPDATE grade_items SET gradetype=1` alone — the quiz's `grade=0` would re-break the item on
the next sync. Finish with `moosh -n cache-clear` and verify the column in the grade report.

**WHY THE COLUMN STAYS HIDDEN EVEN AFTER THE MAX-GRADE FIX (verified 2026-08-28, quiz 76):**
`quiz_grade_item_update()` (mod/quiz/lib.php) re-derives `hidden` from the quiz's review-display
flags on EVERY save. If marks are only shown AFTER_CLOSE (`reviewmarks`/`reviewmaxmarks`
bit = 0x10) and the quiz has no `timeclose`, it forces `hidden=1` permanently. Symptoms the
user sees: "I fixed the max grade but nothing shows / total of marks remains 0". Fix the flags
to include the LATER_WHILE_OPEN bit (0x100) — value 4352 (IMMEDIATELY_AFTER+LATER_WHILE_OPEN)
matches healthy sibling quizzes — then re-run `quiz_grade_item_update($quiz)` (attach
`$quiz->visible` from the CM so the cm-hidden branch doesn't re-hide it) and set
`grade_items.hidden=0`.
Second trap: `mdl_quiz.sumgrades` is only recomputed by the question-editing screen
(`grade_calculator::recompute_quiz_sumgrades()`); it can sit at 0 while `quiz_slots` sum to the
real total, which is what the quiz "Total marks" field shows. Recompute via
`\mod_quiz\quiz_settings::create($quizid)->get_grade_calculator()->recompute_quiz_sumgrades()`.
Final step: `grade_regrade_final_grades($courseid)` (the same call the Recompute button uses —
`grade_update()` has a 9-arg signature, don't guess it) to clear `needsupdate`, then
`moosh -n cache-clear` and verify the item row matches a known-visible sibling exactly
(hidden/gradetype/categoryid/grademax).

## Quiz "Receiving a passing grade" completion (storage model, verified 2026-08-28)

"Receiving a grade → Receiving a passing grade" on a quiz is spread over **four settings in two
tables** — all must be set, and the pass *mark* is NOT stored on the activity:

1. **Tracking = automatic** — `course_modules.completion = 2` (0=off, 1=manual).
2. **"Receiving a grade"** — `course_modules.completiongradeitemnumber = 0` (NULL = off; `0`
   selects the default grade item, itemnumber 0). The form's `completionusegrade` checkbox is
   persisted as exactly this column (`completion/classes/manager.php`:
   `completiongradeitemnumber = usegrade ? 0 : null`).
3. **"Receiving a passing grade"** sub-option — `course_modules.completionpassgrade = 1`
   (tinyint(1) FLAG only; 0 = any grade). It does not store a score.
4. **The pass mark** — `grade_items.gradepass` (e.g. 30 of 100, 6 of 20). The engine
   (`internal_get_grade_state()` in `lib/completionlib.php`) compares the student's
   `finalgrade` (else `rawgrade`) to it. With `gradepass = 0` any recorded grade counts as
   complete and no pass/fail split happens — the classic "invalid completion setting" symptom.

The quiz page shows "Grade to pass: X out of Y" to students whenever `gradepass != 0`
(`mod/quiz/view.php`). Bulk recipe, real-engine verification script, pitfalls, and the
2026-08-28 worked example (13 Mock quizzes in <coursecode>):
`references/quiz-completion-passgrade.md`.

## Grading per group (one score per group)

The gradebook has no native group-grade row; propagate the group score to each member:

1. Build group → member userids from `groups_members`. **Empty groups = no registrations yet** (a `choicegroup` registration activity must run first).
2. For each group, upsert a `grade_grades` row per member: `rawgrade` = group score (clamp to 0..`grademax`), `rawgrademax`/`rawgrademin` matching the item, `usermodified` = grader, `timecreated`/`timemodified` = now.
3. Set `needsupdate=1` on the item + course item; `moosh -n cache-clear`.
4. Verify: rows per group = member count; spot-check one member's `finalgrade`; confirm the course total moved by score × weight.

## Per-question quiz manual override (mark + comment) — the proper mechanism

When a student's quiz is zeroed for absence-failed-to-explain, the approved notice email
template (factual, final decision — **no explanation window, no open-hour invite, no
evidence offer, no makeup**; policy tightened 2026-10-07) is
`templates/zero-grade-notice-absent-explanation.md` — draft from it, get user confirmation,
then send.

When the user asks to override a student's quiz marks **per question with an
explanation** (e.g. "mark every question 0 because they couldn't explain their
answers"), the proper mechanism on this build is the **question-engine manual
grade**, exactly what the quiz "Edit comment or grade" popup
(`mod/quiz/comment.php` → `process_submitted_actions()`) does. Do NOT hand-edit
`question_attempts.minfraction`/`sumgrades` — that desyncs the gradebook and the
question-step audit trail, and the comment has nowhere to live.

Key facts (verified 2026-09-22, E-Quiz 2 zeroing for one student):
- **`mdl_quiz_grades` is the calculator's CACHED per-user best grade** (one row
  per quiz/user, auto-written by `grade_calculator::recompute_final_grade()`),
  NOT a manual-override store. It has **no `usercomment` column**. The
  per-question manual mark + comment live in **question-attempt STEP data**:
  new step rows in `mdl_question_attempt_steps` + `mdl_question_attempt_step_data`
  with behaviour vars `-mark`, `-maxmark`, `-comment`, `-commentformat`.
- **`mdl_question_attempts` has NO `manualmark`/`usercomment` columns** on this
  build (unlike stock Moodle) — do not query them. Read manual state via the API:
  `question_attempt::get_current_manual_mark()`, `has_manual_comment()`,
  `get_manual_comment()` (returns `[comment, format, step]`).
- Earned mark per question = `minfraction × maxmark`; a manual mark step
  **replaces** the automatic fraction (the fraction is read from the LAST step).

API path (works in CLI; all verified live this session):
```php
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('<webroot>/config.php'); require_once('<webroot>/lib/setup.php');
require_once('<webroot>/mod/quiz/locallib.php');
require_once('<webroot>/mod/quiz/classes/quiz_attempt.php');
$attemptobj = \mod_quiz\quiz_attempt::create($attemptid);   // attempt ID, not userid
$ref = new ReflectionObject($attemptobj);
$p = $ref->getProperty('quba'); $p->setAccessible(true);
$quba = $p->getValue($attemptobj);   // get_question_usage() throws in CLI (unit-test-guarded)
foreach ($attemptobj->get_slots('all') as $slot) {
    $qa = $attemptobj->get_question_attempt($slot);
    if ($DB->get_field('question','qtype',['id'=>$qa->get_question_id()]) === 'description') continue; // 0-mark Information page
    $qa->manual_grade($COMMENT, 0, FORMAT_MOODLE, time(), $graderUserId);
}
question_engine::save_questions_usage_by_activity($quba);  // MUST save before recompute
// Build delta (2026-10-06): the manual path does NOT update sumgrades (it only sets
// per-question minfraction=0) and recompute reads sumgrades FROM THE DB — refresh it
// from the engine total first, or the gradebook stays at FULL MARKS while every
// question shows 0:
$attemptobj->get_attempt()->sumgrades = $quba->get_total_mark();
$DB->update_record('quiz_attempts', $attemptobj->get_attempt());
$rec = $ref->getMethod('recompute_final_grade'); $rec->setAccessible(true); $rec->invoke($attemptobj); // protected in this build
```
This yields `sumgrades=0`, `quiz_grades.grade=0`, `grade_grades.rawgrade=0` AND
`finalgrade=0` (raw→gradebook scale, e.g. /80), with the comment visible on every
question in the attempt review/grading report. Also fire
`\mod_quiz\event\question_manually_graded::create([...])->trigger()` per slot
(the popup fires it; harmless to skip but keep the audit trail).
Finish (verified 2026-10-06/07): `require_once('<webroot>/lib/gradelib.php');
grade_regrade_final_grades($courseid);` (undefined-function error without the require)
to refresh course totals, then `moosh -n cache-clear`, and re-verify all four fields
(sumgrades / quiz_grades.grade / rawgrade / finalgrade) through the moodle_db MCP —
an independent connection, not the script's own reads. Full build delta:
`references/quiz-manual-grade-override.md`.

Pitfalls hit this session (full recipe + pre-state backup format:
`references/quiz-manual-grade-override.md`):
- `get_grade()`/`get_id()` don't exist here → use `get_mark()` / `get_database_id()`.
- `question_definition` objects expose no `get_name()`/`get_qtype()` (description
  qtype has neither) → join `mdl_question` by `questionid` for qtype/name.
- Delegated transactions **work** around the engine flow when the transaction
  is always closed (`allow_commit()` on the apply path, `rollback()` on the
  dry-run path) — verified 2026-09-24 with both paths, incl. a committed
  zero-out of 16 slots. The earlier "active database transaction detected
  during request shutdown" was an *unclosed* transaction at script exit, not
  an engine incompatibility. Preferred shape: one script with a `--commit`
  flag; default = apply + verify + rollback.
- **Verify the write through a SECONDARY channel before trusting it:** a
  wrong FK join (`question_attempt_step_data.attemptstepid` →
  `question_attempt_steps.id`, NOT `question_attempts.id`) reads 0 manual
  steps even after a successful commit, and acting on that false negative
  (a "restore") can leave the grade fields and the persisted manual marks
  DESYNCED. Re-check per-step data via the correct 3-table join through the
  `moodle_db` MCP tool (separate connection, real SQL error text) before
  reverting anything; a partial revert (grades only, steps untouched) is how
  total and per-question marks diverge. Full trap + working query:
  `references/quiz-manual-grade-override.md`.
- `process_submitted_actions()` in CLI needs the exact form POST (per-slot field
  prefix `q{usageid}:{slot}_` with `:sequencecheck` from
  `get_sequence_check_count()`, `-mark`, `-maxmark`, `:minfraction`,
  `:maxfraction`, `-comment`, `-commentformat`) — the direct `manual_grade()`
  loop above is simpler and equivalent; prefer it.
- DB columns come back as STRINGS — `$at->userid !== $userid` (int) is a
  **false** mismatch; compare with `!=`.
- Always back up `question_attempts` (all columns), its
  `question_attempt_step_data`, `quiz_attempts`, `grade_grades`, and
  `quiz_grades` rows BEFORE writing; run a dry-run pass and restore from backup
  to confirm it's a no-op before committing.

## Score distribution of a quiz's completed attempts

"Give me the score distribution of students who have completed <quiz>": report the gradebook
(rescaled) distribution, reconciled against the quiz's `sumgrades`. Two facts keep this honest:

- **`mdl_quiz_attempts.sumgrades` is on the QUESTION scale** (the sum of `mdl_quiz_slots.maxmark`),
  NOT the gradebook scale. For the CE-Quizzes that is 4.0 (4 graded Code Runner questions × 1 mark;
  slot 1 is a 0-mark description), rescaled to **20/20** in the gradebook (×5). Report both or
  rescale by `grademax / question_max`.
- **Finished ≠ graded.** Teachers and test accounts *finish* attempts but their `mdl_grade_grades`
  row is `aggregationstatus='novalue'` with `finalgrade NULL`. So `COUNT(state='finished')`
  overcounts the graded-student population. Drive the *student* distribution from the gradebook
  (`mdl_grade_grades ... AND finalgrade IS NOT NULL`), then reconcile to the quiz by state.
  (CE-Quiz 1, quiz 58, itemid 60: 203 finished ↔ 201 graded students; the 2 extras were teachers.)

Find the scales + the gradebook item, then bucket both scales:

```sql
SELECT SUM(maxmark) AS question_max FROM mdl_quiz_slots WHERE quizid = <quizid>;
SELECT id, itemnumber, itemname, grademax, multfactor, plusfactor
FROM mdl_grade_items
WHERE courseid = <cid> AND itemmodule='quiz' AND iteminstance = <quizid>;

-- question scale: everyone who finished (students + teachers)
SELECT ROUND(sumgrades,2) AS score_qs, COUNT(*) AS n
FROM mdl_quiz_attempts WHERE quiz=<quizid> AND state='finished'
GROUP BY ROUND(sumgrades,2) ORDER BY score_qs;

-- gradebook scale: only graded students (the one to report)
SELECT ROUND(rawgrade,2) AS score_gb, COUNT(*) AS n
FROM mdl_grade_grades WHERE itemid=<itemid> AND finalgrade IS NOT NULL
GROUP BY ROUND(rawgrade,2) ORDER BY score_gb;
```

To name *who* lost marks and *where*, take users with `rawgrade < grademax` and drill per-question
via `moodle-quiz-attempt-inspection` §6 (final-step state / fraction). Cross-check counts: graded
students should equal finished students minus the ungraded teachers. When they don't match, do NOT
assume the grade row is missing — the row usually **exists with `finalgrade NULL`** (`aggregationstatus='novalue'`);
a `LEFT JOIN ... WHERE gg.id IS NULL` anti-join returns nothing in that case (2026-09-17: CE-Quiz 1's
2 ungraded users each had a row). Reconcile with `JOIN ... AND gg.finalgrade IS NULL`.

### Binned distribution (N equal score bands / intervals)

The user asks for "score distribution ... divided into N score bands/intervals" (asked with
N=4 for CE-Quiz 1 and N=5 for E-Quiz 1/2 on 2026-09-17). Bin on the QUESTION scale (raw marks
earned) and show the gradebook-equivalent range beside each band:

- Band width = `question_max / N`; last band closed at the top.
- `question_max` from `mdl_quiz_slots` (per-quiz, robust): `SELECT SUM(maxmark) FROM mdl_quiz_slots WHERE quizid = <quizid>;`
  (Equivalently sum `maxmark` over one finished attempt's `mdl_question_attempts`; both agreed on
  2026-09-17: CE-Quiz 1 = 4.0, E-Quiz 1 = 22, E-Quiz 2 = 23. Note `mdl_quiz_slots` has NO
  `questionid` column — slot→question resolution goes through `mdl_question_attempts`.)
- Filter to STUDENTS only — teachers also finish attempts (E-Quiz 1 had a teacher at 20.5/22 that
  would have landed in the top band). Verified student filter (contextlevel 50 = course):

```sql
SELECT band, COUNT(*) AS n FROM (
  SELECT CASE WHEN sumgrades < <max/N> THEN 'A: 0 - <...>'
              WHEN sumgrades < <2*max/N> THEN 'B: ...'
              ELSE 'E: ...' END AS band
  FROM mdl_quiz_attempts qa
  JOIN mdl_user u ON u.id = qa.userid
  JOIN mdl_role_assignments ra ON ra.userid = u.id
       AND ra.contextid = (SELECT id FROM mdl_context WHERE contextlevel = 50 AND instanceid = <cid>)
  JOIN mdl_role r ON r.id = ra.roleid AND r.shortname = 'student'
  WHERE qa.quiz = <quizid> AND qa.state = 'finished'
) t GROUP BY band ORDER BY band;
```

- Cross-check: band sum == finished student attempts == gradebook rows with `finalgrade IS NOT
  NULL` for that item (all three matched on 2026-09-17: CE-Quiz 1 = 201, E-Quiz 2 = 96, E-Quiz 1 = 186).
- These queries run as-is through the `moodle_db` MCP (param name `query`, ≤100 rows; aggregates
  fit comfortably) — just drop PHP `$vars`. Avoid `deleted`/`timecreated` columns in the SQL
  (MCP keyword filter rejects them — "CREATE"/"DELETE" substrings).
- For a student listing, skip the `groups_members` join unless a group column is requested — it
  fans rows out × groups per user (see Pitfalls).
- A still-open quiz shifts the numbers — state finished/in-progress counts and that it is a
  snapshot; a closed quiz with no grace period is final. Report spread (min/max) alongside and
  name the low-band students — they are few, and names + a per-question drill beat a giant table.

## Pitfalls

- **Groups join fans rows out.** `mdl_groups_members` is one row per (user,group). Joining
  `groups_members → groups` to enrich a per-user query duplicates any user in >1 group, so counts
  and distributions through that join double-count. Skip the join when counting, or `DISTINCT`
  on `userid`. (Observed: a teacher in 2 groups appeared twice in a finished-attempt listing.)
- **`state='finished'` is NOT the graded population.** Teachers/test accounts finish but stay
  `novalue` in the gradebook — see the score-distribution section above.
- Wrong column name **or table name** in `get_records`/`get_columns` → bare `!!! Error reading from database !!!` with no hint (no `weight` on `grade_items`; no `sortorder`/`idnumber`/`letterbox` on `grade_categories`; `get_columns('grade_item')` with the singular table name fails the same way — the table is **plural**: `grade_items`). Schema fallback: fetch one row and print `array_keys((array)$row)` — authoritative over `lib/db/install.xml`, which may lag the live schema. Full verified column lists (grade_items, grade_categories, grade_settings, choicegroup_options): `references/grade-items-schema.md`.
- Aggregation constants differ between Moodle versions — always read `lib/grade/constants.php`; never hardcode from memory.
- **Quiz items' `maxgrade` can be NULL on this site** (verified 2026-09-14: all 40 course-3 quiz items are `maxgrade = NULL`; the effective max is `mdl_quiz.grade`). Never compute a threshold or ratio from a quiz item's `maxgrade` without a NULL check — `threshold = 0.3 × maxgrade` with NULL silently becomes 0 and a "≤30%" query returns an empty set (false all-clear).
- Hidden items can inflate the weight sum (25B mock retakes in 26a) — filter `(int)$hidden > 0` when reporting "active" weights.
- `get_records(..., 'DISTINCT col')` works for distinct probing.
- Do NOT rescale existing items' weights to "make room" for a new one without explicit user confirmation.
- Course-specific snapshot: see `references/course-3-gradebook.md`.
