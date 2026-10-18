# This Moodle 5.2 fork — non-standard schema & flaky-DB notes (condensed)

Condensed from live debugging (2026-09-14). This Moodle 5.2.1 install deviates from upstream
Moodle column names in several core tables. **Always verify with
`mcp__moodle_db__describe_table` / information_schema before writing a query** — upstream
Moodle docs and the `moodle-db-access` skill's table map are partially wrong for this fork.

## Non-standard column names (differ from upstream Moodle)

| Table | This fork | Upstream (do NOT use here) |
|---|---|---|
| `mdl_quiz_attempts` | `sumgrades` | `sumgrade` |
| `mdl_quiz_attempts` | has `uniqueid` (the →question_usages link) | upstream links via `question_usages.quizattemptid` |
| `mdl_quiz_slots` | `quizid`, `slot`, `page`, `displaynumber`, `requireprevious`, `maxmark`, `quizgradeitemid` | upstream: `quiz`, `number`, `questionid` |
| `mdl_question_attempts` | `maxmark` | `maxgrade` |
| `mdl_question_attempt_steps` | `state` | upstream `event` |
| `mdl_question_usages` | only `id, contextid, component, preferredbehaviour` | upstream has `quizattemptid` (ABSENT here) |
| `mdl_quiz` | `attempts` (attempts-allowed) | `attemptsallowed` |

- `mdl_question_attempt_steps` columns: `id, questionattemptid, sequencenumber, state, fraction, timecreated, userid`. **No `timemodified`, no `event`.**
- `mdl_config` is **only** `id, name, value` (no `plugin` column) — plugin configs are in `mdl_config_plugins (plugin, name, value)`.

## Step-state machine (mdl_question_attempt_steps.state)

`todo` → … terminal states: `complete`, `gradedright`, `gradedwrong`, `submitted`, `gaveup`, `failed`.
For "did they answer this question": last non-`todo` state in {complete, gradedright, gradedwrong, submitted} = answered; {gaveup, failed} = gave up; only `todo` = not reached.

## The `get_records_sql` driver is flaky — concrete failure shapes

All observed as a **bare** `Error reading from database` (no detail) from the PHP bootstrap,
while the *same* data is fine through the MCP `moodle_db` tool (separate connection):

Fails (avoid):
- Any **nested subquery** in the WHERE/SELECT.
- `get_record()` / `get_field()` where `get_records()` on the same table works.
- Selecting or filtering `event` or `timemodified` on `mdl_question_attempt_steps` (nonexistent cols).
- `SELECT … FROM {quiz_slots}` in many shapes (try the MCP tool instead).
- Some `sumgrades`+`timefinish` combos without a timefinish predicate.

Works reliably:
- **Flat single-table or simple 2–3-table join** `get_records_sql` with an `IN (…)` list — *chunk the IN list to ~30 ids* on big tables (`mdl_question_attempt_steps` is ~3.5M rows; 30-id chunks worked, 136-id IN failed).
- `get_records()` / `count_records()` with hash conditions.

### Debugging recipe
1. Wrap each query in `try/catch` printing the label so you know exactly which one dies.
2. Bisect: same table with fewer columns, then fewer predicates, then `get_records` vs `get_records_sql`.
3. If a table's PHP query keeps failing but you just need a **read**, use the **MCP `moodle_db` query tool** (different connection, usually succeeds) — but note it caps at 100 rows and rejects SQL containing the substrings `DELETE`/`CREATE` (even inside a column name like `timecreated`/`userdeleted`), and `FROM_UNIXTIME` format args get stripped.
4. Never trust a flaky-tool result you'll report: cross-check a `count_records`/hash-API spot value first.

## Join chain: student → per-question state

`quiz_attempts.uniqueid` = `question_usages.id` → `question_attempts.questionusageid`
(`.slot`, `.questionid`, `.id`) → `question_attempt_steps.questionattemptid` (== `question_attempts.id`), `.state`.

## Cross-checks that resolved ambiguity this session
- `mdl_quiz.grade` (gradebook max, e.g. 80) ≠ the question-mark scale that `sumgrades` is on (e.g. 22). Authoritative quiz % = `mdl_grade_grades.finalgrade` for the quiz's `mdl_grade_items` row (already rescaled). Derive the true question max from one known-correct pair: `raw / (finalgrade / quiz.grade)`.
- CE-Quiz 1 (quiz 58) layout: slot 1 = "Information" (0 marks), slot 2 = first real question, 4 marked questions total (slots 2–5, 1 mark each).
