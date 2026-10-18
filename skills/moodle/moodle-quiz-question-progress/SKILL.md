---
name: moodle-quiz-question-progress
description: "Determine per-question (per-slot) completion for students on a Moodle quiz — who answered / gave up / never reached a specific question. Used live during a lab quiz session to spot stuck/skipped students, or post-hoc for a final report. Class-level sibling of moodle-equiz-student-status (which is attempt-level pass/fail/enrolment)."
---

# Moodle Quiz Question (Slot) Progress

Answer: for a given quiz and a given question slot, which students **answered** it, which **gave up** (reached it but abandoned it with no answer), and which **never reached** it (still on an earlier question / mid-attempt).

This is a **question-level** status — distinct from attempt-level cohorts (who passed / failed / never attempted / not enrolled), which live in the sibling skill `moodle-equiz-student-status`.

## Triggers

- "who has not completed Question N / slot N in <quiz>"
- "which students are stuck on / skipped question X" (during a running lab quiz)
- "per-question progress on the CE-Quiz", "who gave up on question 1"
- Instructor monitoring a live CE-Quiz session in real time

## Inputs

- `quizid` (int) — the quiz's `mdl_quiz.id` (e.g. CE-Quiz 1 = 58 in cs1302a_26a).
- `slot` (int) — the **slot number** of the question. Slot 1 is often a 0-mark "Information" placeholder; the first *real* question is usually slot 2. Map slots to question names first (see below) so you confirm you're reading the right question.
- `courseid` (int, default 3) — for lab/group enrichment.

Run: `php <skill>/scripts/question_progress.php <quizid> <slot> [courseid]`

If the script runs, present its three lists (answered / gave up / not reached) and STOP. Only read on to understand/repair it.

## Environment

Moodle webroot `/var/www/html/public`; run as www-data:
```
cd /var/www/moodledata/.hermes && php /tmp/script.php
```
Bootstrap with `define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true); require config.php; require lib/setup.php; global $DB;`.

## The technique (verified against this Moodle 5.2 fork, 2026-09-14)

The join chain to get from a student to their per-question state:

```
mdl_quiz_attempts (quiz, preview=0)
   .id, .userid, .uniqueid, .timefinish
        │  uniqueid
        ▼
mdl_question_usages  (id == quiz_attempts.uniqueid)
        │  questionusageid
        ▼
mdl_question_attempts  (.questionusageid, .slot, .questionid, .id)
        │  .id  (== questionattemptid)
        ▼
mdl_question_attempt_steps  (.questionattemptid, .sequencenumber, .state)
```

1. **Attempts** — one flat query: `SELECT id, userid, uniqueid, timefinish FROM {quiz_attempts} WHERE quiz = ? AND preview = 0`. Build `uniqueid → userid` and submitted (timefinish>0) vs in-progress maps.
2. **Slot's question attempts** — `SELECT id, questionusageid, questionid FROM {question_attempts} WHERE slot = ? AND questionusageid IN (<uniqueids>)`. The `questionid` (same for every attempt of a fixed quiz) names the question: `get_field('question','name',['id'=>$qid])`.
3. **States** — for those question-attempt ids (chunk the IN list to ~30), `SELECT questionattemptid, sequencenumber, state FROM {question_attempt_steps} WHERE questionattemptid IN (...) ORDER BY questionattemptid, sequencenumber`. **The column is `state`, NOT `event`.**
4. **Classify** the *last non-`todo`* state per question-attempt (a student with several attempts: best case wins — answered > gaveup > notreached):
   - **answered**: terminal state in `complete`, `gradedright`, `gradedwrong`, `submitted`
   - **gave up**: terminal state in `gaveup`, `failed`
   - **not reached**: no terminal state yet (only `todo` steps)
5. **Enrich** with `mdl_user` + lab/project groups via `mdl_groups_members` → `mdl_groups` (courseid-scoped).

## CRITICAL: this is a LIVE snapshot when the quiz is running

CE-Quizzes open per lab group with a 45-min limit. While a group is mid-session, "not reached" / "gave up" students are **mostly just still working** — not genuinely stuck. Always:
- State the counts as of the timestamp.
- Flag every in-progress student with `[quiz still open]`.
- Offer to re-run later (or offer a one-shot ping when in-progress hits 0) before treating the list as a final "failed this question" result.
- A student who *submitted the whole quiz* but has no terminal state on this slot is a real "completed the quiz but skipped/failed this question" — the strongest signal; separate them from the merely-still-open ones when it matters.

## Output conventions

- Print the slot→question mapping first (confirms the right question).
- Headline counts: started / answered / gave up / not reached + submitted vs in-progress.
- Then the three lists (name | email | groups | `[quiz still open]` tag).
- Exclude/tag test accounts (`helpers` group, `ltitest`, `@example.com`) rather than silently dropping them.
- Read-only — no `moosh -n cache-clear` needed.

## Pitfalls

- **Multi-user `IN (…)` over `mdl_logstore_standard_log` can return stale rows silently** (relevant when enriching with live liveness/IP): 2026-09-15 a 3-user IN-list query returned "latest event" rows ~45 min stale while the identical single-user queries were fresh. Query one user at a time for live status you'll report; spot-check one student individually.
- **Same-day follow-up questions are cheap**: once the technique works for slot N, slots N+1… are the same script with `$slot` changed (this session: Q1=slot2, Q2=slot3, Q3=slot4 of CE-Quiz 1). Reuse the working script instead of re-deriving.
- **`mdl_question_attempt_steps` uses `state` (todo/complete/gradedright/gradedwrong/gaveup/submitted/failed), NOT `event`.** Selecting/filtering on `event` fails on this fork. Also `timemodified` is absent — see the schema reference.
- **Slot ≠ question number.** Slot 1 is commonly a 0-mark placeholder. Confirm the question name before reporting.
- **`get_records_sql` is flaky on this driver** — it fails with a bare "Error reading from database" on nested subqueries and some column combos. Keep every query flat (single table or a simple 2–3 table join, no subqueries) and chunk big IN lists. See `references/fork-schema-and-driver-quirks.md`.
- **`get_records_sql` keys results by the FIRST selected column; duplicate keys OVERWRITE.** Selecting `questionattemptid` first collapses each question's steps to one row. Always `SELECT id, questionattemptid, …` (unique pk first). (Verified 2026-09-15; details in the sibling `moodle-quiz-integrity-audit` skill's `references/php-db-gotchas.md`.)
- **`usort()` reindexes to 0,1,2… on this PHP build** — it does not preserve array keys. If you need uid-keyed lookups after sorting, sort a separate `array_keys()` copy and fetch values by key.
- **State nuance (adaptive behaviour):** a correct answer shows `complete` (student clicked Check) followed by `gradedright`; an answer graded right only at final submit shows `gradedright` with NO preceding `complete`. Both count as "answered" here, but the distinction is the core signal for the integrity audit — see `moodle-quiz-integrity-audit`.
- **Do NOT compute this from grades.** Question-level completion must come from `question_attempt_steps` states — a question can be skipped (0 marks, quiz still submitted) and never show up in any grade.
- Multi-attempt quizzes: a student may have several `question_attempts` for the same slot (one per quiz attempt). Classify by best case.

## Files

- `scripts/question_progress.php` — runnable: `php question_progress.php <quizid> <slot> [courseid]`.
- `references/fork-schema-and-driver-quirks.md` — this Moodle 5.2 fork's non-standard column names + the flaky-`get_records_sql` shapes (condensed knowledge bank).
