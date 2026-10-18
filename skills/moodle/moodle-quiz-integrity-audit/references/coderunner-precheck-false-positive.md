# Case study: CodeRunner Precheck false positive (2026-09-17, E-Quiz 1)

The audit that flagged a real working student. Keep this as the calibration for
"am I counting the right verification signal?"

## What happened
An audit of E-Quiz 1 (quiz 57, <coursecode>) counted self-verification as
`state='complete'` steps only (the adaptive-behaviour state set by an MC "Check").
a student (attempt 15707) came out as "3 checks, 58%, no verification on
essentially all code questions" and landed in the suspicion list. The instructor
checked the quiz review page and objected: the student had prechecked a lot.

## Root cause (verified in source + DB)
- Quiz composition: slots 2–11 = `multichoice` (Check button → `complete` state),
  slots 12–17 = `coderunner` (Precheck button → **no new step state**).
- `question/behaviour/adaptive_adapted_for_coderunner/behaviour.php`:
  `process_action()` routes a precheck button press into
  `process_submit($pendingstep, PRECHECK)` — the same submit path, flagged with
  the behaviour var `precheck`.
- This Moodle version persists step behaviour data in
  `mdl_question_attempt_step_data` (`attemptstepid, name, value`). The flag is
  `name='-precheck'` (there is also a running counter `-_numprechecks` and
  `_testoutcome` caching CodeRunner test results). The step's `state` column
  itself can be `todo` (CodeRunner accepts the response) or `complete`.
- Attempt 15707 raw data: state histogram
  `{todo:127, complete:3, finished:1, gradedright:7, gradedpartial:8, gradedwrong:1}`
  but **96 `-precheck` rows** — per-slot precheck counts on the code slots:
  s12=2, s13=12, s14=23, s15=4, s16=11, s17=44. The "3 checks" were 3 MC Checks;
  the 96 Prechecks were invisible to the metric.

## Corrected metric
Type-aware verification per question:
```sql
-- Checks (MC/standard): steps with state 'complete'
SELECT questionattemptid, COUNT(*) FROM mdl_question_attempt_steps
WHERE state='complete' AND questionattemptid IN (...) GROUP BY questionattemptid;

-- Prechecks (CodeRunner): steps flagged '-precheck' in step_data
SELECT qast.questionattemptid, COUNT(*) n
FROM mdl_question_attempt_step_data qsd
JOIN mdl_question_attempt_steps qast ON qast.id = qsd.attemptstepid
WHERE qsd.name = '-precheck' AND qast.questionattemptid IN (...)
GROUP BY qast.questionattemptid;
```
(Join with a `LEFT JOIN ... AND qsd.name='-precheck'` + CASE when you need both
in one pass — note a LEFT JOIN multiplies rows when a step has multiple
step_data rows; count distinct stepids or the flag column, not raw rows.)

After the fix the same student ranked 183/186 (bottom) — correctly unflagged. The
true survivors of E-Quiz 1's "few verifications" signal were students with
**0 MC-Checks** (e.g. 10 MC + 0 checks + 12–15 code Prechecks, 91–100%,
12–53 min) — the anomaly moved to the MC side, where skipping Check is
harder to explain.

## Takeaways
1. Never assume "verification" = one step state. Check the question **type per slot**
   (`mdl_question_attempts` JOIN `mdl_question.qtype`) and the behaviour
   (`mdl_question_usages.preferredbehaviour`) before counting anything.
2. When the user disputes a flag with a specific attempt id, go straight to the
   raw per-slot step trace of THAT attempt — it's the fastest way to find what
   the metric missed (and it's the trust-repair move).
3. `php -l` in this pod is unreliable (reports parse errors on valid one-liners);
   verify ad-hoc audit scripts by running them read-only.
4. Raw `mysqli` is unavailable from the pod and the `moodle_db` MCP tool is
   read-only SELECT/SHOW/DESCRIBE ≤100 rows — chunked `IN(...)` extraction
   (100 ids/chunk) via PHP bootstrap remains the workhorse for full-cohort pulls.
