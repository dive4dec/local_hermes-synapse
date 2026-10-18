---
name: moodle-troubleshooting
description: "Diagnose Moodle access failures and user issues via mdl_logstore_standard_log, enrollment checks, and quiz access rules (SEB, passwords, time windows)."
---

# Moodle Troubleshooting

Diagnose why a user can't access a quiz, why an LTI launch fails, or why access is blocked.

## Triggers

- "user can't access quiz"
- "quiz failed", "access denied", "prevented"
- SEB / Safe Exam Browser issues
- "why was the user blocked"
- Any quiz access or enrollment mystery
- "copy quiz settings", "make this quiz match that one"
- "fix quiz settings", "rename quizzes", "update course content"

## Step 1: Find the RIGHT user record

**Pitfall: Duplicate usernames.** A name like "Adam LTITEST" may exist as multiple user records. Always disambiguate:

```php
$users = $DB->get_records_select('user', "firstname = 'Adam' AND lastname = 'LTITEST'", [], 0, 'id, lastaccess, auth');
```

Pick the one with the **most recent `lastaccess`** — that's the active account. The stale one may have no enrollment and misleads diagnosis.

## Step 2: Check the activity log

The `mdl_logstore_standard_log` table is the single most useful source. The `other` column contains **JSON** with event-specific details — including the exact reason access was denied:

```php
$logs = $DB->get_records('logstore_standard_log', ['userid' => $userid, 'courseid' => $courseid], 'id DESC', '*', 0, 20);
foreach ($logs as $log) {
    echo "{$log->eventname} | action={$log->action} | objectid={$log->objectid} | other={$log->other}\n";
}
```

Key fields:
- `eventname` — fully qualified event class, e.g. `\quizaccess_seb\event\access_prevented`
- `action` — `prevented`, `attempted`, `submitted`, etc.
- `objecttable` / `objectid` — identifies the quiz, assignment, etc.
- `other` — **JSON blob** with the real reason (config key mismatch, password wrong, time not open)
- `contextinstanceid` — the `cmid` (course module instance) for the activity
- `ip` — **populated** in this installation (Moodle 5.x event log). Use it for IP-based checks (e.g. campus vs external) — no HTTP access-log report needed. Filter quiz events by `component = 'mod_quiz'`.

**Pitfalls:**
- **Filter by `component`, NOT `module`** — this table has a `component` column and no `module` column. `['module'=>'quiz']` in `get_records()` throws `Error reading from database`.
- **`$DB->get_table_columns()` does not exist** in this environment — use `$DB->get_columns('logstore_standard_log')` (returns objects with `->name`).
- **`timecreated`, not `timecreate`** — the timestamp column is named `timecreated`.

## Common access failure patterns

### SEB (Safe Exam Browser) — "Invalid SEB config key"

- Event: `\quizaccess_seb\event\access_prevented`
- `other` JSON contains: `{"reason":"Invalid SEB config key","savedconfigkey":"...","receivedconfigkey":null,...}`
- **Cause**: Student's SEB client has stale config that doesn't match Moodle's stored hash
- **Fix**: Student must re-download the `.seb` config file from the quiz page

### Quiz password
- Event: `\mod_quiz\event\access_prevented`
- `other` JSON: `{"reason":"Quiz password required",...}`
- **Fix**: Student needs the quiz password

### Time open/close
- Event: `\mod_quiz\event\access_prevented`
- `other` JSON: `{"reason":"Quiz has not opened yet",...}`
- **Fix**: Wait for `timeopen` or check group overrides

### "User X changed their email / profile" when it should be locked
- **LTI-provisioned users bypass the Prohibit.** The LTI 1.3 auth plugin (`auth/lti/auth.php` `update_user_account()`, called on **every launch**) force-writes email from the launch JWT as **system actor 0** (`user_updated` with `userid=0`), no capability check. A `moodle/user:editownprofile` Prohibit does NOT stop this.
- Diagnosis order: (1) verify the Prohibit via `has_capability('moodle/user:editownprofile', \context_user::instance($uid), $user, false)` in the PHP bootstrap — do NOT conclude "lock missing" from an empty `mdl_role_capabilities` row for bare `user/editownprofile` (the stored string has the `moodle/user:` prefix; bare string matches 0 rows); (2) confirm no `user_updated` with the student as **actor** (proves no self-edit); (3) a system-actor (`userid=0`) `user_updated` right after an LTI launch = the sync, not a person.
- **Fix is platform-side** (correct the email on the LTI tool) or patching `auth/lti` to stop overwriting email on existing accounts. Full worked case: `moodle-mcp-db-query` → `references/logstore-user-field-audit.md`.

## Step 3: Check activity-level access restrictions

Three layers can block access to a quiz (check ALL before concluding):

1. **`groupmode`/`groupingid`** on `mdl_course_modules` — `groupmode=1` + non-zero `groupingid` means only group members can access
2. **`availability` JSON** on `mdl_course_modules` — a value like `{"op":"&","c":[{"type":"grouping","id":5}]}` restricts access to members of that grouping, EVEN IF `groupmode=0`. This is independent of groupmode. Clear with `SET availability=NULL`.
3. **Quiz-level settings** — `timeopen`/`timeclose`, `password`, SEB config, overrides

```php
$cm = $DB->get_record('course_modules', ['id' => $cmid]);
echo "groupmode={$cm->groupmode}, groupingid={$cm->groupingid}\n";
echo "availability=" . ($cm->availability ?? 'NULL') . "\n";
```

## Step 4: Verify enrollment

```php
$enrols = $DB->get_records('enrol', ['courseid' => $courseid]);
foreach ($enrols as $en) {
    $ues = $DB->get_records('user_enrolments', ['enrolid' => $en->id, 'userid' => $userid, 'status' => 0]);
    if ($ues) { echo "ENROLLED via {$en->enrol}\n"; }
}
```

No enrollment → no access, regardless of quiz settings.

## Common quiz settings pitfalls

- **Compare ALL `review*` fields** — there are more than the commonly-checked `reviewattempt`/`reviewcorrectness`/`reviewgeneralfeedback`. Fields like `reviewmaxmarks`, `reviewmarks`, `reviewrightanswer`, and `reviewspecificfeedback` are often missed.
- **Never copy `timeopen`/`timeclose` timestamps blindly** from old quizzes — they will be stale dates from a previous semester. Set to `0` (always open) unless specific times are needed.
- **Always purge cache** after any DB change before telling the user it's done: `cd /var/www/html/public && moosh -n cache-clear`.
- **`$DB->get_records('quiz_overrides', ...)` can fail** with "Error reading from database" in CLI bootstrap. Workaround: fetch all with `get_records('quiz_overrides')` (no filter) and filter in PHP.

## Course content management

When bulk-renaming or updating course content (labels, quiz titles, contact info):

1. Find the records first (iterate `course_modules` + the specific mod table).
2. Apply changes via `$DB->set_field()` or `$DB->update_record()`.
3. **Always purge cache** afterward — applies to ALL DB changes, not just structural ones.
4. Use `trim(strip_tags($label->intro))` to inspect label content without formatting noise.

## Lab/lecture schedule reference

Lab and lecture section assignments are stored in the Obsidian vault at `/var/www/moodledata/.hermes/obsidian-vault/CS1302A.Weekly.Lab.Schedule.md`. Always consult this file when updating course Contact labels or CE-Quiz group overrides — it is the source of truth for section-to-lecturer mapping.

## PHP bootstrap

```php
<?php
define('CLI_SCRIPT', TRUE);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/check.php';
require_once('/var/www/html/config.php');
// $DB is now available
?>
```

Write to `/tmp/<name>.php` and run `php /tmp/<name>.php 2>&1`.

## See also

- `moodle-db-access` — general DB query patterns and table reference
- `moodle-cequiz-management` — CE-Quiz timing and group overrides
