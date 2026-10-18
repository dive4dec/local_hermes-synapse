---
name: moodle-equiz-student-status
description: "Produce the three student-status cohorts for a quiz in an LTI-enrolled course (e.g. <coursecode> / course <cid>): (A) submitted and scored <= threshold %, (B) enrolled but never submitted, (C) on the LTI group-sync roster but with no Moodle account. Use when the user asks who failed / did not attempt a quiz, or who is in the Canvas/LTI roster but not enrolled."
---

# Moodle quiz student-status cohorts

Answer three questions about one quiz in one course:
- **A. Failed**: enrolled + submitted + final mark <= threshold (default 30%).
- **B. Not attempted**: enrolled + no finished (non-preview) attempt.
- **C. Not enrolled**: present in the LTI group-sync roster but no Moodle user/enrolment.

Ready-made script: `scripts/cohorts.php` (see linked files). Usage:
```
php <skill_dir>/scripts/cohorts.php <courseid> "<quiz name>" [threshold_pct]
# example
cd <datadir>/.hermes && php <datadir>/.hermes/skills/moodle/moodle-equiz-student-status/scripts/cohorts.php 3 "E-Quiz 1" 30
```
If the script works, STOP here and present the three sections. Only read on to understand/repair it.

## Environment
- Moodle webroot: `<webroot>`. Bootstrap any CLI script with:
  ```php
  define('CLI_SCRIPT', true);
  define('MOODLE_INTERNAL', true);
  require('<webroot>/config.php');
  require_once('<webroot>/lib/setup.php');
  global $DB;
  ```
- Run as: `cd <datadir>/.hermes && php /tmp/script.php` (www-data).
- `<coursecode>` = course id **3**. LTI plugin is `ltigroups` → `mdl_ltigroups_roster`.
- Do NOT do this through the MCP `moodle_db` `query` tool — it truncates, silently drops data, and rejects keywords. PHP CLI scripts are reliable.

## The three traps (learned the hard way)
1. **`sumgrades` is on the QUESTION mark scale, not `mdl_quiz.grade`.** E-Quiz 1 (course <cid>): real question max = **22**, `quiz.grade` = 80. Computing `sumgrades / quiz.grade` understates every score (e.g. 8/80 = 10% when the truth is 8/22 = 36%). **Authoritative % = gradebook**: `mdl_grade_items` row with `itemmodule='quiz', iteminstance=<quizid>` → its `mdl_grade_grades.finalgrade` (already rescaled to `quiz.grade`). To cross-check the true question max, take any known-correct pair: `actualmax = raw_sumgrades / (finalgrade / quiz.grade)`.
2. **Flaky driver**: `get_records_sql` dies with a bare "Error reading from database" on nested subqueries and on some column combos (e.g. selecting `sumgrades` + `timefinish` without a `timefinish` predicate). Keep every query flat (one table or one simple join, no subqueries) and test each query in isolation if something new fails.
3. **`finalgrade` NULL ≠ not attempted.** A submitted student can have NULL/'' `finalgrade` (grade not yet computed — e.g. LTI grade push lagging). Classify as "submitted, grade pending" and say so; never count them as not-attempted. A genuine zero is the string `'0.00000'`.

## Procedure (what the script does)
1. **Resolve ids**: `mdl_quiz` by (course, name) → `quizid`; `mdl_grade_items` by (itemmodule='quiz', iteminstance=quizid) → grade item; `quiz.grade` = gradebook max.
2. **Enrolled active students** = intersection of:
   - `mdl_role_assignments` at the course context (`mdl_context` with contextlevel=50, instanceid=courseid) with the **student** role id, AND
   - `mdl_user_enrolments` (status=0) over active `mdl_enrol` instances (status=0) for the course.
3. **Attempts**: `mdl_quiz_attempts` where `quiz=quizid AND preview=0`; **submitted** = `timefinish > 0` (NULL/0 = abandoned mid-attempt → count as not submitted).
4. **Cohort A**: submitted + enrolled + `finalgrade / quiz.grade <= threshold`. List `finalgrade`/`quiz.grade` (and raw sumgrades for reference).
5. **Cohort B**: enrolled + no submitted attempt.
6. **Cohort C**: `mdl_ltigroups_roster` where `courseid=course AND (userid IS NULL OR userid = 0)` — `userid` gets filled on the student's first LTI launch (which auto-enrolls them). `assignments` is JSON like `{"Lec":"C01","Lab":"T03"}`.
7. **Exclusions for real-student counts**: membership in the `helpers` group, email contains `ltitest`, email `@example.com`. Show them tagged, not deleted.
8. **Enrich** with course groups (Lab / Lec / project) via `mdl_groups_members` → `mdl_groups` (courseid-scoped).
9. **Sanity check before presenting**: `submitted + not-attempted == enrolled` (modulo grade-pending note); spot-check 2–3 students' % against the gradebook UI; confirm the count of `'0.00000'` grade rows matches the count of 0%- scorers.

## Output conventions
- Print counts first, then the full lists (name | email | %/score | groups | tag).
- Say explicitly which source each number comes from (gradebook vs raw attempt).
- This is read-only — no `moosh -n cache-clear` needed (that's only after DB *writes*).

## Pitfalls / edge cases
- **Timezone trap:** pod PHP `date()` renders UTC+8 (Asia/Hong_Kong) while the system clock is UTC. Before saying a quiz is "still open" / "closed", compute `time()` vs `timeopen`/`timeclose` numerically and cross-check with `date -u`. Two date-related user corrections came from this.
- Quiz names with spaces need quotes on the CLI.
- A quiz may allow multiple attempts: the gradebook value is the aggregated (best) grade; raw best = max sumgrades over finished attempts.
- Preview attempts (preview=1) must always be excluded.
- If the roster row has a `userid` set but that user is not in the active-enrolment intersection, surface it manually (weird state, don't auto-bucket).
- Never present MCP `query` tool results for these cohorts — they are truncated (100 rows) and flaky.
