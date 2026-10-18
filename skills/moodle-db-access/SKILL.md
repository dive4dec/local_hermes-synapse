---
name: moodle-db-access
description: "Access Moodle database from Hermes agent — PHP bootstrap and PyMySQL bridge. Covers course listings, question bank queries, enrolment data, and grade lookups."
---

# Moodle Database Access

Access the Moodle database from within the Hermes agent environment.

## Triggers

- User asks to check courses, question banks, enrolments, grades, or any Moodle DB data
- User asks to list users, roles, groups, or course activities
- You need to look up any data stored in Moodle tables
- "check the question bank", "list all courses", "who is enrolled in X", "show me grades"

## Available tools

### moodle-bridge plugin (2 tools)

The `moodle-bridge` plugin provides exactly **2 tools** — no general-purpose DB query tool exists:

- **`moodle_get_my_courses`** — list courses the current user is enrolled in
- **`moodle_upload_file`** — upload a file to a course as a resource

There is **no `mcp__moodle_db__query` tool**. Do not attempt to call it.

### Primary method — PHP bootstrap

Boot the Moodle framework to get `$DB` access:

```php
<?php
define('CLI_SCRIPT', TRUE);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/check.php';
require_once('/var/www/html/config.php');

// Now $DB is available
$course = $DB->get_record('course', ['id' => 3]);
echo $course->fullname . PHP_EOL;
?>
```

Write the script to `/tmp/<name>.php` and run with `php /tmp/<name>.php 2>&1`.

### Which $DB methods work

| Method | Status |
|---|---|
| `$DB->get_record()` | ✅ Works |
| `$DB->get_records()` | ✅ Works |
| `$DB->get_field()` | ✅ Works |
| `$DB->get_records_sql()` | ❌ UNRELIABLE — fails with "Error reading from database", AND (worse) can silently return a WRONG/INCOMPLETE rowset with no error. On 2026-09-09 a join query for one user's groups returned 1 row when the user belonged to 3 groups, corrupting a report. NEVER trust it for data you will report to the user. |
| `$DB->insert_record()` / `update_record()` | ✅ Works |

**Use `get_record()` / `get_records()` with hash conditions instead of `get_records_sql()` — the SQL variant has a known issue in this environment.** For per-user membership (groups, role assignments, enrolments), loop with `get_records('table', ['userid' => $id])` — N calls is fine for a few hundred users, and it's the only way to be sure the result is complete. When you must use a multi-table SQL query, cross-check with a `count_records`/hash-API spot check on at least one entity before reporting.

### Fallback — raw mysqli (usually fails)

Raw `mysqli` connections **fail** from this pod (`Access denied for 'moodleuser'@'<pod_ip>'`). The moodle-bridge plugin uses PyMySQL with the same credentials and works because it connects from a different network namespace. The PHP bootstrap approach always works because it connects from the Moodle pod's authorized IP range.

**Do not use raw mysqli unless you have a specific reason — the PHP bootstrap is the reliable approach.**

## Key Moodle tables

| Table | Purpose |
|---|---|
| `mdl_course` | Courses (id, fullname, shortname, format, visible) |
| `mdl_user` | Users (id, firstname, lastname, email, auth) |
| `mdl_user_enrolments` | Enrolments (userid, enrolid, status) |
| `mdl_enrol` | Enrolment methods (courseid, enrol, status) |
| `mdl_role` | Roles (id, name, shortname, archetype) |
| `mdl_role_assignments` | Role assignments (userid, roleid, contextid) |
| `mdl_course_modules` | Course activities (course, module, instance, visible) |
| `mdl_grade_grades` | Student grades (userid, itemid, rawgrade, finalgrade) |
| `mdl_groups` | Groups (id, courseid, name) |
| `mdl_groups_members` | Group members (groupid, userid) |
| `mdl_context` | Contexts (id, contextlevel, instanceid, path, depth) — contextlevel 70 = course, 80 = block |
| `mdl_question` | Questions (id, qtype, name, questiontext, defaultmark) |
| `mdl_question_versions` | Question versions (questionid, questionbankentryid, version) |
| `mdl_question_bank_entries` | Question entries (id, **questioncategoryid** — NOT questionarea) |
| `mdl_question_categories` | Categories (id, name, contextid, parent) |
| `mdl_question_answers` | Answer options for multichoice/ordering/ddwtos |
| `mdl_quiz` | Quizzes (id, course, name, timeopen, timeclose) |
| `mdl_quiz_slots` | Quiz → slot rows (no questionid column; linked via question_references) |
| `mdl_quiz_sections` | Quiz sections (id, quizid, firstslot, heading, shufflequestions) |
| `mdl_question_references` | Links questions to contexts (component, questionarea, itemid, questionbankentryid, version) |
| `mdl_question_usages` | Question usages (id, contextid, component, preferredbehaviour) |
| `mdl_question_attempts` | Attempt records (questionusageid, slot, questionid, maxmark) |
| `mdl_forum` | Forums (id, course, name, type — 'news' = announcements) |
| `mdl_forum_discussions` | Forum discussions (id, forum, subject, userid, created) |
| `mdl_forum_posts` | Forum posts (id, discussion, userid, subject, message, created) |

## Common queries

### List all courses
```php
$courses = $DB->get_records('course');
```

### Find a course by shortname
```php
$course = $DB->get_record('course', ['shortname' => '<coursecode>']);
```

### List enrolled students in a course
```php
$enrols = $DB->get_records('enrol', ['courseid' => $courseid]);
$studentIds = [];
foreach ($enrols as $e) {
    $ues = $DB->get_records('user_enrolments', ['enrolid' => $e->id, 'status' => 0]);
    foreach ($ues as $ue) $studentIds[] = $ue->userid;
}
// Then fetch each user via $DB->get_record('user', ['id' => $uid])
```

### Check announcement forum discussions
```php
// Find the announcements forum
$forum = $DB->get_records_select('forum', 'course = ? AND type = ?', [$courseid, 'news']);
// Get discussions
$discs = $DB->get_records('forum_discussions', ['forum' => $forumId]);
// Get posts for each discussion
$posts = $DB->get_records('forum_posts', ['discussion' => $discId]);
```

## Pitfalls

- **`mcp__moodle_db__query` does not exist:** There is no general-purpose DB query tool. The moodle-bridge plugin only provides `moodle_get_my_courses` and `moodle_upload_file`.
- **`$DB->get_records_sql()` fails:** Use `get_record()` / `get_records()` with hash conditions instead.
- **No `pdo_mysql`:** PHP has `mysqli` but NOT `pdo_mysql`. Raw mysqli connections fail from this pod due to IP-based auth.
- **No `mariadb` CLI:** The `mariadb` or `mysql` command-line tools are not installed. Use PHP scripts.
- **No `moosh php-eval`:** moosh 1.27 does not have `php-eval`. Write a PHP file and run it.
- **CLI_SCRIPT must be TRUE (uppercase):** `define('CLI_SCRIPT', true)` (lowercase) causes a fatal. Use `TRUE` or `1`.
- **`mdl_question_bank_entries` uses `questioncategoryid`, NOT `questionarea`**.
- **`mdl_context` has `instanceid`, NOT `courseid`:** Use `WHERE contextlevel = 70 AND instanceid = <courseid>`. Moodle 5.x uses contextlevel=70 for course contexts.
- **`mdl_quiz_slots` has NO `questionid` column:** Linked via `mdl_question_references` (component='mod_quiz', questionarea='slots', itemid=slot_id).
- **Course question categories live at contextlevel=70 (course) in Moodle 5.x, NOT 50.**
- **`mdl_forum_discussions.subject` doesn't exist:** The discussion title is stored in the `name` column, NOT `subject`. Fetching `subject` returns `NULL`.
- **Empty quiz slots ≠ empty quiz:** A quiz can have 0 question_references yet still have valid student attempts.
- **Quiz group mode lives in `course_modules`, not `quiz`:** The `groupmode` and `groupingid` fields are on the `course_modules` record, not the `quiz` table. The quiz edit form reads from `$this->_cm` (the CM record). Setting them on the `quiz` table has no effect. Use `$DB->set_field('course_modules', 'groupmode', 1, ['id' => $cmid])` to change group mode.
- **`grouping_groups` table is actually `groupings_groups`:** The join table between groupings and groups is `groupings_groups` (plural on both sides), not `grouping_groups`. Using the wrong name causes "Table does not exist".
- **ALWAYS run `moosh -n cache-clear` after any DB change:** After inserting/deleting/updating records (groups, overrides, course_modules, etc.), always run `cd <webroot> && moosh -n cache-clear` so changes appear in the UI. The user gets very frustrated having to remind you.
