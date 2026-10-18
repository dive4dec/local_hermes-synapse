---
name: crossquiz-ai-divergence-audit
description: Identify students who may not be learning properly / misusing AI by comparing performance on IDENTICAL questions shared between a self-paced homework quiz (E-Quiz) and an in-class timed quiz (CE-Quiz) — per-question divergence, multi-round track record, code-transcription tells, and a two-filter screen (performance gap AND low precheck effort, BOTH required). Use when asked to "find students like TSO", to screen for AI-assisted homework, or when in-class results collapse vs homework on repeated questions.
---

# Cross-Quiz AI-Divergence Audit (homework vs in-class, same questions)

Sibling of the manual `quiz-ai-misuse-audit` skill (which audits ONE quiz's fast/high/low-check pattern). This one audits the **cross-quiz gap** on shared questions — the "TSO pattern".

## When to use
- "Identify students who are like TSO / potentially misusing AI / not learning properly."
- Requires two quizzes that share 1+ questions. In CS1302: E‑Quiz N = homework (open ~1 week, self‑paced), CE‑Quiz N = in‑class (45 min, SEB, one shot); pairs often reuse 1–2 code questions.
- Natural trigger: a round where homework is near‑perfect but in‑class collapses.

## Why it works
A student who genuinely understands a solution rebuilds it under time pressure. Near‑perfect homework + poor in‑class on the **identical** questions = the answer was not internalized (commonly AI‑generated homework). Sharpest variant: prior in‑class rounds were fine and only the latest round collapsed.

## Data model (this build — do not guess)
- Per‑question grade = **last step's fraction** in `mdl_question_attempt_steps` (max `sequencenumber`) × `qat.maxmark`. **`qat.maxfraction` is unreliable** (read 1.0 on a question that scored 0.7 — verified TSO u553).
- Student's actual submitted code = **`mdl_question_attempts.responsesummary`** (step_data `responsesummary` is empty on the final step — don't use it).
- Join: `qa.uniqueid = qat.questionusageid` (backtick `` `questionusageid` `` inside nested correlated subselects). Filter `qa.state IN ('finished','graded')`.
- Use raw mysqli / PHP bootstrap (moodle‑db‑access pattern); MCP read‑only replica is partial for question‑engine tables and blocks `timecreated`.
- Per‑quiz question list: `SELECT qat.questionid, MIN(qat.slot) slot, MAX(qat.maxmark) FROM mdl_question_attempts qat JOIN mdl_quiz_attempts qa ON qa.uniqueid=qat.questionusageid WHERE qa.quiz=<qid> GROUP BY qat.questionid` (exclude maxmark=0 "Information" slot).
- **E5 round traps (2026-10-13, cost ~8 diagnostic runs):**
  - **`mdl_question_attempt_steps` has NO `data` column** — the value column is **`fraction`** (nullable decimal) + `state`. Selecting `s.data` (even backticked) dies with a bare "Error reading from database" that looks like driver flakiness. For final-step fractions: use `state` when it is `gradedright`/`gradedwrong`, else `fraction`.
  - **Correlated subqueries die in this build** — `AND s.sequencenumber = (SELECT MAX(s2.sequencenumber) FROM {question_attempt_steps} s2 WHERE s2.questionattemptid = qat.id)` → bare DB error, even with `LIMIT 1` on the outside, and `WHERE id IN (SELECT MAX(id) …)` fails too. **Working pattern = derived-table join**: `JOIN (SELECT questionattemptid, MAX(sequencenumber) m FROM {question_attempt_steps} GROUP BY questionattemptid) x ON x.questionattemptid = qat.id JOIN {question_attempt_steps} s ON s.questionattemptid = qat.id AND s.sequencenumber = x.m`.
  - **`get_records_sql` first-column keying corrupts per-user maps** (see `moodle-php-cli-pitfalls` §3): first run of this audit keyed rows by `userid` and silently collapsed the whole cohort to uniform 100/50/1 values. Always `SELECT s.id AS rid, …` first when grouping in PHP.
  - **A question may exist as TWO questionid versions in one quiz** (E‑Quiz 5 carried q3789 AND q12796, both "Generate n characters", both slot 15 — a mid-window replacement; CE‑Quiz 5 had only q12796). Per-user shared‑Q fraction must take **MAX across versions**. Detect by listing each quiz's questionid set and looking for same-name/same-slot duplicates.
  - **Role-join gotcha when building the student set:** `SELECT ra.userid FROM {role_assignments} ra JOIN {role} r ON r.id=ra.roleid WHERE r.shortname='teacher'` works, but adding `AND ra.courseid=3` → bare DB error (that predicate on the table is blocked). The plain query returns all teachers site-wide; intersect with the course enrolment set in PHP (`{user_enrolments}` + `{enrol}` join works fine) instead.
  - **A clean zero-flag round is a valid result.** E5 (65) vs CE5 (66): shared Qs = q3784 (leaky relu) + q12796 (generate n chars); 192 real students finished both; **197/197 right on each shared Q in-class → zero gap candidates → report "no flags"** with the per-question right/wrong counts as evidence. Do not force a list; the honest answer is none. (113 students still showed ≤1.5 prechecks/q + 0 wrong finals on E5 — noted as low-effort but NOT flagged, per the two-filter rule.)
- **SQL reserved words (MariaDB, cost 3 failed queries in the 2026-10-06 run)**: backtick `` `questionusageid` `` and never alias a column `right` (use `rgts`); `usage` is reserved too. `mdl_question_attempts` times: use `mdl_quiz_attempts.timestart/timefinish` (there is no `timecreated` on the attempt row; step-level time is `mdl_question_attempt_steps.timecreated`).

## Procedure
1. **Shared questions**: list both quizzes' question ids, intersect. Record each question's maxmark in each quiz (homework questions often carry 2× marks).
2. **Per‑user shared‑question fractions** in both quizzes (final‑step fraction per user per questionid).
3. **Gap** = (shared‑Qs % homework) − (shared‑Qs % in‑class). Tier:
   - **T1** failed BOTH shared Qs in‑class (full marks on both in homework).
   - **T2** failed one shared Q in‑class, full in homework, solved the other in‑class.
   - **T3** partial/borderline on one shared Q.
4. **Multi‑round track record** (strongest signal): quiz ids per round are contiguous pairs (e.g. 57/58 = E1/CE1 … 63/64 = E4/CE4 in course 3); total % = `sumgrades / Σmaxmark`. The tell = **homework stable‑high while CE collapses only in the final round** (worked example: 100/95/98 → 25).
5. **Code‑transcription tell** (the discriminator): pull `responsesummary` on the failed in‑class Q from BOTH quizzes. TSO signature = in‑class code is a **corrupted transcription of the student's own homework** — same variable names/structure but one token off (wrong operand `divisor%2` vs `num%divisor`, `is_prime == False` compare instead of assign, mis‑indented def), or truncated to blank / `# YOUR CODE HERE` stub. Homework that is clean, complete, commented, bug‑free = AI signature. Genuine independent failure produces *different* code, not a near‑copy with one typo.
6. **In‑class effort context**: step count, best precheck fraction, and whether the final submission was blank after N edits (gave up) vs blank immediately (possibly client freeze).
7. **TWO-FILTER screen — both are required (user correction, 2026-10-06).** The performance gap (step 3) only *selects candidates*; the precheck-effort filter is the *additional requirement*. Report only students who fail BOTH. **Never** flag by prechecks alone (false alarms on strong consistent first-try coders who show no in-class divergence) and **never** by gap alone (over-flags students who genuinely iterated on homework — e.g. KWAN u624: biggest CE collapse 100/95/98→25 but 43 prechecks / 2.7 per Q → CLEARED).
   On the homework (E‑Quiz) CodeRunner questions, per user:
   - `prechecks/q` = (count of `todo` steps carrying `mdl_question_attempt_step_data.name='-precheck'`) ÷ number of graded questions. Cohort median ~19 total over 16 Qs; flag at ≤ ~16 total (≈≤1.0/Q), borderline up to ~24.
   - `instant` = questions that reached `gradedright` after ≤2 prechecks.
   - `wrong` = count of `gradedwrong` steps. A genuinely iterating student almost always trips a failing test — **0 wrong checks across all questions** is a strong pasted/generated‑answer signal.
   - **Final list = gap candidates ∩ low prechecks.** Worked result (CE4 vs E4): u522 CHENG, u677 KWOK, u553 TSO, u731 YU, u545 HE, u588 BEKMUKHANBETOV, u557 FENG, u662 CAI; borderline u578 OU (23 prechecks), u653 TAM (17); excluded despite gap: KWAN 43, QIN 74, WANG 35, YEUNG 29, LIN 29, KWOK u669 28.
   - **Persistence across rounds** multiplies the signal: run the same metric on the earlier E‑Quizzes (contiguous quiz ids, e.g. 57/59/61/63). Low effort in every round (0.3–0.5 prechecks/q) is a trait, not a one‑off week.
   - **Calibrate before finalizing**: always run the metric on the anchors the user names (one known‑genuine, one known‑suspicious) and verify it separates them in the right direction before reporting.

## Caveats (do not over-attribute)
- **Client‑freeze confound**: if the in‑class quiz had documented freeze/autosave issues (check `moodle-coderunner-jobe-diagnosis` + its case file first), *blank/truncated* in‑class submissions are partially machine‑fault. The clearest not‑learning evidence is **present‑but‑wrong** code, not absence. State the confound in the report.
- One shared‑question pair is thin evidence — the track record + code tell carry the weight.
- Output = a **suspicion list for investigation**, never an accusation. Recommended decisive step: short one‑on‑one to rebuild the solution from scratch. House style for any follow‑up email: factual, no accusation without decisive evidence, individualized (see user profile).
- Exclude non‑student role users (teachers sit outside time limits — see moodle‑mcp‑db-query).

## Output format (Matrix: no tables)
Per student: `Name (uNNN) — homework total% / in‑class total% — per shared‑Q split (hw → in) — track record R1..Rn — prechecks/q + instant rate + wrong‑checks (all E‑Quiz rounds) — code tell — tier`. Save full report with code excerpts to `.hermes/cron/output/<quiz>_ai_misuse_cohort_report.md`.

## Reference files
- `references/ce4-eq4-2026-10-06.md` — worked example: CE‑Quiz 4 (64) vs E‑Quiz 4 (63), 192 students, final TWO‑FILTER list (8 suspicious + borderline + excluded-with-gap), code excerpts, calibration anchors (KWAN cleared / YU flagged).
- `references/e5-ce5-2026-10-13.md` — CE‑Quiz 5 (66) vs E‑Quiz 5 (65): CLEAN round (0 flags), per-question right/wrong counts, duplicate-question-version handling, the 113 low-effort-not-flagged note, and the build traps of that run.
