---
name: quiz-ai-misuse-audit
description: Audit a Moodle quiz for AI misuse via per-question step-trace analysis (fast + high score + near-zero self-checks), answer-text similarity, and IP cross-reference. Use when asked to find students who "completed quickly, mostly correct, with very few prechecks/checks" or any quiz-integrity screening.
---

# Quiz AI-misuse audit

## When to use
User wants a list of students potentially misusing AI on a quiz — symptom: fast completion, high score, very few Check/Precheck interactions.

## Step 0 — resolve the CORRECT quiz (do not skip!)
Courses often have several quizzes with similar names (numbered variants, E-/CE-/quiz1, etc.). ALWAYS list every quiz in the course and confirm identity by **name AND question count AND max mark AND time limit** before auditing — never assume.
```sql
SELECT q.id, q.name, q.grade, q.sumgrades, q.timelimit, q.preferredbehaviour, cm.id
FROM mdl_quiz q JOIN mdl_course_modules cm ON cm.instance=q.id AND cm.module=(SELECT id FROM mdl_modules WHERE name='quiz')
WHERE q.course=<cid> ORDER BY q.id
```
Then get each quiz's question count and maxmarks from `mdl_question_attempts`. Auditing the wrong quiz gives a plausible-looking but completely wrong report.
> Example from one deployment: "E-Quiz 1" = 80-grade, 16 graded questions (maxmark 1–2 each), timelimit 0; "CE-Quiz 1" = 20-grade, 4 questions, 45 min. When two quizzes match a student's description, ASK which one — don't guess.

## Data model (this build)
- `mdl_quiz_attempts`: `uniqueid` = `mdl_question_usages.id`. `sumgrades` = raw marks (NOT the /grade scale — divide by sum of question maxmarks for %). No `grade` column.
- `mdl_question_attempts`: `id, questionusageid, slot, maxmark, responsesummary` (the actual answer text!). Slot 1 = "Information" page (maxmark 0) — exclude.
- `mdl_question_attempt_steps`: `id, questionattemptid, sequencenumber, state, timecreated, fraction`. (No `event` column; `timecreated` is unix ts.)

## State semantics (adaptive behaviour — verified in question/behaviour/adaptive/behaviour.php)
- `todo` = question page viewed (repeated = re-reads)
- `complete` = the student **clicked Check and the answer was correct** (self-check happened) — **MC / standard questions ONLY**
- `gradedright`/`gradedpartial` with **no preceding verification** = answer was **only graded at final submit** — student never verified
- `gaveup`, `invalid` = skipped / incomplete submit
- Normal cohort pattern = one verification per question.

### ⚠️ CRITICAL PITFALL — CodeRunner questions use "Precheck", not "Check"
CodeRunner (`qtype_coderunner`) questions have **no Check button** — they have a **Precheck** button (behaviour `qbehaviour_adaptive_adapted_for_coderunner`). A Precheck is **NOT** a distinct step state; it is a step carrying a **`-precheck` flag** stored in `mdl_question_attempt_step_data` (this version), and the step's `state` can be `todo` or `complete`. So **counting only `state='complete'` silently misses every Precheck** — a student who iterated 40× on a code bug registers as "0 checks" = a **false positive**.

To detect a mixed MC+CodeRunner quiz, query question types per slot:
```sql
SELECT qa.slot, q.qtype FROM {question_attempts} qa JOIN {question} q ON q.id=qa.questionid
WHERE qa.questionusageid IN (SELECT uniqueid FROM {quiz_attempts} WHERE quiz=<id>) GROUP BY qa.slot, q.qtype
```
Then the correct per-question verification metric is **type-aware**:
- multichoice / standard → verification = count of `state='complete'` steps (Check)
- coderunner → verification = count of steps with `name='-precheck'` in `mdl_question_attempt_step_data`
```sql
-- per questionattemptid, number of prechecks
SELECT qast.questionattemptid, COUNT(*) n
FROM {question_attempt_step_data} qsd
JOIN {question_attempt_steps} qast ON qast.id = qsd.attemptstepid
WHERE qsd.name = '-precheck' AND qast.questionattemptid IN (...) GROUP BY qast.questionattemptid
```
Real case: a student with **96 Prechecks (44 iterations on one debugging question)** was wrongly flagged "3 checks" because only MC `complete` steps were counted. Always report the per-slot verification matrix so the human can see *which* question types were verified.

## Environment pitfalls (PHP in a Moodle pod — cost real debugging time)
1. `get_records_sql` keys results by the **first selected column** (duplicates overwrite). ALWAYS select the table's `id` first: `SELECT id, questionattemptid, ... `.
2. `usort()` and `array_merge()` reindex **integer keys** to 0,1,2… — sort `array_keys($arr)` separately, or iterate keys explicitly; never rely on keys surviving a merge/sort.
3. Closures at top level do not auto-bind globals — use `global $x;` inside or pass via `use`.
4. Chunk big `IN (...)` lists (~100 ids/chunk). Never select columns that don't exist in your version (verify with `information_schema.columns` first — e.g. some versions have no `mdl_question_attempt_step_behaviour` table; `event`/`remoteaddr`-style columns usually don't exist here).
5. `php -l` may be broken in the pod (it can report "Errors parsing" even on valid one-liners). Verify a script by actually **running** it (read-only queries) instead of trusting lint.
6. **Adapt the bootstrap paths to your own Moodle install** — find `config.php` and the data dir on your box, then run scripts as: `cd <hermes_home> && timeout 300 php -d display_errors=1 /tmp/x.php` where the script starts:
   ```php
   define('CLI_SCRIPT', true);
   define('MOODLE_INTERNAL', true);
   require('<your_moodle_root>/config.php');
   require_once('<your_moodle_root>/lib/setup.php');
   ```
   (In the source deployment: moodle root `/var/www/html/public`, hermes home `/var/www/moodledata/.hermes`.)
7. If a DB tool is available, prefer it for quick schema probes (`information_schema.columns`, `table_schema = DATABASE()`) and for confirming a table exists before joining it.

## Audit procedure
1. **Per-attempt metrics** (finished, non-preview, exclude test accounts like `e_altitest`): duration `timefinish - timestart`, score % = `sumgrades / Σmaxmark`, `checks` = count of `complete` steps on graded slots, `noComplete` = graded questions with zero `complete` steps, `views` = `todo` count.
2. **Cohort baseline**: median/p25/p90 durations; verification distribution (e.g. in one course 114/186 had exactly one verification per MC question). "Fast" = relative to median (e.g. ≤ 0.5×median or an absolute floor like 10 min), NOT a fixed number.
3. **Flag rule** (tune to cohort; the worked example used): `score% >= 90 AND total_verifications <= ~15`, with the sharpest sub-signal = **zero Checks on the MC questions** (MC questions have a Check button and most students use it; code questions may legitimately have few Prechecks for 1-liners). Rank and output the full cohort CSV so the instructor can tune the cutoff.
4. **Answer-text comparison** (the collusion discriminator):
   - MC slots: convergence expected (everyone picks the right option) — NOT evidence.
   - Code slots: count distinct normalized answers per slot + pairwise identical-answer rate. Verbatim/near-verbatim matches across students = copying. **Individual AI use typically produces DIVERSE code (different var names/styles) — absence of copies does NOT clear them.**
   - Identity slot ("print your name"): verify each student's own name is in the answer (rules out one person answering for many; also checks they did any work at all).
5. **IP cross-check**: if a `moodle_audit_quiz`-style tool is available, run it with the course's **lab/campus CIDR ranges** (ask the instructor; these differ per campus/lab) to get in-attempt-window IPs + non-campus flags (logstore retention limits apply — audit soon). Note: for open/remote quizzes the whole cohort may be off-lab; single-IP + on-lab is the strong lab signal.
6. **Timeline sanity**: with timelimit 0, `timestart` may be days before real activity (student leaves tab open). Use step `timecreated` span, not raw duration, to judge "quick completion" — report both.

## Interpretation — be honest about proof level
- The flag (near-zero checks + high score + fast) is a **strong indicator**, not proof. Benign explanations: confident student who never hits Check; leaving the tab open then pasting final answers at the end.
- Distinguish the two sub-patterns when reporting: **fast-finishers** (hard to explain benignly) vs **long-open-then-fast-finish** (plausibly benign).
- Present as a "suspicion list for investigation", never as an accusation; offer the answer-content follow-up as the next discriminating step.

## Output format
Table-free Matrix: ranked list with `name (group) — duration — score% — checks (of N) — IP(s) — note`. Save full CSV (e.g. `/tmp/<quiz>_ai_flags.csv`) and offer to upload it to the course as a hidden file.
