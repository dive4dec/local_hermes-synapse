---
name: quiz-integrity-deep-dive
description: "Investigate ONE student's quiz integrity + technical claims on this Moodle: verify 'computer crashed / runner hung' against logstore + Jobe health, compare shared questions across homework vs in-class attempts, detect AI-authorship signals, and produce integrity report + student email. Use when a single student disputes a result, claims technical failure, or shows perfect-homework/weak-in-class divergence."
---

# Quiz integrity deep-dive (single student)

Cohort screening belongs to `quiz-ai-misuse-audit`. This skill is the follow-up: one named student, a reported technical problem, and a suspicion (often instructor-raised) that AI did the homework. Everything here is READ-ONLY — no grade/access changes; end with report + email for the instructor to approve.

## Prereqs (this deployment)
- Moodle root `/var/www/html/public`, hermes home `/var/www/moodledata/.hermes`, course cs1302a_26a = id 3.
- PHP bootstrap scripts; run `cd /var/www/moodledata/.hermes && timeout 120 php -d display_errors=1 /tmp/x.php` (filter `REQUEST_URI` noise from output).
- **Raw mysqli is reliable here**: `new mysqli($host,$user,$pass,$db,$port)` from `$CFG` works for joins/ORDER BY even when `$DB->get_records_sql` is flaky ("Error reading from database"). Helper: `rows($m,$sql)` with `$m->error` output. (Older note "mysqli access denied" does not hold for the current pod.)
- **Table name gotcha:** the question-attempt table is `mdl_question_attempts` (plural). `mdl_question_attempt` does not exist and fails confusingly.
- `mdl_question_attempt_steps` cols: id, questionattemptid, sequencenumber, state, fraction, timecreated, userid. `mdl_question_attempt_step_data`: attemptstepid, name, value.
- Slot 1 = "Information" page; Question N = slot N+1.
- `quiz_attempts.uniqueid = question_usages.id`.

## Step 1 — establish the score contrast
Full quiz history: `SELECT qa.id, qa.quiz, qa.preview, qa.timestart, qa.timefinish, qa.sumgrades, z.name FROM mdl_quiz_attempts qa JOIN mdl_quiz z ON z.id=qa.quiz WHERE qa.userid=<uid> AND qa.preview=0 ORDER BY qa.timestart`
Note the pattern (e.g. perfect E-Quizzes vs weak CE-Quizzes). Identify the two attempts to compare (usage uniqueids from `quiz_attempts.uniqueid` of the finished attempts).

## Step 2 — the "computer crashed" verification (logstore)
MCP keyword filter blocks `timecreated` — use PHP/mysqli:
```sql
SELECT timecreated, ip, component, action, target, contextid
FROM mdl_logstore_standard_log
WHERE userid=<uid> AND timecreated BETWEEN <t0> AND <t1>
ORDER BY timecreated, id
```
Map contextid→quiz: `mdl_context`(instanceid)→`mdl_course_modules`(id)→`mdl_quiz`(instance).
Read the sequence around the attempt:
- **Autosave continuity = anti-crash test.** Code Runner quizzes autosave ~every minute. Continuous autosaves every ~60s until `submitted` with zero gaps = uninterrupted session; a crashing machine shows multi-minute rhythm breaks.
- **The converse matters too — autosave GAPS are client-side freeze evidence (HAIDER u611, 2026-10-06).** Gaps of 189–241 s (≈3 missed autosave cycles) mid-attempt, each resuming exactly at a check/submit moment = the page/browser was unresponsive for 3–4 min. That is a genuine "crash-like experience" and PARTIALLY SUPPORTS the student's claim (client-side, not server-side). Fairness caveat: a gap can also be a pause in typing (autosave only fires on change) — the discriminating details are gap ≥3 min, resuming exactly at a check, and pre-attempt SEB blocks on the same machine. Report as TWO SEPARATE findings: server side refuted (every request answered) + client side instability confirmed (freezes/SEB restarts).
- **`quizaccess_seb prevented`/`access` events** = SEB blocked (quiz requires SEB). Cluster a few minutes BEFORE `started`, with repeated `loggedin` on the lab PC = SEB/browser startup restart ("crash-like" startup, not in-attempt failure). Blocks DURING the attempt = real problem.
- Count events per IP in the window (`GROUP BY ip`) — one IP throughout = single device.
- **Cohort SEB sweep (do this before concluding it's one student's problem, HAIDER case 2026-10-06).** Query ALL `quizaccess_seb prevented` events for the quiz's `contextid` in a 2 h window: `SELECT userid, ip, COUNT(*) n, MIN(timecreated), MAX(timecreated) FROM mdl_logstore_standard_log WHERE component='quizaccess_seb' AND action='prevented' AND contextid=<ctx> AND timecreated BETWEEN <t0> AND <t1> GROUP BY userid, ip`. CE-Quiz 4 5 Oct: **87 students affected; 16 blocked DURING their attempt** (one with 33 in-attempt blocks), spread across the whole 175.159.202.x lab fleet + some campus/external IPs → systemic SEB/lab instability, worth escalating to IT. To find in-attempt blocks per user, join `quizaccess_seb` rows against each user's `quiz_attempts.timestart..timefinish`. The worst-affected in-attempt students show the same autosave-gap signature — corroborate with their autosave cadence before reporting.

## Step 3 — campus/lab IP check (don't guess ranges)
Campus/lab ranges live in `/var/www/moodledata/.hermes/.env` as `MOODLE_AUDIT_CAMPUS_IPS` — read it; for CS1302: `10.0.0.0/8, 144.214.0.0/16, 172.16.0.0/12, 175.159.202.0/24`. `175.159.202.x` = on-site lab PCs (NOT VPN — user-corrected 2026-10-06); `144.214.0.x` = campus. If all attempt IPs are in-range, there is no network anomaly — do NOT flag.

## Step 4 — per-question step timeline (where the student actually was)
```sql
SELECT s.questionattemptid, s.sequencenumber, s.state, s.timecreated
FROM mdl_question_attempt_steps s JOIN mdl_question_attempts q
ON q.id=s.questionattemptid WHERE q.questionusageid=<usage>
ORDER BY s.timecreated, s.id
```
Returns stuck-and-reworking (e.g. back to question 1 in final 7 min) vs abandoned (crash) vs smooth. Step states: `todo` (each Precheck/submit), `complete`, `gradedright`/`gradedpartial`/`gaveup` at final grading.

## Step 5 — server health: were any checks dropped/slow/hung?
The student's prechecks each stored a `_testoutcome` step_data value — a PHP-serialized `qtype_coderunner_testing_outcome`. Extract status: `preg_match('/s:6:"status";i:(\d+);/', $value)`.
Status codes (`question/type/coderunner/classes/testing_outcome.php`): **1=VALID** (full test result), **2=SYNTAX_ERROR** (student's code), **3=BAD_COMBINATOR**, **4=SANDBOX_ERROR** (server-side run failed), **5=MISSING_PROTOTYPE**, **6=UNSERIALIZE_FAILED**.
Scan the WHOLE cohort in the window (not just the student):
```sql
SELECT qa.id aid, s.timecreated, d.value
FROM mdl_question_attempt_steps s
JOIN mdl_question_attempts qat ON qat.id=s.questionattemptid
JOIN mdl_question_usages qu ON qu.id=qat.questionusageid
JOIN mdl_quiz_attempts qa ON qa.uniqueid=qu.id
JOIN mdl_question_attempt_step_data d ON d.attemptstepid=s.id AND d.name='_testoutcome'
WHERE qa.quiz=<quizid> AND s.timecreated BETWEEN <t0> AND <t1>
```
Only 1s and 2s, zero 3–6 = every check returned normally; nothing dropped/timed out/hung. (Real case: 2148 cohort checks during a 64-student lab spike → 1876 valid + 272 syntax errors + 0 server-side failures.)

## Step 6 — live Jobe probe (worst case = infinite loop)
Config: `SELECT name,value FROM mdl_config_plugins WHERE plugin='qtype_coderunner' AND name IN ('jobe_host','jobe_apikey')`.
POST `http://<jobe_host>/jobe/index.php/restapi/runs` (header `X-API-KEY: *** JSON body:
`{"run_spec":{"language_id":"python3","sourcecode":"...","sourcefilename":"__tester__.python3","input":"","file_list":[]}}`
Verified bounds: normal run ~0.2s; infinite loop killed by 5s CPU limit in ~6s (outcome=13); 12 concurrent infinite-loop jobs all returned in ~8s (serialized, never wedges). So "infinite loops blocked the runner" is bounded at ~5–6s and produces no dropped responses. Re-runnable probe: `scripts/jobe_probe.php` (self-bootstraps config from `$CFG`, read-only).
If the instructor pushes back with "the Jobe pod has 48 runners — why can't it handle 30 concurrent checks?", run the capacity ladder from `moodle-coderunner-jobe-diagnosis` (`scripts/jobe_capacity_probe.php`): configured slots ≠ executing CPUs. On this pod only ~16–27 CPU-saturating loops actually run at once (48-loop batch took 11.2 s); the pod is CPU-quota-bound. The freeze is queue delay in *mixed* load (loops + trivial checks), and it hits ANY user — including the instructor without SEB.

## Step 7 — shared-question comparison (the decisive AI-misuse signal)
Questions reused across the homework quiz and in-class quiz:
```sql
SELECT e.slot es, c.slot cs, q.name, e.responsesummary, c.responsesummary
FROM mdl_question_attempts e
JOIN mdl_question_attempts c ON c.questionid=e.questionid
JOIN mdl_question q ON q.id=e.questionid
WHERE e.questionusageid=<HW usage> AND c.questionusageid=<CE usage>
```
Full marks in homework + a DIFFERENT, weaker in-class version of the same question = he didn't build the solution (can't reproduce what you didn't write). This behavioural evidence (demonstrated inability to reproduce) is the defensible core; text forensics is supporting only.
Also look for literal `# YOUR CODE HERE` stubs / one-line non-answers on the non-shared questions.

## Step 8 — AI-authorship heuristics on the homework text (indicators, not proof)
```php
$cjk = preg_match_all('/[\x{4e00}-\x{9fff}]/u', $resp); // per answer
```
Signals: uniformly bug-free correct code; explanatory comments in the student's L1 (e.g. Chinese tutorial-style `# 只需要檢查到 sqrt(num)`) on hard questions but terse on trivial ones; all answers polished. Present as inference.

## Deliverables
1. **Integrity report** (one page, save to `.hermes/cron/output/`): score table → crash-claim verdict with log evidence → IP verdict → Jobe health (cohort status counts + live probe numbers) → AI signals + shared-question code side-by-side → assessment separating (a) technical claim refuted/supported from (b) integrity concern → actions.
2. **Student email** — tone spec lives in `pod-smtp-email-send` skill (learning-concern register). Plain language, no IDs/log internals; include the verified crash-check findings in 2–4 plain-language bullets; the "more help does not mean better learning — help can backfire" principle; AI-as-teacher; invite to Monday open hour or after Wednesday 9am–12pm lecture. Draft for instructor approval BEFORE sending.

## Pitfalls
- `usage` is a reserved word in MySQL — alias it (`qa.uniqueid uniq`) or quote it.
- `mdl_config` cols are only id/name/value; coderunner settings live in `mdl_config_plugins` (plugin/name/value).
- Don't trust a single status code — the `_testoutcome` payload also carries `errormessage`; for non-1/2 statuses, grep it.
- Logstore retention is limited — audit soon after the quiz.
- Keep technical-claim verdict and integrity assessment as SEPARATE findings; a refuted crash claim makes the integrity case stand on its own, and conflating them weakens both.
- Never email the student before the instructor approves the draft.
