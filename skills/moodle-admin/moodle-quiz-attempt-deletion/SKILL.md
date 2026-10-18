---
name: moodle-quiz-attempt-deletion
description: "Delete quiz attempts (all, or per-user) on this Moodle 5.x safely. An attempt is NOT one row — it fans out across ~6 Question-Engine tables plus gradebook/completion/stats. Covers the safe delete API, the full cascade to clean, a count-before/count-after verification recipe, and what to KEEP (SEB settings, overrides, logstore). Use for 'delete all attempts of quiz X', 'wipe quiz Y history', 'reset attempts'."
---

# Moodle Quiz Attempt Deletion

Deleting quiz attempts on this site (Moodle 5.x, Question Engine 3.x). The trap: **an attempt is
not a single row**. Each `mdl_quiz_attempts` row fans out into a Question-Engine usage and
per-question attempt/step/data rows, plus gradebook rows, completion rows, and cached
statistics. Deleting only `mdl_quiz_attempts` (or a naive SQL) orphans the Question-Engine rows
and leaves stale grades. Use the purpose-built API and clean the full cascade.

## Triggers

- "delete all attempts of quiz X" / "wipe <quiz> history" / "reset attempts"
- "delete user Y's attempts on quiz Z"
- Any request to clear quiz submission data (before re-running a test quiz, e.g. "Quiz for testing SEB")

## ⚠️ First: confirm WHICH quiz

Activity names are often **not unique** across a multi-semester site. Always disambiguate by
**quiz id** before touching anything, and show the user both id + course:

```sql
SELECT q.id AS quizid, q.name, q.course AS courseid, c.shortname,
  (SELECT cm.id FROM mdl_course_modules cm
     WHERE cm.instance = q.id
       AND cm.module = (SELECT id FROM mdl_modules WHERE name = 'quiz')) AS cmid
FROM mdl_quiz q JOIN mdl_course c ON c.id = q.course
WHERE q.name = '<quiz name>';
```
(Quiz module numeric id = **17** on this site; `cm.module` is a numeric FK, not the name — see
`moodle-mcp-db-query` pitfall 11.) If multiple rows come back, list all and ask which to run.

## The safe delete API (do NOT hand-SQL the Question Engine)

`mod/quiz/lib.php` provides two cascade-safe functions:

- **All attempts of a quiz:** `quiz_delete_all_attempts($quizobj)` (line ~338). It calls
  `question_engine::delete_questions_usage_by_activities(new qubaids_for_quiz($quiz->id))`
  (which removes the Question-Engine usages + question_attempts + steps + step_data for the
  whole quiz) then `delete_records('quiz_attempts')` and `delete_records('quiz_grades')`.
- **One user's attempts:** `quiz_delete_user_attempts($quizobj, $userobj)` (line ~352) —
  scoped to that user's attempts via `qubaids_for_users_attempts`.

The **Course Reset** UI (`quiz_reset_userdata()`, lib.php ~1473) is the same cascade plus
optional overrides/gradebook removal — but it operates **per-course** (all quizzes in the
course), so it's too broad when you only want one quiz. Use the two functions above for a
single quiz.

The API covers attempts + Question Engine + `mdl_quiz_grades`. It does **NOT** remove:
gradebook `mdl_grade_grades` rows, completion rows, or `mdl_quiz_statistics`. Clean those too.

## The full per-quiz cascade to clean (verified table set, Moodle 5.x)

For quiz id `Q`, cmid `C`:

| Table | Filter | Notes |
|---|---|---|
| `mdl_quiz_attempts` | `quiz = Q` | includes `preview = 1` (staff preview) rows too |
| `mdl_quiz_grades` | `quiz = Q` | handled by the API |
| Question Engine: `mdl_question_usages` (+ `mdl_question_attempts`, `mdl_question_attempt_steps`, `mdl_question_attempt_step_data`) | via the usage for context `C` (level **70**, `instanceid = C`, `component = 'mod_quiz'`) | handled by the API; **do NOT** hand-delete |
| `mdl_grade_grades` | `itemid = <grade item id for Q>` | resolve: `SELECT id FROM mdl_grade_items WHERE iteminstance = Q` (the quiz's grade item; `itemmodule = 'quiz'`). `mdl_grade_grades` has **no `courseid`** — scope via the item |
| `mdl_grade_grades_history` | `itemid = <same>` | keep/audit trail of grade changes |
| `mdl_course_modules_completion` | `coursemoduleid = C` | FK is `coursemoduleid` (NOT `coursemodule`) |
| `mdl_quiz_statistics` | the quiz's stats rows | see note below — keyed by `hashcode`, not a `quiz` column |

**Question-Engine join shape (verified):** `mdl_question_usages.id` == `mdl_quiz_attempts.uniqueid`
(one usage per attempt on this site). `mdl_question_attempts.questionusageid` → usage;
`mdl_question_attempt_steps.questionattemptid` → question attempt;
`mdl_question_attempt_step_data.attemptstepid` → step (column is `attemptstepid`, NOT `stepid`).

**`mdl_quiz_statistics` quirk:** columns are `id, hashcode, whichattempts, timemodified,
firstattemptscount, …, allattemptsavg, median, …` — there is **no `quiz` column**. To delete
"this quiz's" stats you need the `hashcode` for the quiz (compute as the site does in
`mod/quiz/locallib.php` or delete by matching `allattemptscount`/`whichattempts` to the quiz's
attempt volume). **Simplest safe move: leave `mdl_quiz_statistics` alone** — it is a
recomputable cache; the quiz's "Statistics" tab will recompute on demand. Only delete it if the
user wants a fully cold cache.

## What to KEEP (do not delete as part of "delete attempts")

- **`mdl_quizaccess_seb_quizsettings`** (`quizid = Q`) — the quiz's SEB template/config
  assignment. These are **settings**, not attempts. Deleting them breaks SEB config.
- **`mdl_quiz_overrides`** (`quiz = Q`) — per-user/per-group time, timelimit, attempt, password
  overrides. Also settings. Keep unless the user explicitly wants them wiped.
- **`mdl_logstore_standard_log`** — audit trail. Keep.
- The **quiz activity itself** (`mdl_quiz` row, `mdl_course_modules` row, sections, slots,
  questions in the bank) — "delete attempts" ≠ "delete the quiz". Confirm scope if ambiguous.

## Verification recipe (count-before / count-after)

Always report the blast radius **before** deleting, then confirm **after**:

```php
// BEFORE (also gives the numbers to show the user)
$att  = $DB->count_records('quiz_attempts', ['quiz' => $Q]);
$usages = $DB->get_records('question_usages', ['contextid' => $ctxid, 'component' => 'mod_quiz']); // ctxid = level-70 context for cmid C
$qat  = 0; foreach ($usages as $u) $qat += $DB->count_records('question_attempts', ['questionusageid' => $u->id]);
$gitem = $DB->get_record('grade_items', ['iteminstance' => $Q]);
$grades = $gitem ? $DB->count_records('grade_grades', ['itemid' => $gitem->id]) : 0;
$compl = $DB->count_records('course_modules_completion', ['coursemoduleid' => $C]);
// AFTER: all of the above should be 0.
```

Then **purge caches** so the UI reflects it: `cd <webroot> && moosh -n cache-clear`
(quiz + coursemodinfo). Re-run the counts and confirm zero. Report the before→after numbers to
the user.

## PHP bootstrap + gotchas

- Bootstrap exactly per `moodle-db-access` (CLI_SCRIPT uppercase, `$_SERVER['REQUEST_URI']`,
  `require_once config.php`). The delete functions live in `mod/quiz/lib.php` — `require_once`
  `$CFG->dirroot.'/mod/quiz/locallib.php'` first (they reference `qubaids_*` from locallib).
- The API wants **objects**: `$quiz = new quiz($Q, $cm)` or fetch `get_record('quiz', ['id'=>$Q])`
  and ensure it carries a `cmid` (`quiz_delete_user_attempts` / per-attempt paths resolve a CM).
  Set `$quizobj->cmid = $C` if it's missing.
- `$DB->get_records_sql()` on the Question-Engine/logstore tables is unreliable in this env —
  use the hash-API (`get_records`/`count_records`) loop, or read-only `mcp__moodle_db__query`
  for the counts, for accuracy (see `moodle-db-access` + `moodle-mcp-db-query`).
- **Preview attempts** (`preview = 1`) are included in `quiz_delete_all_attempts`. If the user
  only wants *student* attempts gone, delete per-user with `preview = 0` instead, or filter.

## See also

- `moodle-db-access` — bootstrap + which `$DB` methods are reliable
- `moodle-mcp-db-query` — read-only count queries, keyword-filter gotchas
- `moodle-seb-quiz-access` — the SEB settings you must NOT delete
- `moodle-cache-purge` — post-change cache clearing
