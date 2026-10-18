---
name: moodle-answer-dispute-investigation
description: "Investigate a student's claim that a quiz recorded the wrong, missing, or extra answer vs what they submitted (system added an option they did not pick, answer not saved, marked for a question they never saw). Per-slot forensics: attempt question-set vs current quiz definition (snapshot/restore trap), _order + choiceN reconstruction from step data, logstore limits, question-type source review. Use when a student or teacher disputes a recorded answer or a question's marking."
---

# Moodle answer-dispute investigation (student vs recorded answer)

A student claims the system recorded an answer different from what they submitted
(option added / dropped / changed), or a mark reflects an answer they never chose.
This is **forensics of one student's stored submission**, not an integrity audit
(suspicious attempts → `moodle-quiz-integrity-audit`), not absentee zeroing
(`moodle-absent-zero-grade`), and not question-quality review
(`moodle-quiz-question-review`). The deliverable: what the system **actually
stored** for that slot, when, with the raw evidence, plus what the code can and
cannot do.

Environment: this box is a Moodle 5.x fork (dive/socratic, cs1302a_26a = course
3). Schema traps below are for THIS build.

## Step 0 — pin the three identities (skipping this costs a full wasted run)
1. **Student**: `mdl_user` by firstname+lastname. LTI usernames are opaque
   (`enrol_lti<hex>`); emails look like `<initials><n>-c@my.cityu.edu.hk`.
   Disambiguate by surname — there are multiple LAU Tsz *Ying*/Tsz *Long* etc.
2. **Quiz**: `mdl_quiz` by name **AND course**. ⚠️ Parallel course instances exist:
   course 2 and course 6 each carry their own "E-Quiz 4"/"CE-Quiz 4" (e.g. quiz 26
   cm 61 course 2; quiz 63 cm 160 course 3; quiz 161 course 6). Confirm the
   student's enrolled course and use THAT course's quiz.
3. **Question**: the question the student describes (stem text + option count).
   Note its id(s) — remember 5.x questions are versioned (see Step 2).

## Step 1 — the attempt row
`mdl_quiz_attempts` (quiz, userid): `state, timestart, timefinish, timemodified,
sumgrades, layout`. `layout` = comma slot list per page, `0` = page break
(e.g. `1,0,2,3,4,5,6,0,7,8,9,10,0,11..17,0`).
⚠️ **Timezone split**: PHP CLI / `userdate` = Asia/Hong_Kong (HKT, UTC+8); the
MCP `query` tool's `FROM_UNIXTIME()` = UTC. 16:03 UTC = 00:03 HKT *next day*.
Always print both or state the TZ; compare raw unix. `timecreated=0` (1970)
means "restored from backup", not "created then".

## Step 2 — resolve the attempt's REAL question set (#1 pitfall, cost 2026-09-28)
An attempt may contain a **different question set than the quiz's current
definition** — the quiz was re-edited / clone-restored after the attempt opened,
or the attempt itself was restored. Verify BEFORE any deep forensics:
- ⚠️ **`mdl_question_attempts.questionusageid` == `mdl_quiz_attempts.uniqueid`,
  NOT `mdl_quiz_attempts.id`.** This fork has BOTH columns and they DIFFER
  (attempt 16569: id=16569, uniqueid=16681). On 2026-09-28 the first pass
  followed `id` and it coincidentally hit a **stale/ghost `question_usage` of the
  same number** (16569) carrying a DIFFERENT quiz's set → a false "snapshot trap /
  restored attempt" conclusion that cost the afternoon. Always: `SELECT id,
  uniqueid, state FROM mdl_quiz_attempts WHERE id=?`, then join `question_attempts`
  by `questionusageid = uniqueid`.
- Get the attempt's set: `mdl_question_attempts` by `questionusageid` (= uniqueid).
  Cross-check the slot count against `layout` and confirm the disputed question's
  qid is present BEFORE any per-slot forensics.
- Get the current set: `mdl_quiz_slots (id, slot, quizid, page, maxmark)` →
  `mdl_question_references (itemid = quiz_slots.id, questionbankentryid, version
  NULL = latest)` → `mdl_question_versions (questionbankentryid, version,
  questionid)` → `mdl_question (id, name, qtype)`.
- **Compare the two sets.** If the disputed question is NOT in the attempt:
  STOP — the claim doesn't map to this attempt. Usual causes: restored/duplicated
  attempt, parallel course instance, or student memory of a different quiz.
- **Restored-attempt signals** (look for these ONLY on the correctly-resolved
  usage): step `timecreated` days *earlier* than `quiz_attempts.timestart`; the
  attempt's question set == a DIFFERENT quiz's current set; `mdl_quiz.timecreated
  = 0`. ⚠️ On 2026-09-28 these signals (09-24 steps, E-Quiz 3's set) belonged to
  the GHOST usage 16569, NOT the student's real usage 16681 (a clean loops set) —
  a false alarm caused by following `quiz_attempts.id`. Don't invoke "restored"
  until you've confirmed the set mismatch is on the `uniqueid`-resolved usage.
- Versioning note: same `questionbankentryid` has multiple `mdl_question` rows
  (v1, v2…). An attempt may reference the older row; the quiz shows the latest.

## Step 3 — per-slot forensics (only once the question is confirmed in the attempt)
1. **`_order`** — step 0 data row `name='_order'`: comma list of answer ids in
   DISPLAY order; position i = option letter (a=pos0, b=pos1, c, d, e…).
2. **complete step** — `mdl_question_attempt_steps` state `complete` (last data
   step before grading) → `mdl_question_attempt_step_data`: in THIS build every
   option is stored explicitly as `choice0..choiceN=0|1` (deviation from stock
   Moodle, where unchecked boxes are absent), plus `-submit=1`, `-_try`,
   `-_rawfraction`.
3. **Selected options** = positions where `choiceN=1`, mapped to letters via
   `_order`. Cross-check `mdl_question_attempts.responsesummary` /
   `rightanswer` (cached text summaries) — they are snapshots of the question
   text at grading time and go stale after edits; **raw step data wins**.
4. `mdl_question_answers` for that questionid: check BOTH the `correct` flag and
   `fraction` (the actual grading weight). Observed 2026-09-28: a fresh question
   with `correct=0` on all 5 options — verify `fraction` before declaring "no
   correct option configured".

## Step 4 — the "log of the attempt" is step data, NOT the logstore
`mdl_logstore_standard_log` columns: `eventname, component, action, target,
objecttable, objectid, contextid, contextlevel, contextinstanceid, userid,
courseid, other (JSON payload), timecreated, origin, ip, realuserid`.
- **There is NO per-question student submit/check event in this build.** In-quiz
  you only see `\mod_quiz\event\attempt_viewed|updated|autosaved|started|
  submitted|ended`. The logstore therefore CANNOT show which options were
  POSTed — it shows page-level activity only.
- Filter by `contextid` (get it: `SELECT id FROM mdl_context WHERE
  instanceid=<cmid> AND contextlevel=70`). There is NO `coursemodule` or `edata`
  column.
- What it DOES give: the submission window (which pages viewed/autosaved/updated
  and when), the client `ip`, and admin edit history
  (`\core\event\question_created|updated|deleted`, `course_module_created|
  updated|deleted`) — useful to answer "when did the question change / when did
  the student actually sit the quiz".
- Retention is short (a few months; on 2026-09-28 it spanned 07-16..09-28).

## Step 5 — question-type source review (rule out a server bug)
For multichoice: `/var/www/html/public/question/type/multichoice/question.php`,
class `qtype_multichoice_multi_question`:
- `get_expected_data()` → `choice<N>` PARAM_BOOL per option (one per `_order`
  position).
- `grade_response()` → sums `fraction` over non-empty `choiceN`, clamped [0,1].
- `summarise_response()` → text of truthy choices, `'; '`-joined.
**The server stores exactly what the form POSTs — there is no code path that
adds an unchecked option.** So a "ghost option" can only come from: (a)
client-side stale UI state / double-POST, (b) an autosaved edit that was
superseded (autosave steps interleave with manual ones — read ALL complete
steps in sequence, not just the last), (c) restored/rewritten attempt data
(Step 2 signals), (d) student misremembering, or (e) **stale page delivery by
the PWA service worker** — on this box `local/pwa/sw.js` is
stale-while-revalidate and caches ANY url-with-query-string, which includes
quiz attempt pages; on a flaky/mobile connection a stale copy of the question
page can be rendered with old checkbox state. (e) is a scoped, reversible
environment fix (exclude `/mod/quiz/` and `/question/` from the SW cache) —
unlike patching core question code mid-exam. Read the specific qtype file
(coderunner: `-precheck`/`-answer` data rows) before concluding "no code bug".

## Step 5a — "the system added an option": recorded vs display-only (2026-09-28 root cause)
A student reports an option appeared that they didn't pick. Before concluding a
server/data bug, classify WHERE the extra option lives:
1. **Read ALL `complete` steps in sequence** (not just the last). In this build
   every `complete` step stores all `choice0..choiceN` explicitly (0/1) +
   `-_try`, `-_rawfraction`.
2. **A `todo` step is a display/working state, NOT a submission.** The adaptive
   "Check your answer" flow re-renders an already-answered question after the
   student navigates away and back; that re-render can pre-fill a STALE selection
   (e.g. show `d` ticked) as a `todo` step. If the extra option appears ONLY in a
   `todo` step and NOT in any `complete` step, it never entered the graded answer —
   it's a client-side pre-fill artifact, not a recorded submission.
3. **The LAST `complete`/`gradedright` step is the authoritative answer.** A
   student "unclicking and re-checking" produces later `complete` steps that
   overwrite earlier ones.
4. **Always verify the grade impact** before concluding harm: the final step's
   `-_rawfraction` (1.0 = full) + `state` (`gradedright` = correct). On 2026-09-28
   the student's final step was `gradedright`/0.9999 = full marks, so NO retrieval
   was needed and the "false attempt" didn't exist.
5. **Check it's not systemic**: run the same per-try reconstruction for every
   student who saw that question (loop `question_attempts` by `questionid`, map
   each to its usage via `quiz_attempts.uniqueid`). If only one student shows the
   artifact, it's a transient client glitch, not a defect.

## Step 5b — "Can we fix this bug?" (remediation triage, 2026-09-28)
After a client-side re-render / pre-fill artifact is established, a "fix it"
request is a layered decision, not a single patch. Order by risk:
1. **Don't touch the grading engine.** The grade comes from the last submitted
   (`-_try`) response, never from a `todo` autosave — provably correct here.
   Patching it to "fix" a cosmetic display bug risks real scoring regressions.
2. **Don't patch core question/behaviour JS mid-exam window** for a
   non-reproducible, no-scoring-impact, single-student glitch. From the pod you
   cannot reproduce the client glitch (no browser, no logged-in student
   session), so a core patch would be untested exactly when it must not break
   anything. File an upstream ticket instead, with the per-try step dump as the
   repro bundle.
3. **Safe scoped fix: the PWA service worker.** `local/pwa/sw.js`
   (stale-while-revalidate, caches anything with a query string) can serve a
   STALE quiz-attempt page on flaky connections — a concrete aggravating factor
   for stale checkbox state. Excluding `/mod/quiz/` and `/question/` from the
   SW cache (always-network / no-store) is reversible, has no grading impact,
   and protects all students. This is the right "fix now" if any.
4. **Optional cosmetic record cleanup:** reset the question's later try noise
   (e.g. a student's 13:55 re-checks) only if the teacher asks; it changes
   nothing about the grade.
5. **Reply script for the student:** state (i) final recorded answer + its mark,
   (ii) the extra option was a display-only glitch that never entered the
   graded answer, (iii) no false attempt is counted — directly answering their
   "retrieve my false attempts" ask. Keep out of the email: question ids, step
   dumps, timestamps.

## Step 6 — report shape
1. Does the disputed question exist in this attempt? (set match/mismatch, on the
   `uniqueid`-resolved usage)
2. Stored selection: letters + raw `choiceN` flags + step timestamps + `_order`.
3. Logstore corroboration: activity window, pages, IP.
4. Code capability: what the qtype can/can't do to the stored set.
5. **Grade impact: final step `-_rawfraction` + `state`; was the student actually
   penalised?** (Often the answer is "no" — see Step 5a.)
6. Verdict + next action (e.g. teacher-confirmed manual override via the
   manual-grade path in `moodle-absent-zero-grade`).

## Tooling gotchas (this box)
- MCP `query` tool: parameter is **`query`** (not `sql`); ONE statement only
  (no `;`); rejects "CREATE"/"DELETE" substrings anywhere — **including in
  your aliases** (`AS created`, `AS qcreated` all trip it; `timecreated` does
  too). Use `AS tc` or drop the column.
- PHP CLI bootstrap MUST be `define('CLI_SCRIPT',true); define('MOODLE_INTERNAL',
  true); require('/var/www/html/public/config.php'); require_once('/var/www/
  html/public/lib/setup.php'); global $DB;` — omitting config.php or
  MOODLE_INTERNAL → silent exit 1, zero output. PHP stdout is often swallowed by
  the terminal wrapper → `fwrite` results to `/tmp/out.txt` and read that.
  Run: `cd /var/www/moodledata/.hermes && timeout 300 php -d display_errors=1 /tmp/x.php`.
- Full schema-trap bank: `moodle-php-cli-pitfalls` (esp. §8a/8b/11b + §12).

## Case files
- **references/lau-tsz-long-equiz4-2026-09-28.md** — "system added option d"
  claim on E-Quiz 4 Q3 (infinite loops) — RESOLVED: a transient client-side
  re-render, NOT a server bug and NOT a penalty (final step `gradedright`, full
  marks). The real usage is `quiz_attempts.uniqueid`; the first pass's "snapshot
  trap" was an `id`/`uniqueid` collision false alarm. Full per-try table + root cause.
