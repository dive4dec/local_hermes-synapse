---
name: moodle-coderunner-jobe-diagnosis
description: "Diagnose Code Runner check/precheck slow, frozen, or not-working reports on this Moodle plus Jobe sandbox build. Measure live Jobe latency, detect head-of-line blocking under in-class bursts, quantify cohort check load and infinite-loop time-limit jobs from the DB, and separate server-side from client-side SEB or frozen-tab causes. Use when a student or teacher reports the Precheck or Check button hanging, a computer crash, or checks not responding during a quiz."
---

# Code Runner / Jobe "check freeze" diagnosis

Student or teacher says: "the check/precheck didn't work", "it froze", "my computer crashed" during a Code Runner quiz. Determine whether the **server** (Jobe/web tier) or the **client** (SEB, browser, lab PC) is at fault, with evidence a future session can cite.

## Triggers
- "check/precheck doesn't work / freezes / is slow" during a quiz
- "my computer crashed during the quiz" (verify against logs)
- Planning a large concurrent in-class quiz and asking whether Code Runner will cope
- After any quiz where many students report technical trouble at the same time

## Architecture (this build)
- Jobe pod: `jobe` (K8s service name). REST: `http://jobe/jobe/index.php/restapi/runs` (POST), `/files`, `/languages`; header `X-API-KEY: <key>`.
- Config: `mdl_config_plugins` where `plugin='qtype_coderunner'` → `jobe_host` (may be `;`-separated list = load-balanced), `jobe_apikey`, `wsmaxcputime` (s, default here **5**), `wsmaxhourlyrate`, `enablegradecache`.
- Check flow: browser → php-fpm → curl to Jobe (synchronous, no client progress indicator) → Jobe runs sandbox process (CPU-limited) → result. **All students share the Jobe instance(s) in `jobe_host`.**
- Grading cache: identical runs are cached (`coderunner_grading_cache`) — repeat identical answers don't hit Jobe again.
- Sandbox constants (`question/type/coderunner/classes/sandbox.php`): Jobe outcome codes — 11 compile error, 12 runtime error, **13 time-limit (loop killed)**, 15 success, 17 memory, 20/21 internal/overload.
- Test-outcome status codes (`classes/testing_outcome.php`): **1 = VALID** (full result returned), **2 = SYNTAX_ERROR** (student's fault), 3 = bad combinator, **4 = SANDBOX_ERROR**, 5 = missing prototype, 6 = unserialise failed. Status ≥3 in a step = genuine server-side failure — **a healthy window contains none.**

## Step 1 — Is Jobe healthy right now? (live probe, read-only)
Run the bundled probe (no system changes, safe during a live quiz):
```
php <skill_dir>/scripts/jobe_probe.php        # reads jobe_host/jobe_apikey from Moodle config
```
It runs: trivial script (expect ~0.2 s), a bounded loop, an **infinite loop** (expect killed at ~cputime+1 s, outcome 13), and a **30-job mixed concurrent burst** (15 trivial + 15 infinite loops).
Interpretation:
- Trivial slow (>2 s) or loops never returning → Jobe problem (scaling/restart).
- Trivial fast, but in the mixed burst the **trivial jobs take seconds** (avg ≫0.5 s, max >2 s) → **head-of-line blocking**: Jobe's finite workers are occupied by 5–6 s loop jobs; normal checks queue behind them. This is the classic cause of "check froze for minutes" during in-class bursts.

### Step 1b — Measure the pod's REAL parallelism (capacity ladder)
A claimed "N runners" is a count of **concurrent slots, not CPUs that execute at once** — the real ceiling is the Jobe pod's CPU quota. Run the bundled ladder (read-only, ~40 s):
```
php <skill_dir>/scripts/jobe_capacity_probe.php
```
It fires CPU-saturating infinite loops in batches (8/16/32/48) and derives implied parallelism `N / ceil(wall / 6.2)`. Measured on the CE‑Quiz 4 pod (claimed 48 runners, 6 Oct 2026): **8 loops→6.2 s, 16→9.1 s, 32→8.5 s, 48→11.2 s ⇒ only ~16–27 executing at once; 48 trivial checks→0.5 s**. Consequences: 30 concurrent *trivial* checks are fine (0.3 s); the freeze appears in *mixed* load because loops pin the pod's cores for ~6 s each and starve both normal checks AND Jobe's own Apache/PHP request handling. If asked "why aren't 48 runners enough to handle 30 concurrent checks": **the pod is CPU-bound, not slot-bound** — answer with the ladder numbers, and say more runners/slots won't help; the levers are CPU limit / more pods (`;`-list) / lower `wsmaxcputime`.

## Step 2 — Did the real window have that load? (DB, read-only)
1. **Check volume per minute** for the quiz's attempt window (bursts at slot start are the risk):
```sql
-- per-minute precheck volume for quiz <qid>, window <t0>-<t1> (raw mysqli / PHP bootstrap; MCP can't use timecreated)
SELECT FROM_UNIXTIME(FLOOR(s.timecreated/60)*60) m, COUNT(*) checks
FROM mdl_question_attempt_steps s
JOIN mdl_question_attempts qat ON qat.id=s.questionattemptid
JOIN mdl_question_usages qu ON qu.id=qat.questionusageid
JOIN mdl_quiz_attempts qa ON qa.uniqueid=qu.id
JOIN mdl_question_attempt_step_data d ON d.attemptstepid=s.id AND d.name='-precheck'
WHERE qa.quiz=<qid> AND s.timecreated BETWEEN <t0> AND <t1>
GROUP BY FLOOR(s.timecreated/60) ORDER BY m
```
2. **Server-side failures**: extract `s:6:"status";i:(\d+);` from each `_testoutcome` step_data value in the window. All 1/2 = healthy; any 3–6 = server-side problems (list them with timestamps).
3. **Infinite-loop load**: a time-limited run prints nothing → count `s:3:"got";s:0:""` (empty got) vs non-empty across the window. ~5–10% of test runs being empty in a 60-student concurrent quiz = continuous 6-second jobs feeding the queue.
4. **Cohort start burst**: `SELECT timestart FROM mdl_quiz_attempts WHERE quiz=<qid>` — 60+ starts inside one minute = the trigger shape.

## Step 3 — The individual's "crash/freeze" claim (client vs server)
1. **Autosave heartbeat**: `mdl_logstore_standard_log` where `userid=<u> AND component='mod_quiz' AND action='autosaved'` in the attempt window. Cadence ~60–75 s; **gaps >180 s** = client unresponsive *or a typing pause* (autosave only fires on change — a gap alone is NOT proof of a freeze). Gaps resuming exactly at a check = student waiting on a slow round-trip.
   **Decisive client-freeze test (verified 2026-10-06, Haider u611):** a **multi-minute (≥2–4 min) window with ZERO requests of any kind from the student** (no autosave/update/view) while **cohort-wide autosave counts stay flat** (~20–30/min from other students those same minutes) = **client-side hang** (SEB lockdown browser / lab PC), not the server. A Jobe queue explains *seconds* of check delay at most (measured ceiling ≈5–11 s under 30–48-job bursts) — it **cannot** explain a 3–4 min total blackout. Such a case = a **lab-machine/SEB stability** issue (IT ticket), not Moodle/Jobe. If another report/sibling-agent claims a different cause, re-verify from logstore+DB and **concede with data when it's right** (a sister hermes instance on this host was right on Haider's case).
   **Safe student-facing recovery:** refreshing the page is fine — the attempt resumes server-side, the timer keeps running, at most ~1 min of unsaved typing is lost. If the tab is fully unresponsive, force-quit SEB and relaunch, then reopen the quiz URL.
2. **SEB blocks**: `component='quizaccess_seb' AND action='prevented'` (`target='access'`). Pre-start clusters between fresh `core loggedin` events = SEB/browser startup restart — real, but only costs pre-attempt time. SEB gates *entry*, it never delays *checks*.
3. **Step-level completeness**: if every step for the student carries a status-1 `_testoutcome`, every request was answered — no dropped checks.
4. **Verdict**: continuous autosaves + zero server errors + attempt completed ⇒ claim not supported *during* the attempt; pre-start SEB hiccup = the only real glitch. Report both halves honestly.

## Step 4 — Escalation / fixes (do NOT apply to a live quiz without explicit go-ahead)
1. **Scale Jobe** — and be precise: the bottleneck is the pod's **CPU quota**, not the runner-slot count (Step 1b). Either raise the Jobe pod's CPU limit / move it to more cores, **or** run 2–3 pods and set `jobe_host` = `;`-separated list (CodeRunner natively load-balances + sticky-routes). Just adding configured slots to the same pod does nothing.
2. **Lower `wsmaxcputime`** (5 → 2–3 s) to shorten worst-case queue occupants (a loop then pins a core ~3 s instead of ~6 s).
3. **Client UX**: real "running…" state + timeout/retry on the check button so slow = "slow", not "frozen".
4. **Flatten the burst**: stagger lab-group start times a few minutes.
Fairness note for reports: queue delay costs *time/frustration*, not accuracy — every completed check is graded correctly; state that explicitly.

## Pitfalls
- `usage` is a **reserved word** in MariaDB — never use it as a bare column alias (use `uniq`, `qusage`).
- This build uses **legacy plural tables** `mdl_question_attempts` / `mdl_question_attempt_steps` (with `slot`, `questionid`, `maxmark` directly) — not the Moodle-5 `mdl_quiz_questions` + `mdl_question_attempt` schema. The MCP read-only replica is partial (missing/stale) — **use raw mysqli or the PHP bootstrap for these tables**.
- MCP keyword filter blocks `timecreated` (contains "CREATE") — use raw mysqli for any logstore/step time queries.
- Pod PHP `date()` is **UTC+8**; logstore/step `timecreated` epochs are UTC — format with `date('H:i:s', $ts)` in PHP (HKT) and note it, or `date(...).'-u'`-compare against `date -u`.
- Logstore columns on this build: `userid, timecreated, ip, component, action, target, contextid` — **no** `eventname`/`crud`/`objectid`. `contextid` = module context; map via `mdl_context` → `mdl_course_modules` (`cm.instance` = quiz id).
- Lab PCs: `175.159.202.0/24` are **valid on-site lab IPs** (see `.env MOODLE_AUDIT_CAMPUS_IPS`) — never flag them as off-campus/VPN.
- Jobe probe scripts must be **read-only** (REST `runs`/`languages` only, no config writes) — safe to run while students are active.
- The check is an **async XMLHttpRequest** (coderunner `amd/src/outputdisplayarea.js`, `runCodeDirect`) with no client timeout — so a *short* freeze = long round-trip, not a JS/PWA block. **BUT** the whole tab CAN be dead for minutes when the lab PC/SEB hangs (a multi-minute zero-request blackout with flat cohort activity = client hang, see Step 3.1) — don't rule out a real client freeze, and never attribute a multi-minute blackout to Jobe.
- Jobe's admin/status REST endpoints 404 in this build (`restapi/`, `restapi/status`, `admin` all 404) — there is **no exposed runner-queue metric**. The only way to measure real parallelism is the Step 1b capacity ladder against live `runs`.
- The Moodle pod itself is large (72 cores, 1 TB RAM, no CPU cgroup limit, `max_connections=500` with ~5 live DB conns) — the Jobe *pod* is the small CPU-bound box, not this one. Don't confuse the two when attributing the bottleneck.
- PWA service worker (`local/pwa/sw.js`) only caches GET static assets (styles/JS/pix) — it never intercepts check POSTs; don't blame it for check delays.
- php-fpm on this pod: 200 workers, load/mem usually healthy — check `pm.max_children` in `/usr/local/etc/php-fpm.d/zzz_custom.conf` and `cat /proc/loadavg` before blaming the web tier.
- Companion skills `moodle-quiz-attempt-inspection` and `quiz-ai-misuse-audit` are **manually authored (human-only edits)** — skill_manage patches are refused; keep their corrections in this skill or in memory.

## Reference files
- `references/ce4-case-2026-10-05.md` — worked example: CE-Quiz 4 freeze reports, full numbers (87 SEB-block students, 2,148 checks, 251 silent runs, reproduced HOL blocking, 48-slot capacity ladder), verdicts per student.
- `scripts/jobe_probe.php` — live Jobe health + head-of-line-blocking probe (read-only).
- `scripts/jobe_capacity_probe.php` — real-parallelism capacity ladder (read-only; answers "why aren't N runners enough").
