---
name: quiz-sampling-consequence
description: "Pipeline for quiz sampling-for-explanation consequences in cs1302a_26a. A student absent when sampled (whole quiz zero) or present but failed to explain one question (that question zeroed) — verify attempts, zero via manual grade with audit comment, recompute grades, send the user's short FINAL no-mitigation notice email. Use for 'mark zero', 'zero the absentees', 'mark question N as 0', 'failed to explain question X', or emailing students about such grade changes."
---

# Quiz sampling consequence (zero + final notice)

Class of work: after a lecture the instructor samples students to explain quiz
answers. Outcomes handled here:
- **Absent when sampled** → whole quiz zeroed.
- **Present but failed to explain Question N** → that one question zeroed.
Both end with a short factual notice email under the user's no-mitigation policy.

## The user's durable policy for these notices (stated 2026-10-07, overrides softer styles)
**NO** invitation to explain, **NO** request for evidence, **NO** open-hour /
after-lecture offer, **NO** makeup. The user's words: "There is simply no
resources to support mitigation." Do NOT draft the "come and explain" variant
even if another skill or an earlier email in /tmp suggests it. Also: no
AI-misuse / expulsion / learning-concern framing in these notices — no
accusation without decisive evidence; the heavier instruments (formal warning
with expulsion language, TSO-style conversation email) are separate things the
user commissions explicitly with their own template.

Approved email shape (short, factual, final):
```
Dear <first name>,

Today in class I sampled several students to explain their submissions on
<E-Quiz N>, and you were not present when you were asked.

Since no explanation was given, the mark for <E-Quiz N> (your recorded score
was <X>/<Y>) is set to 0. This decision is final; there is no makeup
opportunity for this quiz.

Regards,
Chung Chan
CS1302A Intro to Computer Programming
```
Single-question variant: line 2 = "…you were asked to explain Question N
(<question name>), but were not able to do so."; consequence = "the mark for
that question (<marks> marks) is set to 0." Keep the "final, no makeup" sentence.
Subject: `E-Quiz 4 — mark set to 0` (whole) / `E-Quiz 4 — Question 16 mark set to 0`.

## Procedure (verified 2026-10-07 on this build)
1. **Resolve + verify first** (MCP read-only): user id by name, attempt row
   (`mdl_quiz_attempts` by quiz+userid, state finished, pre sumgrades), and for
   single-question, the slot's question name (`mdl_question_attempts` +
   `mdl_question` by questionusageid). Numbering: **Question N = slot N+1**
   (slot 1 = "Information" description). Show the mapping before acting.
2. **Zero** with the PHP CLI recipe — see `references/zero-recipe.md` in this
   skill for the exact script pattern (whole-attempt and single-slot). The
   critical build facts are in `moodle-gradebook` →
   `references/quiz-manual-grade-override.md` (build-delta section): in this
   Moodle 5.x build `recompute_final_grade()` is PROTECTED (reflection) and
   reads `sumgrades` from the DB — so set `sumgrades = quba->get_total_mark()`
   and save the attempt row BEFORE recomputing, or you get per-question 0s with
   stale 100% aggregates.
   - Backup attempt+step data+grade rows to `/tmp/<quiz>_at<id>_pre.json` first.
   - Audit comment (kept in the attempt, visible in grading report):
     absent: `Mark set to 0: student was not present when sampled to explain the <Quiz> submission. See course email dated <date>.`
     single-Q: `Mark set to 0: failed to explain Question N (<name>) when sampled in class. See course email dated <date>.`
   - Verify via INDEPENDENT MCP read: sumgrades, quiz_grades, grade_grades
     raw/final all equal the expected value, plus `mangrwrong` + `-mark`/`-comment`
     step rows exist.
3. **After all zeros:** `grade_regrade_final_grades($courseid)`
   (`require_once lib/gradelib.php` in the CLI script) + `moosh -n cache-clear`.
4. **Emails:** present drafts → wait for explicit confirm → send per
   `email-student-group` (raw ESMTP, one private message, ~1s pacing, log
   `250 2.0.0 <queueid>` per recipient, report queue IDs).

## Pitfalls
- The desync trap (stale aggregates with correct per-question zeros) — if you
  ever see it, the fix is the same `sumgrades` refresh + recompute, not a
  second manual_grade pass (it no-ops on already-mangrwrong slots).
- `process_submitted_actions()` as an alternative: reads `$_POST` internally
  (a local `$post` array never assigned to `$_POST` = silent no-op), and its
  `-comment` field is `paramrawfiles` so plain-text comments are dropped. Use
  the `manual_grade()` API path for mark+comment.
- Double-zero guard: check for existing `-mark` steps (join via
  `question_attempt_steps.id`, NOT `question_attempts.id`) before applying.
- These notices are the user's approved final-word instrument; if a student
  later does show up and explain, that is a new user decision, not something
  the email promises.
