---
name: moodle-lti-management
description: "Manage Moodle LTI activities: inspect custom parameters, map to notebook links in labels, fix URL paths, and duplicate activities. Covers JupyterHub integration and LTI parameter structure."
---

# Moodle LTI Activity Management

Class-level skill for working with LTI (Learning Tools Interoperability) activities in Moodle, particularly JupyterHub-integrated courses where LTI activities launch notebooks.

## Triggers

- User asks to check or fix LTI custom parameters
- User wants to verify LTI activities point to the correct notebook URLs
- User duplicates an LTI activity and it fails or has wrong parameters
- "LTI", "JupyterHub", "notebook link", "custom parameters", "instructorcustomparameters"

## Finding LTI activities

LTI records live in `mdl_lti`. The `instructorcustomparameters` field is the critical parameter that controls which notebook launches.

### Query all LTI activities in a course

```php
<?php
define('CLI_SCRIPT', TRUE);
require_once('config.php');

$ltis = $DB->get_records('lti');
foreach($ltis as $lti) {
    echo "id:{$lti->id} name:{$lti->name}\n";
    if ($lti->instructorcustomparameters) {
        echo "  custom: {$lti->instructorcustomparameters}\n";
    }
}
```

### LTI custom parameter structure

The `instructorcustomparameters` field uses this format:
```
next=../user-redirect/git-pull?repo=https://github.com/org/repo&urlpath=lab/tree/course_name/LectureN/Notebook_Name.ipynb
```

Key fields:
- `next` — relative path to JupyterHub's git-pull redirect (starts with `../user-redirect/git-pull`)
- `repo` — GitHub repository URL
- `urlpath` — path within the repo to the notebook, typically `lab/tree/<course>/<lecture>/<notebook>.ipynb`

## Mapping LTI activities to label notebook links

Lecture labels often contain HTML links to the same notebooks. To verify LTI activities match:

1. Find the label (in `mdl_label`) containing the lecture section
2. Extract the `href` from anchor tags in the label's `intro` field
3. Decode the nested URL parameters: Canvas wrapper → JupyterHub LTI launch → git-pull with `custom_next`
4. Compare the decoded `repo` and `urlpath` with the LTI's `instructorcustomparameters`

### Decoding a label's notebook link

The label URL is typically:
```
https://canvas.cityu.edu.hk/courses/XXX/external_tools/retrieve?display=borderless&url=<encoded_jupyterhub_lti_launch_url>
```

Decode step by step:
1. Parse the outer Canvas URL — get the `url` parameter
2. Decode the `url` parameter — it's a JupyterHub LTI launch URL with `custom_next`
3. Parse `custom_next` — it's the git-pull URL with `repo` and `urlpath`
4. Compare `repo` and `urlpath` with the LTI activity's `instructorcustomparameters`

## Updating LTI custom parameters

Use `moosh php-eval` or a PHP script with `CLI_SCRIPT`:

```php
$lti = $DB->get_record('lti', ['id' => $lti_id]);
$lti->instructorcustomparameters = 'next=../user-redirect/git-pull?repo=https://github.com/dive4dec/cs1302a_26a&urlpath=lab/tree/cs1302a_26a/Lecture2/Values_and_Variables.ipynb';
$DB->update_record('lti', $lti);
```

After updating, verify the change by re-reading the record.

## Creating LTI activities

When a lecture label has a notebook link but no corresponding LTI activity, create one manually. Always decode the notebook URL from the label first (see "Mapping LTI activities to label notebook links" above).

### Steps

1. **Find the target section** — locate the `course_sections` record and its `sequence` that contains the label.
2. **Create the LTI record** — insert into `mdl_lti` with all required fields (see schema below).
3. **Create the course module** — insert into `course_modules` with `module=14`, linking to the new LTI `instance`.
4. **Insert into section sequence** — append the new cmid after the label's cmid in `course_sections.sequence`.
5. **Create the context** — call `context_module::instance($cmid, true)` so Moodle registers the activity.
6. **Purge caches** — `cache_helper::purge_by_event('changesincourse')`.

### Required LTI fields for insert

```php
$lti = new stdClass();
$lti->course = $course_id;
$lti->name = 'Activity name';
$lti->intro = '';
$lti->introformat = 4; // HTML
$lti->timecreated = time();
$lti->timemodified = time();
$lti->typeid = 2; // External tool type
$lti->toolurl = '';
$lti->securetoolurl = '';
$lti->instructorchoicesendname = 1;
$lti->instructorchoicesendemailaddr = 1;
$lti->instructorchoiceallowroster = '';
$lti->instructorchoiceallowsetting = '';
$lti->instructorcustomparameters = 'next=../user-redirect/git-pull?repo=...&urlpath=...';
$lti->instructorchoiceacceptgrades = 0;
$lti->grade = 0;
$lti->launchcontainer = 1; // New window
$lti->resourcekey = '';
$lti->password = '';
$lti->debuglaunch = 0;
$lti->showtitlelaunch = 0;
$lti->showdescriptionlaunch = 0;
$lti->servicesalt = '';
$lti->icon = '';
$lti->secureicon = '';
$ltiid = $DB->insert_record('lti', $lti);
```

### Required course_modules fields

```php
$cm = new stdClass();
$cm->course = $course_id;
$cm->module = 14; // lti
$cm->instance = $ltiid;
$cm->section = $section_id;
$cm->added = time();
$cm->score = 0;
$cm->indent = 1;
$cm->visible = 1;
$cm->visibleoncoursepage = 1;
$cm->visibleold = 1;
$cm->groupmode = 0;
$cm->groupingid = 0;
$cm->completion = 0;
$cm->completionview = 0;
$cm->showdescription = 1;
$cm->downloadcontent = 1;
$cm->lang = '';
$cm->enableaitools = 0;
$cm->enabledaiactions = '{"summarise_text":1,"explain_text":1,"generate_text":1}';
$cmid = $DB->insert_record('course_modules', $cm);
```

### Section sequence insertion

Insert the new cmid after the label cmid in the sequence string:

```php
$section = $DB->get_record('course_sections', ['id' => $section_id]);
$new_sequence = $label_cmid . ',' . $cmid . ',' . substr($section->sequence, strlen($label_cmid) + 1);
$section->sequence = $new_sequence;
$DB->update_record('course_sections', $section);
```

### Context and cache

```php
require_once($CFG->dirroot . '/lib/accesslib.php');
context_module::instance($cmid, true);
cache_helper::purge_by_event('changesincourse');
cache::make('core', 'coursemodinfo')->purge();
```

**Both** cache purges are required — `changesincourse` alone is insufficient; the activity won't appear in the UI without also purging `coursemodinfo`.

### Script file approach

Write PHP to a temp file and execute with `php`, not inline with `php -r`. Shell quoting mangles Moodle variable references (`$CFG`, `$DB`) and PHP array syntax. Always delete the temp script after execution.

### Pitfall: Insert fails with "Error writing to database"

If you only set `course`, `name`, and `instructorcustomparameters`, the insert will fail. The LTI table has many non-nullable fields (`typeid`, `introformat`, `launchcontainer`, etc.). Always provide the full set of fields shown above. Copy the values from an existing working LTI record as a template.

## Duplicating LTI activities

### The duplication process

Moodle duplicates activities via `course/format/classes/local/cmactions.php::duplicate()` (lines 409-562):
1. **Backup** the activity (backup_controller)
2. **Restore** it into the same course (restore_controller with `TARGET_CURRENT_ADDING`)
3. **Post-processing**: rename with ` (Copy)` suffix, move positioning, copy role overrides

### Pitfall: "dmlreadexception Error reading from database" on duplicate

The activity IS duplicated but shows an error and the name lacks the ` (Copy)` suffix.

**Root cause: The `mdl_lti` table is missing the `coursemodule` column.** The LTI plugin code (`mod/lti/lib.php:126`, `:178`) references `$lti->coursemodule` for completion tracking, but `install.xml` never defines this column and `upgrade.php` has no step to add it. When duplication triggers `lti_update_instance()` → `core_completion\api::update_completion_date_event($lti->coursemodule, ...)`, the query fails with `Unknown column 'coursemodule' in 'SELECT'`.

**Diagnosis:** Check with:
```bash
moosh php-eval "\$cols = \$DB->get_columns('lti'); foreach(\$cols as \$c) { echo \$c->name . PHP_EOL; }"
```
If `coursemodule` is absent from the output, this is the cause.

**Fix:** Add the missing column and populate it:
```sql
ALTER TABLE mdl_lti ADD COLUMN coursemodule INT(10) DEFAULT NULL;
UPDATE mdl_lti lti
JOIN course_modules cm ON cm.instance = lti.id AND cm.module = (SELECT id FROM mdl_modules WHERE name = 'lti')
SET lti.coursemodule = cm.id;
```

**See** `references/duplication-error.md` for full investigation details.

## LTI table schema

| Column | Type | Purpose |
|--------|------|---------|
| `id` | int | LTI instance ID |
| `course` | int | Course ID |
| `name` | varchar | Activity name |
| `intro` | text | Description (HTML) |
| `introformat` | int | Format of intro (4 = HTML) |
| `typeid` | int | LTI tool type reference |
| `instructorcustomparameters` | text | Custom params passed on launch (key field!) |
| `instructorchoicesendname` | int | Send user name (1/0) |
| `instructorchoicesendemailaddr` | int | Send user email (1/0) |
| `launchcontainer` | int | Launch container (1 = new window) |
| `showtitlelaunch` | int | Show title on launch |
| `showdescriptionlaunch` | int | Show description on launch |
| `servicesalt` | varchar | OAuth signature secret |
| `timecreated` | int | Creation timestamp |
| `timemodified` | int | Last modification timestamp |

## LTI group sync roster (`ltigroups` plugin) — "who hasn't logged in yet?"

The `ltigroups` plugin syncs a student roster (pushed from the course schedule) and auto-creates Moodle accounts on first LTI launch. Tables (verified 2026-08-29, course 3):

- **`mdl_ltigroups_roster`** — `id, courseid, eid, assignments, userid, timesynced, timecreated`
  - `eid` = the student's **CityU email** (the join key; the roster stores NO display name)
  - `assignments` = JSON of group assignments, e.g. `{"Lec":"C01","Lab":"T01"}`
  - `userid` = NULL/0 → **student has never logged in via LTI** (no account auto-created yet); set → account exists, `timesynced` = when it was linked
- **`mdl_ltigroups_config`** — `id, courseid, joinkey, staged`
- **`mdl_ltigroups_mapping`** — `id, courseid, groupingname, csvcolumn, sortorder` (roster column → grouping)

**"List students in the group sync who haven't enrolled / never LTI-logged-in":**

```sql
SELECT id, eid, assignments
FROM mdl_ltigroups_roster
WHERE courseid = <courseid> AND (userid IS NULL OR userid = 0)
ORDER BY assignments, eid;
```

**Pitfalls (verified 2026-08-29):**
- **Test accounts pollute the "never logged in" list.** The course-3 roster contains tester emails (`e_bltitest@cityu.edu.hk`, `e_cltitest@cityu.edu.hk`, `e_eltitest@cityu.edu.hk`). Two of them *do* have auto-created accounts (Bob LTITEST user 22, Chris LTITEST user 23, usernames `enrol_lti…`) yet their roster rows still show `userid` NULL. Cross-check each unlinked email against `mdl_user` (`SELECT u.id FROM mdl_user u WHERE u.email = r.eid`) and report test accounts separately from real students.
- The roster carries only email + Lec/Lab assignment — **not the student's name**. Derive a display name from the email prefix (CityU convention: `firstname-initiallastnameN-c`) or join `mdl_user` for linked rows only.
- Don't conflate roster size (212) with enrolled-student counts (182): the roster includes not-yet-logged-in + test rows; the enrolment count includes LTI auto-provisioned accounts.

## Stable user identity for LTI tools (JupyterHub) — don't key on email

If a downstream tool (JupyterHub, a grade service, …) needs a **stable** per-student identifier, do **NOT** key on email. LTI-provisioned students can change their email on the platform, and the LTI 1.3 launch sync then rewrites `mdl_user.email` (see the `moodle-lock-profile-editing` LTI-sync caveat and `logstore-user-field-audit.md`). The tool then sees a "new" person → duplicate accounts.

**What Moodle actually sends to the tool on each launch** (`mod/lti/locallib.php` `lti_build_request()`, ~line 804):
- `user_id` = `$USER->id` — the Moodle user id. **Stable and unique** — the best key.
- `ext_user_username` = `$USER->username` — for LTI-1.3 users this is `enrol_lti_13_<sha1(iss_sub)>`, derived from the platform `sub`, so it is **stable** (email-independent). Sent when the instance has `sendname = Always` (the JupyterHub instances in course 3 do).
- `lis_person_sourcedid` = `$USER->idnumber` — **empty for every LTI-1.3 user** on this site (verified 2026-09-10: uid 618 `idnumber` blank; only 8 legacy LTI-1.1 accounts carry an 8-digit idnumber). So the tool currently receives `lis_person_sourcedid = ""` and cannot use it.
- `lis_person_contact_email_primary` = `$USER->email` — mutable; **do not use as the key**.

**Why `idnumber` is empty:** the LTI 1.3 **auth** plugin (`auth/lti/auth.php`) never stores the inbound `person_sourcedid` claim. `create_new_account()` and `update_user_account()` sync only `given_name`, `family_name`, `email` (+picture). The string `sourcedid` does not appear anywhere in `auth/lti/`. (The `person_sourcedid` claim IS in the launch JWT — `enrol/lti/launch.php` decodes the whole JWT and it's in the claim map at `mod/lti/locallib.php:344` — it's simply dropped when the account is written.)

**The proper fix (apply only after user confirmation):** patch `auth/lti/auth.php` to persist the platform's stable id:
- `create_new_account()`: set `$user->idnumber = $userdata['person_sourcedid'] ?? null;`
- `update_user_account()`: add `'idnumber' => $userdata['person_sourcedid']` to the sync array, **only when the claim is present** (so a missing claim never blanks an existing idnumber).
Then `idnumber` self-populates on each student's next launch (passive), or you backfill in one shot from a student-number↔email mapping. After that, `lis_person_sourcedid` carries the CityU student number to the tool, with `user_id` / `ext_user_username` as fallbacks. Before relying on it, log one live launch's claims to confirm what the platform actually puts in `person_sourcedid` (expected: the CityU student number, per the 8 legacy accounts).

**Knock-on effect on the group-sync roster (verified 2026-09-10):** `local/ltigroups` matches roster rows to accounts **by email** (`sync.php:45`). When the LTI sync flips a student's account email away from the roster's `eid`, that roster row's `userid` link goes **NULL** even though the account still exists (uid 618's roster row showed `userid = NULL` while the account was live). Same root cause as the email problem; making identity key on `idnumber`/`sub` instead of email fixes both.

## Moodle version

This skill applies to **Moodle 5.2.1** (Build: 20260608) running PHP 8.3 on MariaDB 11.8.2.