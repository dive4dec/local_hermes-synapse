# Moodle 5.x Quiz Schema (Direct DB Access)

**Database**: credentials are stored in Moodle's `config.php` at `/var/www/html/config.php` — never hardcode them here.

Extract connection info at runtime:
```bash
cd /var/www/html && php -r '
define("CLI_SCRIPT", true);
require_once("config.php");
printf("host=%s db=%s user=%s\n", $CFG->dbhost, $CFG->dbname, $CFG->dbuser);
'
```

For interactive access, pipe the credentials from config.php:
```bash
cd /var/www/html && mysql $(php -r '
define("CLI_SCRIPT", true);
require_once("config.php");
printf("-h %s -u %s -p%s %s", $CFG->dbhost, $CFG->dbuser, $CFG->dbpass, $CFG->dbname);
')
```

## Key schema changes from older Moodle versions

- `mdl_quiz_attempts.quizid` → renamed to `mdl_quiz_attempts.quiz`
- `mdl_quiz_questions` table is **GONE**
- `mdl_quiz_slots` no longer has `questionid`/`questionname` columns
- Question linkage: `mdl_quiz_slots` → `mdl_question_references` → `mdl_question_bank_entries` → `mdl_question_versions` → `mdl_question`

## Core tables for quiz attempt data

### mdl_quiz_attempts
| Column | Type | Notes |
|---|---|---|
| id | bigint | Primary key |
| quiz | bigint | FK to mdl_quiz.id (was `quizid` in older versions) |
| userid | bigint | FK to mdl_user.id |
| attempt | mediumint | Attempt number for this user |
| uniqueid | bigint | **Maps to mdl_question_attempts.questionusageid** |
| state | varchar(16) | 'finished', 'inprogress', etc. |
| preview | smallint | 0 = real attempt, 1 = preview |
| sumgrades | decimal(10,5) | Total score |
| timestart | bigint | Unix timestamp |
| timefinish | bigint | Unix timestamp |

### mdl_question_attempts
| Column | Type | Notes |
|---|---|---|
| id | bigint | Primary key |
| questionusageid | bigint | **Maps to mdl_quiz_attempts.uniqueid** |
| slot | bigint | Question slot number |
| questionid | bigint | FK to mdl_question.id |
| maxmark | decimal(12,7) | Max points for this question |
| responsesummary | longtext | Student's answer text |
| rightanswer | longtext | Correct answer text |

### mdl_question_attempt_steps
| Column | Type | Notes |
|---|---|---|
| id | bigint | Primary key |
| questionattemptid | bigint | FK to mdl_question_attempts.id |
| sequencenumber | int | Step order within the attempt |
| fraction | decimal | Score fraction (0.0-1.0) for this step |
| state | varchar | 'gradedright', 'gradedwrong', etc. |

### mdl_question
| Column | Type | Notes |
|---|---|---|
| id | bigint | Primary key |
| name | varchar | Question title/name |

## Query patterns

### Find quiz by name in a course
```sql
SELECT q.id, q.name FROM mdl_quiz q
JOIN mdl_course c ON q.course = c.id
WHERE c.shortname = 'cs2310_25a' AND q.name LIKE '%iRAT1%';
```

### Get finished attempts with scores
```sql
SELECT ua.id, ua.userid, ua.uniqueid, ua.sumgrades,
       u.idnumber, u.firstname, u.lastname, u.email,
       FROM_UNIXTIME(ua.timestart) AS start_time
FROM mdl_quiz_attempts ua
JOIN mdl_user u ON u.id = ua.userid
WHERE ua.quiz = <QUIZ_ID> AND ua.state = 'finished' AND ua.preview = 0
ORDER BY ua.sumgrades DESC;
```

### Get per-question data for an attempt
```sql
-- Get the uniqueid from the quiz attempt first
SELECT uniqueid FROM mdl_quiz_attempts WHERE id = <ATTEMPT_ID>;

-- Then query question attempts using that uniqueid as questionusageid
SELECT qa.slot, qa.questionid, qa.maxmark, qa.responsesummary,
       q.name AS question_name
FROM mdl_question_attempts qa
JOIN mdl_question q ON q.id = qa.questionid
WHERE qa.questionusageid = <UNIQUEID>
ORDER BY qa.slot;
```

### Get final fraction per question (last step)
```sql
SELECT qa.slot, qa.questionid, qa.maxmark,
       qas.fraction, qas.state
FROM mdl_question_attempts qa
JOIN mdl_question_attempt_steps qas ON qas.questionattemptid = qa.id
WHERE qa.questionusageid = <UNIQUEID>
ORDER BY qa.slot, qas.sequencenumber DESC;
-- Deduplicate in application code: keep only first row per slot (highest sequencenumber)
```

### Get question names for a quiz (from any attempt)
```sql
SELECT DISTINCT qa.slot, qa.questionid, q.name
FROM mdl_question_attempts qa
JOIN mdl_question q ON q.id = qa.questionid
WHERE qa.questionusageid = <ANY_UNIQUEID_FROM_THIS_QUIZ>
ORDER BY qa.slot;
```

## Pitfalls

- **Column name `quiz` not `quizid`**: Moodle 5.x renamed the FK column in `mdl_quiz_attempts`.
- **`questionusageid` = `uniqueid`**: The link between quiz attempts and question attempts is `mdl_quiz_attempts.uniqueid` → `mdl_question_attempts.questionusageid`.
- **Multiple steps per question**: A single question attempt can have multiple steps (e.g., multiple submissions). Always take the step with the highest `sequencenumber` for the final grade.
- **`responsesummary` contains newlines and commas**: When exporting to CSV, sanitize these fields (replace newlines with spaces, commas with semicolons).
- **`mdl_quiz_slots` is sparse**: It only has `id`, `slot`, `quizid`, `page`, `displaynumber`, `maxmark` — no direct question reference. Use `mdl_question_references` if you need slot→question mapping without an existing attempt.
