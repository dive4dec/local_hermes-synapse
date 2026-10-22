---
name: moodle-quiz-integrity-audit
description: Detect potentially misused/flagged quiz attempts in this Moodle — AI answer-pasting, copying, off-campus access, timing anomalies. Reconstructs each student's per-question step trace from question_attempt_steps, uses adaptive-behaviour state semantics to flag "fast + high score + never self-checked" attempts, and cross-references in-window IPs. Use when the user suspects cheating/AI misuse on a quiz or wants a list of students to review.
---

# Moodle quiz integrity / AI-misuse audit

Find students who may have misused AI (or cheated) on a quiz. This box is an LTI course (<coursecode> / course id 3) with quizzes like "CE-Quiz 1" (quiz id 58) and "E-Quiz 1" (quiz id 57). Distinguish this from the sibling skills: `moodle-equiz-student-status` = pass/fail/enrolment cohorts; `moodle-quiz-question-progress` = who answered/skipped a slot; this one = **who did it suspiciously**.

## ⚠️ Step 0 — DISAMBIGUATE THE QUIZ BY ID, not by name (costs real work if skipped)
This course has **parallel quizzes with similar names that are DIFFERENT quizzes**: "CE-Quiz N" (4 questions, ~45-min time limit) vs "E-Quiz N" (16–17 questions, often **no** time limit). "CE-Quiz 1" (quiz 58, cmid 146) ≠ "E-Quiz 1" (quiz 57, cmid 145). In one session I audited CE-Quiz 1 thinking it was "the quiz" and only got corrected by the user saying *"E-Quiz 1 should have 16 questions instead"* — my whole 4-question analysis was for the wrong quiz.

**Before running anything, resolve the exact quiz id AND sanity-check the question count the user expects:**
```sql
SELECT q.id, q.name, q.preferredbehaviour, q.timelimit, q.grade, q.sumgrades, cm.id AS cmid
FROM mdl_quiz q
JOIN mdl_course_modules cm ON cm.instance=q.id AND cm.module=(SELECT id FROM mdl_modules WHERE name='quiz')
WHERE q.course=3 AND q.name LIKE '%E-Quiz 1%'   -- or filter by id
```
```sql
SELECT COUNT(DISTINCT qa.slot) FROM mdl_question_attempts qa
WHERE qa.questionusageid IN (SELECT uniqueid FROM mdl_quiz_attempts WHERE quiz=<id> AND preview=0);
```
If the user says "16 questions" and you find 4 (or 17 slots), you have the **wrong quiz — stop and re-resolve**. Also note each quiz's `timelimit`: `timelimit=0` means no limit and changes the "fast" criterion (see Flagging). Quiz ids are not a simple offset (E-Quiz 1=57, E-Quiz 2=59, …; CE-Quiz 1=58, CE-Quiz 2=60, …) — look them up, don't guess.

## Core method — reconstruct the per-question STEP TRACE
Standard tables (quiz_attempts, gradebook) only give duration + final score — not enough to spot "answered instantly without checking." The discriminating signal is in `mdl_question_attempt_steps`: one row per state transition per question. Read each student's full trace and you can see *how* they produced the answer (self-checked, or just submitted).

Join chain (this build's non-standard schema):
- `mdl_quiz_attempts` (quiz=58, preview=0): `id, userid, uniqueid, timestart, timefinish, sumgrades`. **`uniqueid` == the `question_usages.id`.** (No `grade` column; `sumgrades` is on the QUESTION scale, not `mdl_quiz.grade`.)
- `mdl_question_attempts` (questionusageid = quiz_attempts.uniqueid): `id, slot, maxmark, responsesummary`. **slot 1 = info page; slots 2..n = graded questions.** ⚠️ **2026-09-28 correction note:** in the E-Quiz 4 answer-dispute session the join `questionusageid = mdl_quiz_attempts.id` returned the correct rows (17/17 matching the attempt layout). If `= uniqueid` comes back empty on this build, try `= id` and verify against the attempt's `layout` string before concluding — which column holds is build/version dependent; confirm, don't assume.
- `mdl_question_attempt_steps` (questionattemptid = question_attempts.id): `id, sequencenumber, state, fraction, timecreated`.

⚠️ Two PHP-in-pod DB gotchas will bite you here — see **references/php-db-gotchas.md**. The two that matter for this task: (1) `get_records_sql` keys by the FIRST selected column and duplicate keys OVERWRITE, so always `SELECT id` (unique pk) first; (2) don't rely on `usort` preserving array keys — sort a separate `array_keys()` copy.

## The key insight: adaptive-behaviour state semantics
The quiz uses `preferredbehaviour=adaptive` (check `mdl_quiz`). Two "right" step states are NOT the same (verified against `question/behaviour/adaptive/behaviour.php`):
- **`complete`** = the student clicked **Check** and it was correct → they self-checked.
- **`gradedright` with no preceding `complete`** = the answer was graded **only at the final submit** → they never pressed Check.

A normal honest attempt shows, per question: `todo → … → complete(1) → gradedright(1)`.
A "pasted answer, never checked" attempt shows: `todo → … → gradedright` with **zero `complete`** steps.

So the user's symptom *"complete quickly, mostly correct, only very few prechecks/checks"* maps precisely to: **high score + zero VERIFICATION + all answers graded at submit + short duration**. ("Verification" is type-aware for mixed MC+CodeRunner quizzes — the critical pitfall below; a zero-`complete` count alone is NOT a valid "zero verification" claim when CodeRunner questions are present.)

### ⚠️ CRITICAL PITFALL — CodeRunner questions use "Precheck", not "Check" (2026-09-17, real false positive caught by the instructor)
`qtype_coderunner` questions have **no Check button** — they have a **Precheck** button (behaviour `qbehaviour_adaptive_adapted_for_coderunner`). A Precheck is **NOT** a distinct step state: it is a step carrying a **`-precheck` flag** stored in `mdl_question_attempt_step_data` (`attemptstepid, name, value`), and the step's `state` can be `todo` or `complete`. Counting only `state='complete'` **silently misses every Precheck** — a student iterating on a debugging question registers as "0 checks". Real case: a student on E-Quiz 1 (attempt 15707) had **96 Prechecks** (44 iterations on the final debugging question) and was wrongly flagged "3 checks"; the instructor caught it from the quiz review page. Full case write-up: **references/coderunner-precheck-false-positive.md**.

For a mixed MC+CodeRunner quiz the verification metric is **type-aware**:
- multichoice / standard slots → verification = count of `state='complete'` steps (Check)
- coderunner slots → verification = count of steps with `name='-precheck'` in `mdl_question_attempt_step_data`

Detect the mix first:
```sql
SELECT qa.slot, q.qtype FROM {question_attempts} qa JOIN {question} q ON q.id=qa.questionid
WHERE qa.questionusageid IN (SELECT uniqueid FROM {quiz_attempts} WHERE quiz=<id>)
GROUP BY qa.slot, q.qtype
```
(E-Quiz 1: slots 2–11 multichoice, slots 12–17 coderunner.)

Schema note: this Moodle version stores step behaviour data in `mdl_question_attempt_step_data` — there is **no** `mdl_question_attempt_step_behaviour` table here (joining it gives "Error reading from database"). Check `information_schema.tables` before joining.

Always report the per-slot verification matrix (count + final state per slot) so the instructor can see *which* question types were verified. The sharpest flag in a mixed quiz is usually **zero Checks on the MC questions** (MC has a Check button and most students use it; 114/186 on E-Quiz 1 checked all 10), since a code slot can legitimately have few Prechecks.

### ⚠️ CRITICAL PITFALL — CodeRunner questions use "Precheck", not "Check" (verified 2026-09-17, cost a false positive)
**`complete` only exists for questions that HAVE a Check button.** CodeRunner questions (`qtype_coderunner`, behaviour `qbehaviour_adaptive_adapted_for_coderunner`) have **no Check button — they have a Precheck button**, and a Precheck is **not a distinct step state**: it is a step carrying a **`-precheck` flag** in `mdl_question_attempt_step_data` (this version), and the step's `state` can be `todo` or `complete`. So on any quiz containing CodeRunner questions, **counting only `state='complete'` silently misses every Precheck** and a student who iterated hard on a code bug (one real case: 96 Prechecks, 44 on a single debugging question) registers as "0 checks" → **false positive**.

Before flagging, check the quiz's question types per slot:
```sql
SELECT qa.slot, q.qtype FROM {question_attempts} qa JOIN {question} q ON q.id=qa.questionid
WHERE qa.questionusageid IN (SELECT uniqueid FROM {quiz_attempts} WHERE quiz=<id>) GROUP BY qa.slot, q.qtype
```
If any slots are `coderunner`, use a **type-aware verification metric** and report a per-slot matrix:
- multichoice / standard → verification = `complete` step count (Check)
- coderunner → verification = steps with `name='-precheck'` in `mdl_question_attempt_step_data`:
```sql
SELECT qast.questionattemptid, COUNT(*) n
FROM {question_attempt_step_data} qsd
JOIN {question_attempt_steps} qast ON qast.id = qsd.attemptstepid
WHERE qsd.name = '-precheck' AND qast.questionattemptid IN (...) GROUP BY qast.questionattemptid
```
For a mixed quiz the sharpest remaining "few checks" signal is **zero Checks on the MC questions specifically** (MCs have a Check button and the cohort norm is one per MC). A sibling skill, `quiz-ai-misuse-audit`, implements this correctly end-to-end (type-aware metric, answer-text comparison, worked E-Quiz 1 numbers) — prefer it for new audits.

## Flagging (defensible, per-student)
For each finished real-student attempt compute:
- `noComplete` = # of graded questions whose final graded state (`gradedright/gradedpartial/gradedwrong`) had **no preceding `complete`** step. ← the core signal
- `dur` = timefinish − timestart; `scorePct` = sumgrades / Σ(maxmark of graded slots); `right`/`graded` counts.
- `checks` = # `complete` steps; `views` = # `todo` steps.

**Primary flag:** scorePct high (≥0.75) AND dur short AND `noComplete` high with no rework (retries = checks − graded ≤ 0).
**Watch list:** fast + high score even with some checks (speed alone — much weaker, list separately).

**"Fast" depends on the quiz:**
- Timed quiz (e.g. CE-Quiz N, 45-min limit): absolute threshold works — dur ≤ ~12 min.
- **No time limit (`timelimit=0`, e.g. E-Quiz N, open for days):** durations span minutes to days, so an absolute threshold is meaningless. Use a **cohort-relative** threshold: compute median/p25 of `dur` over all finished attempts and flag dur ≤ ~0.5×median (and at least ~10 min to skip accidental instant-submits). Then split the flagged set: short total duration (did it fast, all at once) vs very long total duration (left open for days but finished in one fast burst at the end — check the per-question grading timestamps: if all 16 graded states land within seconds of each other near `timefinish`, it was a single final submit).

**Corroborate before naming anyone:**
1. **Establish the cohort norm first** — compute the distribution of `checks` (and of `noComplete`) across ALL finished attempts. For E-Quiz 1 (16 q) the norm was stark: 114/186 students (61%) checked exactly 16× (once per question). A flag is only meaningful against that baseline — a student at 1–3 checks when 61% of the cohort are at 16 is an outlier; a student at 14–16 is not.
2. Check that all graded questions reached their final state at the *same* timestamp (spread ≈ 0 s = everything landed at final submit), and that `responsesummary` is non-empty for all questions (they produced real answers, not blanks). Both held for the CE-Quiz 1 and E-Quiz 1 flagged cohorts.

## Cross-reference in-window IPs
Use the **`moodle_audit_quiz`** tool (pass `cmid` OR `quiz`+`course_id`, and `campus_ips='<lab-cidr>,<campus-cidr>'`). It returns each attempt's in-window IP set + campus flag, **excluding post-finish activity** — far more reliable than hand-joining the logstore. Lab PCs = `<lab-cidr>`; campus = `<campus-cidr>`. A non-campus IP is a strong flag by itself. Helpers (group <helpergid>) may legitimately work off-lab.

**"Who wasn't in the lab" full-cohort list (large quiz, 100+ attempts):** the tool's per-attempt dump is unwieldy at that size — a compact PHP classifier is cleaner: one fetch of `mdl_logstore_standard_log` events (`eventname LIKE '%attempt%'`, `contextlevel=70`, `contextinstanceid=<cmid>`), grouped by user; collect the distinct IPs inside each attempt's `[timestart, timefinish+300]` window; classify (LAB `<lab-cidr>` / CAMPUS `<campus-cidr>` / LOCAL / OTHER-public); print ONLY the non-LAB rows with all their IPs. Grading flag strength: **public ISP IP** (e.g. `<public-isp-ip>` mobile carrier-NAT — multiple rotating IPs = phone hot-spot; `<home-line-ip>` home line) = strong flag; **on-campus but not lab** (`<campus-cidr>`, `<campus-cidr>`) = weaker (library/office PC, possibly SEB at home); **adjacent private subnet** (e.g. `<adjacent-subnet>`) = not a lab PC, verify what it is. Two extra checks in the same pass: (a) exclude helpers/teachers first (they sit off-lab legitimately); (b) compare `timefinish` vs the quiz `timeopen` — an attempt finishing BEFORE the window opened (e.g. ~8 h early) is a timeopen/override anomaly worth a separate look. (CE-Quiz 4, 2026-10-06: 202 attempts → 195 on lab, 6 off: 2 public-IP, 3 campus-non-lab, 1 adjacent-subnet pre-window.)

**Logstore hand-join recipe (gotchas that cost a session):** the table is `mdl_logstore_standard_log`. It has **no usable `cm` column** — `WHERE cm=<cmid>` silently matches ZERO rows (no error, just empty). Filter with `courseid=<cid> AND contextlevel=70 AND contextinstanceid=<CMID>`; activity events are `\mod_quiz\event\attempt_viewed` / `attempt_updated` / `attempt_submitted` (each carries `ip`), SEB blocks are `\quizaccess_seb\event\access_prevented`. The read-only SQL tool **rejects any query containing the substring `UPDATE`** (dangerous-keyword regex) — `eventname IN ('viewed','updated')` is blocked; use `eventname LIKE '%attempt%'` or a word that doesn't contain it.

**Live monitoring ("who is attempting right now, and remotely?")** — same recipe, two changes: (1) window = `[timestart, NOW]` and include `state='inprogress'` attempts (a live lab sitting shows up within minutes of the slot start); for the specific question "who is *currently* attempting remotely" **scope the report to `state='inprogress'` attempts ONLY** — finished attempts must be excluded entirely, because post-finish activity from a campus/home IP is review, not a violation (2026-10-13: a last-10-minutes scan flagged <student-D> u584 on 2 campus-IP events; his attempt had finished 25 min earlier, all on the lab PC — the user corrected: "not those who have completed and are reviewing"). (2) resolve WHICH cmid the attempts are actually on first — a quiz can have several CMs (CE-Quiz 5 = quiz 66 has three: 129/167/669; only 167 carried attempts). Find the live one: `SELECT cm.id cmid, COUNT(qa.id) n FROM mdl_course_modules cm JOIN mdl_context ctx ON ctx.instanceid=cm.id AND ctx.contextlevel=70 JOIN mdl_question_usages qu ON qu.contextid=ctx.id JOIN mdl_quiz_attempts qa ON qa.uniqueid=qu.id WHERE cm.id IN (<the CMs>) GROUP BY cm.id`. Then classify per student: LAB `<lab-cidr>` / CAMPUS `<campus-cidr>` / public-ISP; exclude helpers (group <helpergid>) and non-student accounts BEFORE reporting — **check the user's ROLE, not just group membership: "teacher" and "non-editing-teacher" role holders test quizzes off-lab and can sit `inprogress` for days without it being anomalous, and some hold a student-looking email address** (2026-10-12/13 CE-Quiz 5: <student-A> u726 LTI non-editing teacher; <student-B> u728 teacher, flagged until the user confirmed he's a teacher; <student-C> u734 has a `*-c@<student-domain>` email BUT role = teacher — opened a test attempt from campus IP, 16 events in 18 s, then idle). Query: `SELECT u.id, u.email, r.shortname FROM mdl_user u JOIN mdl_role_assignments ra ON ra.userid=u.id JOIN mdl_role r ON r.id=ra.roleid WHERE u.id=<uid>`. `mdl_course_modules` has no `mod`/`modname` column — `module` is the numeric FK (see `moodle-mcp-db-query` pitfall 11).

**Assigned-slot mapping (was the off-venue attempt in their slot?):** the quiz has one shared window, but each lab group sits it at a fixed hour. Histogram ALL attempts' start-hour and cross-join to lab groups — the hour dominated by one group's members IS that group's slot (CE-Quiz 4, 2026-10-05: 10:00 = T03 (59), 15:00 = T01 (59) + TA1 (10)). A student starting at their slot's start-minute = sat it in-slot even from a non-lab IP.

**Real attempt vs. "just reviewing":** a post-close review creates NO `mdl_quiz_attempts` row, so any attempt row with `attempt_started` + a run of `attempt_autosaved` events + `attempt_submitted` + per-question precheck/Check steps = genuine attempt, not review. SEB compliance check: `access_prevented` events PRE-attempt are normal (the SEB-launch flow requires browsing the quiz page in a normal browser first to download the .seb config); the flag is blocks MID-attempt. Single IP + continuous autosaves over the window = one continuous sitting.

## Honest caveat — always state it
The step trace is a strong **indicator** matching the symptom, **not conclusive proof of AI**: a confident student who simply never hits Check produces the identical trace. The true discriminator is the **answer content** — pull `responsesummary` and look for verbatim / near-verbatim matches across students, or suspiciously clean/canonical answers. Always offer "let me pull their actual answer text and compare" as the next step. Never present a trace-only list as proof.

### Policy framing (2026-10-05, instructor's words) — AI is *allowed* on E-Quizzes; what's not allowed is not showing understanding
The instructor's position: **students MAY use AI tools of their choice on E-Quizzes (the homework/open quizzes), but they are still expected to write an answer that shows their own understanding.** So the integrity finding is **not** "the student used AI" (that's permitted) — it's **"the student's answer doesn't demonstrate their own understanding"** (no iteration/self-check, AI-didactic comments, or — the sharpest tell — can't reproduce a "perfect" answer when the same question is re-asked in the in-class CE-Quiz). Frame every report and every student-facing communication in those terms: it's a *demonstrated-understanding* gap, not a *tool-use* accusation. CE-Quizzes (in-class, SEB) are the controlled venue where the ability should surface — a perfect open E-Quiz with a failed in-class CE-Quiz on the same questions is the textbook signal.

## Workflow
1. **Resolve + disambiguate the quiz id by name→id (Step 0)** and confirm the question count + `timelimit` the user expects before trusting any result.
2. Reconstruct traces for all finished real students (skip the `e_altitest@…` test account). Compute the **cohort baseline** (checks / noComplete / duration distributions) so flags are relative, not absolute.
3. Compute per-student metrics; separate primary flags from watch-list.
4. Cross-reference in-window IPs via `moodle_audit_quiz` (low value for no-time-limit *remote* quizzes where the whole cohort is off-campus — note that rather than over-weighting it).
5. Report, in this order: **primary flags** (name / email / group / duration / score / noComplete / IP); **borderline** (partial no-check); **deliberately NOT flagged** (fast + high but properly self-checked — proves the check matters); **IP anomalies** (non-campus). End with the caveat + the offer to pull answer text.

## Cross-quiz consistency check on reused questions — the strongest AI-misuse signal (worked example, u553, 2026-10-05)
When CE-Quiz N reuses questions from homework E-Quiz N (same `questionid` in both quizzes — compare the slot/questionid lists of both attempts), **one student's two answers to the SAME question** are sharper evidence than any step trace:
- Pull `responsesummary` (student code) from both attempts for the shared `questionid`s (join chain in Core method).
- **Decisive pattern:** homework answer is clean/correct with AI-style tutorial comments (for this Cantonese-medium cohort: Chinese explanatory comments like `# 內層迴圈 1：印出該行的空格` on otherwise-minimal code), while the in-class answer to the identical question is a *different, weaker/buggy* solution — or a stub (`# YOUR CODE HERE` left in) / non-answer (`n = int`). A student who genuinely wrote and understood the homework solution cannot produce an inferior variant of the same question under time pressure. This doubles as the "student is not learning" finding the instructor cares about: the perfect homework score reflects AI output, not his competence.
- Cheap CJK pre-scan per response: `preg_match_all('/[\x{4e00}-\x{9fff}]/u', $responsesummary)` — didactic Chinese comments on clean code = LLM-authorship signature; compare the per-question distribution across the cohort (a student case: the six hard 2-mark questions carried 10–109 CJK chars each with 2–8 `#` comments; the trivial ones were terse/none).
- **Refuting a "computer crashed a lot" claim:** logstore for the attempt window — continuous `autosaved` events (~every minute), single IP, no gaps/error events, and the attempt actually reached `submitted` = no crashes. `quizaccess_seb prevented access` events = SEB not in use (the strong flag for a lab quiz). If the student also blames the code runner / a hung infinite loop, run the **Jobe health check** — direct `/runs` probe + cohort `_testoutcome` status scan — **references/jobe-coderunner-health.md**.
- **IP caution:** `<lab-cidr>` is the LAB PC range per this skill's Cross-reference section — do NOT call an IP in it off-campus (an earlier report mislabeled it; the defensible flags are SEB-blocked + behaviour, not the IP itself).
- Fairness: AI authorship is inferred from indicators, not proven; the *behavioural* contrast (can't reproduce his own "perfect" solutions in class) is the most defensible part — it's about his demonstrated ability, not text forensics. Suggested next step: in-person, no-internet re-demonstration where he explains the logic as he writes.

## Support files
- **references/php-db-gotchas.md** — the verified PHP/DB quirks for writing ad-hoc scripts on this box (get_records_sql keying, usort reindex, closure capture, driver flakiness on multi-joins). Read before writing any DB script.
- **references/jobe-coderunner-health.md** — how to prove/disprove "the computer crashed / the code runner was slow": logstore autosave-continuity check + direct Jobe `/runs` probe + cohort `_testoutcome` status-code scan (status 3–6 = dropped/errored; 1/2 = normal).
- **scripts/integrity_audit.php** — present in this skill dir (type-aware integrity audit; reads `MHS_*` env vars — run `mhs-setup` first). A sibling, more metric-focused implementation also lives in `quiz-ai-misuse-audit`: `scripts/quiz_ai_audit.php` (quiz/course id + MOODLE_ROOT at top; Check+Precheck metric; cohort distribution + per-slot verification matrix + rare-verifier focus list).
