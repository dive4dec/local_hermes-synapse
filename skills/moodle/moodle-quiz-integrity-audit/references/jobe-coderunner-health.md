# CodeRunner / Jobe health — refuting or confirming "the computer crashed / the runner was slow"

Students frequently claim their machine crashed, or that the code runner hung on an infinite loop, to explain a low in-class score. Don't take the word for it — check server-side. Two independent checks are decisive.

## A. Logstore: was the attempt actually interrupted?

`mdl_logstore_standard_log` (columns: `timecreated, ip, component, action, target, contextid`). For the student + attempt window:
- **Continuous `autosaved` events (~every 50–70 s) with no multi-minute gap** = the client was up the whole time. A crashing browser stops the autosave rhythm.
- **The converse (HAIDER u611, 2026-10-06): autosave GAPS of 3–4 min = client-side freeze.** Three gaps (189–241 s) mid-attempt, each resuming exactly at a check = unresponsive page/browser. This is a REAL "crash-like experience" and *partially supports* the student's claim — even while the server side is fully refuted (all his checks answered, 0 errors). Caveat: a gap can be a typing pause (autosave fires on change); the tell-tale details are ≥3 min, resuming at a check, and pre-attempt SEB blocks on the same machine. Verdict then = two separate findings: (1) server side refuted, (2) client instability confirmed → possible lab/SEB reliability issue.
- **Systemic check (HAIDER case): before attributing to one student, sweep the whole cohort.** `SELECT userid, ip, COUNT(*) n FROM mdl_logstore_standard_log WHERE component='quizaccess_seb' AND action='prevented' AND contextid=<quiz ctx> AND timecreated BETWEEN <window> GROUP BY userid, ip` then join each user's attempt window to separate pre-attempt vs in-attempt blocks. CE-Quiz 4 (5 Oct): 87 students hit SEB blocks, 16 in-attempt (one with 33 blocks), spread across the whole 175.159.202.x lab fleet + a few campus/external IPs → escalate to IT as lab/SEB reliability, don't treat as individual student issues.
- The attempt reaches `action='submitted'` = nothing was lost.
- `component='quizaccess_seb' action='prevented'` = SEB not in use at that moment. On a lab quiz that's a real flag (and usually a *pre-attempt* SEB startup hiccup — cluster the timestamps: if the SEB blocks are minutes before `timecreated` of the `started` event, it's a browser/SEB restart at login, not a mid-attempt crash).
- Continuous `autosaved` + single IP + reached `submitted` + zero error events = **no crash**.

## B. Jobe outcome scan: were any checks dropped / hung / errored?

Each CodeRunner check stores its result as a serialized `qtype_coderunner_testing_outcome` in `mdl_question_attempt_step_data` (`name='_testoutcome'`). Extract the `status` int and classify:

| status | meaning |
|---|---|
| 1 STATUS_VALID | full test result returned normally |
| 2 STATUS_SYNTAX_ERROR | student code had a syntax error (normal) |
| 3 STATUS_BAD_COMBINATOR | error |
| 4 STATUS_SANDBOX_ERROR | **the run failed / server error — a hung Jobe would show this** |
| 5 STATUS_MISSING_PROTOTYPE | error |
| 6 STATUS_UNSERIALIZE_FAILED | deserialise failure — **a broken/dropped response would show this** |

The discriminator: across the **whole cohort** for the window, if every check is status 1 or 2 and there are **zero** 3/4/5/6, nothing was dropped, timed out, hit the submission limit, or errored — the runner was healthy for everyone. Query (this build — see gotchas: alias any `usage` column, select a unique pk first):
```sql
SELECT qa.id aid, s.timecreated tc, d.value v
FROM mdl_question_attempt_steps s
JOIN mdl_question_attempts qat ON qat.id=s.questionattemptid
JOIN mdl_question_usages qu ON qu.id=qat.questionusageid
JOIN mdl_quiz_attempts qa ON qa.uniqueid=qu.id
JOIN mdl_question_attempt_step_data d ON d.attemptstepid=s.id AND d.name='_testoutcome'
WHERE qa.quiz=<id> AND s.timecreated BETWEEN <t0> AND <t1>
```
Then `preg_match('/s:6:"status";i:(\d+);/', $v, $mm)` per row and tally. Real case (TSO, CE-Quiz 4, 64 students, 2026-10-05): **2148 checks, 1876 status-1 + 272 status-2, ZERO 3–6** → runner healthy, "crash" refuted.

### Direct Jobe probe (is the server responsive right now?)
Config lives in `mdl_config_plugins` (`plugin='qtype_coderunner'`), keys: `jobe_host` (e.g. `jobe`), `jobe_apikey`, `jobesandbox_enabled`, `wsmaxcputime` (CPU-kill seconds, was 5). REST endpoint: `http://<jobe_host>/jobe/index.php/restapi/runs`, POST `{"run_spec":{"language_id":"python3","sourcecode":"…","sourcefilename":"__tester__.python3","input":"","file_list":[]}}` with header `X-API-KEY: <jobe_apikey>`. The `/status` endpoint 404s — use `/runs`.
- Trivial script → ~0.2 s, `outcome=15` (RESULT_SUCCESS).
- **Infinite loop → ~6 s, `outcome=13` (RESULT_TIME_LIMIT)**: Jobe's CPU limit kills it; it does NOT hang.
- 12 concurrent infinite-loop jobs → all returned in ~8 s wall (Jobe serializes rather than wedges).
So the "infinite loop blocks the runner for a long time" theory is bounded at ~5–6 s and Jobe copes with concurrent load. Outcome codes: 11 compile-err, 12 runtime-err, 13 time-limit, 15 success, 17 memory, 19 syscall, 20 internal, 21 overload, 30/31 output/abnormal.

## Net
If autosaves are continuous, the attempt submitted, and the cohort outcome scan is 100% status 1/2, the "computer crashed / runner was slow" explanation is refuted and the low score stands. The real story is then usually the academic-integrity one (can't reproduce a "perfect" homework solution in class).