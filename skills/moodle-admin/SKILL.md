---
name: moodle-admin
description: "Moodle environment administration: plugin discovery, configuration, Moosh commands, and instance introspection."
---

# Moodle Administration

Class-level skill for Moodle environment discovery, plugin management, and configuration tasks.

## Triggers

- Listing, installing, or managing Moodle plugins
- Finding Moodle installation root or data paths
- Running Moosh commands against the Moodle instance
- Checking Moodle version, configuration, or environment state
- Text rendering surprises (emoticon/emoji auto-conversion, text filters) — see "Text Filters & Emoticons (Moodle 5.2)" below
- Removing or suspending users (especially LTI-provisioned test users) — see "Removing Users (LTI-Provisioned Test Users)" below

## Removing Users (LTI-Provisioned Test Users)

Removing a user from a course (e.g. LTI test accounts like `Adam LTITEST` auto-provisioned by the `enrol_lti` plugin). Verified 2026-08-28.

### Find them (list first, wait for user confirmation)

LTI-provisioned users are recognizable by `username` prefix `enrol_lti<hash>` and `auth = 'lti'`. Multiple accounts can share the same display name across semesters (e.g. "Adam LTITEST" existed as both id=4 from 2024 and id=496 from 2026) — **match by course enrolment, not just name**.

Per-user footprint to check before deleting: enrolments (`mdl_user_enrolments` — FK to `mdl_enrol.id` is `enrolid`, not `enrolment`), `mdl_role_assignments`, `mdl_groups_members` (check the group's other members — don't nuke a shared group), `mdl_grade_grades` (no `courseid` column; join `mdl_grade_items` to scope), `mdl_quiz_attempts` / `mdl_quiz_grades`, `mdl_course_completions` + `mdl_course_modules_completion`, and the LTI link (`mdl_enrol_lti_users.userid`; `mdl_enrol_lti_user_resource_link` keys on `ltiuserid`).

### Delete

`moosh -n user-delete <username> [more usernames...]` (accepts multiple usernames in one call) — calls Moodle's `user_delete_user()`, the standard full-deletion path. This Moodle 5.x `delete_user()` is a **soft delete, by design**: the `mdl_user` row is kept with `deleted=1`, username renamed to `<email>.<timestamp>` (e.g. `e_ae_lti_test@<domain>.1787959770`), email replaced by an MD5 hash, and **all** course data stripped (enrolments, role assignments, group memberships, grades, completions, tokens, sessions). It does **NOT** remove `mdl_quiz_attempts` / `mdl_quiz_grades` rows or `logstore_standard_log` history — those remain attached to the deleted user (invisible in UI reports; purge manually with `delete_records` only if the user wants a hard scrub).

### Verify

1. `SELECT id, deleted, username FROM mdl_user WHERE lastname = 'LTITEST'` — removed ones show `deleted=1` + anonymized usernames; unrelated same-named accounts keep their original `timemodified`.
2. Roster check via the **same function the Participants page uses**: `get_enrolled_users(context_course::instance($cid), null, 0, 'u.id, u.firstname, u.lastname', [], 0, 0)` (the string-condition form `roleid>0` can return empty in CLI bootstrap — use `null` for a plain roster).
3. Group/gradebook spot-checks + `cd /var/www/html/public && moosh -n cache-clear`.

### LTI auto-re-provisioning caveat

The LTI tool recreates deleted accounts on the next launch if it sends the same tool-side user identities. Deletion on the Moodle side is not durable — tell the user that stopping re-creation requires removing the test users on the LTI tool/provider side.

## Key Environment Facts

- **Moodle webroot**: `/var/www/html/public` (NOT `/var/www/html`)
- **Course site directories**: `/var/www/html/cs1302a-eq/` and similar subdirectories serve as Moodle webroots for course-specific sites. Requests through those URLs resolve files relative to the course directory, NOT `/public/`.
- **Plugin symlink requirement**: When a plugin is installed in `/var/www/html/public/local/` but accessed via a course site URL (e.g., `/cs1302a-eq/local/hermesagent/`), you MUST symlink it: `ln -s /var/www/html/public/local/<plugin> /var/www/html/cs1302a-eq/local/<plugin>`. Without it, static assets (CSS, JS) and PHP pages 404.
- **Moodle config file**: `/var/www/html/config.php` (DB credentials, dataroot, wwwroot)
- **Public loader**: `/var/www/html/public/config.php` — shim that requires the parent config
- **Moodle data directory**: `/var/www/moodledata`
- **Database**: MariaDB at host `mariadb`, database `moodle`, prefix `mdl_`
- **Database access**: via `mcp__moodle_db__query` and related tools
- **PHP runtime**: PHP-FPM running as `www-data` inside a Kubernetes pod (`phpfpm-0`)
- **Moosh**: installed at `/usr/local/bin/moosh` → symlink to `/opt/moosh/moosh.php` (v1.27)
- **Moosh source**: `/opt/moosh/` — helper functions in `/opt/moosh/includes/functions.php`
- **Moosh Moodle discovery**: `find_top_moodle_dir()` walks up from CWD (max 10 levels) looking for `config.php` + `version.php` + `install.php`. It does NOT read `~/.moosh/moosh.json`. **Always `cd /var/www/html/public` before running Moosh.**
- **Moosh flag**: always use `-n` (no-user-check) because root runs Moosh but Moodle data is owned by `www-data`
- **Moosh**: installed at `/usr/local/bin/moosh` → symlink to `/opt/moosh/moosh.php` (v1.27). Works in this environment when the plugin cache is valid. See "Course Backup and Restore (CLI)" below.

## Course Backup and Restore (CLI)

### Recommended: Moosh `course-backup` (fast)

**Always prefer Moosh over Moodle's CLI scripts** — Moosh `course-backup` completes in seconds vs. minutes for the same course.

```bash
cd /var/www/html/public && moosh -n course-backup --template --filename=/tmp/backup.mbz <course_id>
cd /var/www/html/public && moosh -n course-restore /tmp/backup.mbz <category_id>
```

- `--template` excludes user enrolments, grades, and user-generated content. Use `--fullbackup` for a complete clone including enrolments.
- `course-restore` auto-creates a new course in the target category with an auto-generated shortname (e.g. `cs1302_25b_1`).
- Rename the restored course with `moosh -n sql-run "UPDATE mdl_course SET shortname='...', fullname='...' WHERE id=<new_id>"` (no trailing semicolon).
- Warning messages during restore (e.g. `exifremover_service::flip_gd()`) are non-fatal — files still restore correctly.
- Verify with `moosh -n course-info <new_id>` (check enrolled users = 0) and `moosh -n course-enrol-list <new_id>`.

### Fallback: Moodle CLI `backup.php` / `restore_backup.php` (slow)

Use Moodle's built-in CLI scripts when Moosh is unavailable. Scripts live under `/var/www/html/admin/cli/`.

#### Backup a course

```bash
php /var/www/html/admin/cli/backup.php --courseid=<ID> --destination=/tmp/
```

- Produces a `.mbz` file in the destination directory.
- **Very slow for large courses** (99 activities + 437 enrolments took 11+ minutes). Run in the background with `notify_on_complete=true`.
- Alternative: `--courseshortname=STRING` instead of `--courseid`.

#### Restore a course into a category

```bash
php /var/www/html/admin/cli/restore_backup.php --file=/tmp/backup.mbz --categoryid=<ID>
```

- Creates a new course in the specified category (new ID + shortname auto-generated).
- Use `--courseid=<ID>` instead to restore activity modules into an existing course.

## Listing Installed Plugins

### Method 1: Moosh `info-plugins` (recommended — most detailed)

```bash
moosh -n info-plugins 2>&1 | grep -v "Deprecated:"
```

Outputs a tab-separated list: `plugintype \t installpath \t plugin_names`. Best for seeing which sub-plugins exist under each type.

### Method 2: Moosh `config-plugins` (simple flat list)

```bash
moosh -n config-plugins
```

Outputs one line per installed plugin (e.g., `local_hermesagent`, `mod_bigbluebuttonbn`). Best for scripting or quick counts.

### Method 3: Filesystem scan

Scan for non-core plugins by checking each plugin type directory:

```bash
# Custom activity modules (mod)
for d in /var/www/html/public/mod/*/; do basename "$d"; done

# Custom local plugins
ls /var/www/html/public/local/

# Custom auth plugins
ls /var/www/html/public/auth/

# Enrol plugins
ls /var/www/html/public/enrol/

# Theme plugins
ls /var/www/html/public/theme/
```

Core plugin names to exclude when identifying custom ones:
- **mod**: assign, book, choice, data, feedback, folder, forum, glossary, h5pactivity, imscp, label, lesson, lti, page, quiz, resource, scorm, url, wiki, workshop
- **auth**: email, ldap, manual, nologin, none, shibboleth, webservice
- **theme**: boost, classic

### Method 4: Database query

```sql
SELECT plugin, version, release, component FROM mdl_config_plugins ORDER BY plugin
```

### Looking up available plugin versions (moosh `plugin-list -v`)

Use `moosh plugin-list -v` to find the latest version of a plugin from the Moodle plugin directory:

```bash
cd /var/www/html/public && moosh -n plugin-list -v 2>&1 | grep -i openaicompatible
# Output: aiprovider_openaicompatible,2025121000,2026060200,https://marketplace.moodle.com/...
# Columns: name,oldest_version,latest_version,download_url
```

- The `-v` flag shows version info instead of supported Moodle versions.
- This is the correct way to check available versions before installing.
- Note: `plugin-list` downloads from moodle.org so it needs external connectivity. It can fail with HTTP 403 — seed the cache first (see Pitfalls below).

### Moosh `plugin-list` is NOT for listing installed plugins

`moosh plugin-list` shows the **catalog of available plugins** from moodle.org, not what's installed on your site. Use `info-plugins` or `config-plugins` for installed plugins. See `references/moosh-plugin-list-loop.md` for full diagnosis of when it loops.

## Installing Plugins

### Moosh `plugin-install` (recommended)

```bash
cd /var/www/html/public && moosh -n plugin-install -f <plugin_name>
```

- Always `cd /var/www/html/public` first (Moosh discovers Moodle from CWD).
- Always use `-n` to skip the ownership check (root runs Moosh, `www-data` owns Moodle data).
- Always use `-f` to force installation — Moodle 5.2 is so new that most plugins report "not supported for your Moodle version" and refuse without `-f`.

**Prerequisite**: Moosh needs an up-to-date plugin database. If `plugins.json` is missing or stale, run:
```bash
cd /var/www/html/public && moosh -n plugin-list 2>&1
```
This downloads `~/.moosh/plugins.json`. (It may loop if external connectivity is unavailable — see Pitfalls below.)

### Manual installation (fallback)

Use when `plugin-install` fails due to network issues or the plugin isn't in the Moodle plugin directory database.

1. **Download the plugin ZIP** from moodle.org (may be rate-limited):
   ```bash
   curl -sL -o /tmp/plugin.zip "https://moodle.org/plugins/download.php/<id>/<pluginname>"
   ```
   Verify it's a real ZIP (not HTML error page): `head -c 100 /tmp/plugin.zip` should show binary data, not `<!DOCTYPE html>`.

2. **Extract into the correct plugin directory:**
   ```bash
   unzip -o /tmp/plugin.zip -d /var/www/html/public/local/    # for local_ plugins
   # or /var/www/html/public/mod/, /var/www/html/public/auth/, etc.
   ```

3. **Set correct ownership:**
   ```bash
   chown -R www-data:www-data /var/www/html/public/local/adminer
   ```

4. **Verify version.php matches DB**: If the plugin is already in the DB with a higher version, update `version.php` accordingly:
   ```bash
   moosh -n config-plugins | grep adminer
   # Check version.php against DB version
   ```

5. **Run the Moodle upgrade** (note: script lives under `/var/www/html/admin/cli/`, NOT `/var/www/html/public/admin/cli/`):
   ```bash
   cd /var/www/html && php admin/cli/upgrade.php --non-interactive
   ```

6. **Verify installation:**
   ```bash
   moosh -n config-plugins | grep <plugin>
   ```

### After `plugin-install`: registering the plugin in the database

`moosh plugin-install` only copies the files — it does **NOT** register the plugin in `mdl_config_plugins`. The plugin will appear in the UI as "To be installed" with no version shown.

**`admin/cli/upgrade.php --non-interactive` does NOT install plugins** — it only checks for core Moodle version upgrades. It will say "No upgrade needed" even when plugins are pending.

To register a plugin, use **one** of:

**Option A — Web UI (recommended):**
Go to `/admin/upgrade.php` and click "Upgrade Moodle database now". This runs the plugin install SQL.

**Option B — PHP script with full Moodle bootstrap:**
```php
<?php
define('CLI_SCRIPT', TRUE);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/register-plugin.php';
require_once('/var/www/html/config.php');
$DB->insert_record('config_plugins', ['plugin' => 'aiprovider_openaicompatible', 'name' => 'version', 'value' => '2026060200']);
purge_all_caches();
echo "Plugin registered.\n";
?>
```
Replace the plugin name and version with the actual values. The version must match `$plugin->version` in the plugin's `version.php`.

**Option C — If `version.php` is missing `$plugin->release`:**
Some plugins show as "To be installed" with no version string in the UI. Add `$plugin->release = '0.1.0';` to `version.php` and run `purge_all_caches()` before attempting the install.

### If download sources are unavailable

If moodle.org rate-limits you (HTTP 429) and GitHub is unreachable:
- Check if the plugin was already extracted from a prior attempt: `find /var/www/html/public/local -name "<plugin>" -type d`
- The plugin may already exist in the DB — just update `version.php` and re-run upgrade.

## Known Custom Plugins (as of 2026-07-18)

| Plugin | Type |
|---|---|
| `local/hermesagent` | Local (AI agent integration) |
| `local/adminer` | Local (Adminer database browser) |
| `mod/bigbluebuttonbn` | Activity (BigBlueButton conferencing) |
| `mod/qbank` | Activity (Question Bank) |
| `mod/subsection` | Activity (Subsection course format) |
| `editor/marklar` | Editor (Marklar placeholder editor) |
| `filter/filtercodes` | Filter (Code syntax highlighting) |

## Creating Activities Programmatically

`moosh activity-add` uses Moodle's test data generator, which initializes the theme/output layer and **crashes for many activity types** (e.g., `forum`) with "Creating a mod_XXX activity initialised the theme and output!". The reliable approach is direct DB insertion via a Moodle-bootstrapped PHP script.

### Generic pattern for creating any activity

```php
<?php
define('CLI_SCRIPT', TRUE);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/add-activity.php';
require_once('/var/www/html/config.php');

// 1. Get the module ID for the activity type
$modid = $DB->get_field('modules', 'id', ['name' => 'forum']);

// 2. Get the target section
$section = $DB->get_record('course_sections', ['course' => 3, 'section' => 1]);

// 3. Insert course_modules row
$cm = new stdClass();
$cm->course = 3;
$cm->module = $modid;
$cm->section = $section->section;
$cm->visible = 1;
$cm->intro = '';
$cmid = $DB->insert_record('course_modules', $cm);

// 4. Insert activity instance (fill in activity-specific fields)
$forum = new stdClass();
$forum->course = 3;
$forum->type = 'qa';
$forum->name = 'CE-Quiz FAQ';
$forum->intro = 'Post your questions here.';
$forum->introformat = 1;
$forumid = $DB->insert_record('forum', $forum);

// 5. Link CM to instance
$DB->set_field('course_modules', 'instance', $forumid, ['id' => $cmid]);
purge_all_caches();
echo "Created: CM=$cmid, Instance=$forumid\n";
?>
```

For **forum** activities, key fields in `mdl_forum`: `type` (qa/standard/social), `forcesubscribe` (0=optional, 1=forced, 2=self-managed), `autosubscribe`.

**After creating, you MUST do TWO cache purges:**

1. `cd /var/www/html/public && moosh -n cache-clear`
2. **Delete the file-based moduleinfo cache** for the affected course. Moodle caches course module structure as files and `moosh cache-clear` does NOT clear them:
   ```bash
   rm -rf /var/www/moodledata/cache/local_file/core_coursemodinfo/<courseid>-c-cache/
   ```
   Without step 2, the activity exists in the DB but **will not appear in the course UI**. Moodle rebuilds the cache on next page load.

### Why `forum_add_instance()` doesn't work via moosh `php-eval`

`forum_add_instance()` expects `$forum->coursemodule` to be set to an existing CM ID, but `add_module()` (which creates the CM) is not available in the moosh bootstrap context. The DB-insert-then-link pattern above sidesteps this entirely.

## Pitfalls

### Moosh does NOT read `~/.moosh/moosh.json` for path discovery
Moosh discovers Moodle by walking up the directory tree from CWD, looking for `config.php` + `version.php` + `install.php` (see `is_top_moodle_dir()` in `/opt/moosh/includes/functions.php`). Setting `"moodlepath"` in `~/.moosh/moosh.json` has **no effect**. Always `cd /var/www/html/public` before running Moosh commands.

### Moosh `-m` / `-c` flags do not exist
The correct moodle-path flag is `-p` (or `--moodle-path`). Flags `-c` and `-m` cause exit 255 with no output. Always `cd /var/www/html/public` before running Moosh instead of relying on a path flag.

### Moosh requires `-n` flag in this environment
Moodle data is owned by `www-data` but Moosh runs as `root`. Always pass `-n` (no-user-check) or Moosh will refuse to run with: "One of your Moodle data directories ... is owned by different user."

### Moosh `plugin-list` infinite loop and HTTP 403
`plugin-list` downloads from `https://download.moodle.org/api/1.3/pluglist.php` using PHP's `file_get_contents()`, which returns 403 Forbidden in this environment. Moosh writes the 403 response to `plugins.json`, JSON parsing fails, and it deletes the file with "Invalid JSON file" — repeating indefinitely.

**Diagnose** by enabling PHP errors:
```bash
php -d display_errors=1 -d error_reporting=E_ALL /usr/local/bin/moosh plugin-list 2>&1
```

**Fix** — seed the cache with curl (which sends a proper User-Agent):
```bash
curl -s -A "Moosh/1.27" https://download.moodle.org/api/1.3/pluglist.php \
  -o /home/www-data/.moosh/plugins.json
```

**After seeding, `plugin-list` and `plugin-install` work normally.** Use `moosh -n plugin-list -v | grep <name>` to look up versions.

**Warning**: Moosh re-downloads the file if older than 24 hours, triggering the same 403. Re-run the curl command if `plugin-list` or `plugin-install` fails again. See `references/moosh-plugin-list-loop.md` for full diagnosis.

### Moosh `sql-run` trailing semicolon
`moosh sql-run` fails with "Multiple sql statements found or bound parameters not used properly" if the query ends with a semicolon. Omit the trailing `;`.

### Moosh has no `course-set-field`
This version of Moosh (1.27) does not include `course-set-field`. Use `moosh -n sql-run "UPDATE mdl_course SET ... WHERE id=..."` instead to rename courses or change fields.

### Moosh exits 255 silently
Moosh can crash with exit 255 and no output when `~/.moosh/plugins.json` is corrupted or when an invalid CLI flag is used (e.g. `-c` instead of `-p`, or `-m`). Always use `php -d display_errors=1` to see the actual error. Fix by removing the file and regenerating:
```bash
rm -f ~/.moosh/plugins.json
cd /var/www/html/public && moosh -n info-plugins
```

### Moosh CLI flags
The correct moodle-path flag is `-p` (or `--moodle-path`). There is **no `-c` or `-m` flag** — using them causes exit 255 with no output unless PHP errors are enabled. Prefer `cd /var/www/html/public` instead of using `-p`.

## Code Runner Prototype Management

Code Runner prototypes are stored as special `coderunner` questions in the `CR_PROTOTYPES` question category (`mdl_question_categories.id = 2`, contextid = 12 — system level). A course `--template` backup **does not include** system-level prototypes, so cloned courses lose their custom prototypes.

### Symptoms of a missing prototype

```
Broken question (missing or duplicate prototype 'python3_CS1302_prototype'). Cannot be run.
```

### Check for a missing prototype

```bash
moosh -p /var/www/html/public -n sql-run "SELECT id, name, qtype, parent FROM mdl_question WHERE name = 'python3_CS1302_prototype'"
```

### Import a prototype from Moodle XML

**Do NOT use `moosh question-import`** — it is broken in this Moodle 5.2 installation (`qformat_xml.php` is missing). Instead, insert the records directly via `moosh sql-run`:

1. **Find the XML export** of the prototype (usually from the system-level question bank → `CR_PROTOTYPES` category).

2. **Delete any broken placeholder** if one exists:
   ```bash
   moosh -p /var/www/html/public -n sql-run "DELETE FROM mdl_question WHERE id = <broken_id>"
   ```

3. **Insert into `mdl_question`** (reuse the freed ID to avoid auto-increment gaps):
   ```sql
   INSERT INTO mdl_question (id, parent, name, questiontext, questiontextformat, generalfeedback, generalfeedbackformat, defaultmark, penalty, qtype, length, stamp, timecreated, timemodified, createdby, modifiedby)
   VALUES (4274, 2, 'python3_CS1302_prototype', '# Prototype of python3 for CS1302', 0, '', 0, 1, 0, 'coderunner', 1, 'moodle@20250625', UNIX_TIMESTAMP(), UNIX_TIMESTAMP(), 2, 2)
   ```
   - `parent=2` is the `CR_PROTOTYPES` category ID.
   - `penalty=0` for prototypes (not `0.3333333`).

4. **Insert into `mdl_question_coderunner_options`**:
   ```sql
   INSERT INTO mdl_question_coderunner_options (questionid, coderunnertype, prototypetype, allornothing, showsource, precheck, hidecheck, answerboxlines, answerboxcolumns, answerpreload, useace, penaltyregime, validateonsave, template, iscombinatortemplate, allowmultiplestdins, testsplitterre, language, grader, hoisttemplateparams, extractcodefromjson, templateparamslang, templateparamsevalpertry, templateparamsevald, twigall, uiplugin, attachments, attachmentsrequired, maxfilesize, displayfeedback, giveupallowed)
   VALUES (4274, 'python3_CS1302_prototype', 2, 0, 0, 2, 0, 18, 100, '# YOUR CODE HERE', 1, '10, 20, ...', 1, 'TEMPLATE_CONTENT', 1, 0, '|SPLITTER_RE|ms', 'python3', 'EqualityGrader', 1, 1, 'None', 0, '{}', 0, 'ace', 0, 0, 10240, 1, 0)
   ```
   - `prototypetype=2` means user-defined prototype (1 = built-in).
   - Shell-quote the `template` field carefully — Twig `{{ }}` is safe in SQL, but PHP single quotes inside the template must be escaped.

5. **Insert test cases** (one `INSERT` per test case):
   ```sql
   INSERT INTO mdl_question_coderunner_tests (questionid, testtype, testcode, stdin, expected, useasexample, display, hiderestiffail, mark)
   VALUES (4274, 0, '1', 'Alice!', 'Hello, Alice!\n', 1, 'SHOW', 0, 1)
   ```

5. **Clear Moodle cache** via moosh:
   ```bash
   moosh -p /var/www/html/public -n cache-clear
   ```

6. **Verify**:
   ```bash
   moosh -p /var/www/html/public -n sql-run "SELECT q.id, q.name, q.parent, cat.name FROM mdl_question q JOIN mdl_question_categories cat ON q.parent = cat.id WHERE q.name = 'python3_CS1302_prototype'"
   ```

### Key tables and columns

| Table | Key columns |
|---|---|
| `mdl_question` | `id`, `parent` (category id), `name`, `qtype` |
| `mdl_question_bank_entries` | `id` (same as question id), `questioncategoryid` |
| `mdl_question_versions` | `id` (same as question id), `questionbankentryid`, `version`, `questionid`, `status` |
| `mdl_question_coderunner_options` | `questionid`, `coderunnertype`, `prototypetype`, `template`, `iscombinatortemplate`, `language`, `grader` |
| `mdl_question_coderunner_tests` | `questionid`, `testcode`, `stdin`, `expected`, `display` |
| `mdl_question_categories` | `id`, `name` (`CR_PROTOTYPES`=2, `contextid`=12 system) |

### Why the versioning tables matter

Code Runner's `get_prototype()` SQL JOINs through `mdl_question_bank_entries` → `mdl_question_versions` → `mdl_question`. If you only insert into `mdl_question` and `mdl_question_coderunner_options`, the prototype **will not be found** — Code Runner returns `null` silently. The `mdl_question_bank_entries` row must exist with `questioncategoryid = 2` (CR_PROTOTYPES), and the `mdl_question_versions` row must reference it.

The easiest way is to reuse the question ID across all tables:
```sql
-- Reuse the same ID (e.g. 4274) across all three question tables
INSERT INTO mdl_question_bank_entries (id, questioncategoryid) VALUES (4274, 2);
INSERT INTO mdl_question_versions (id, questionbankentryid, version, questionid, status) VALUES (4274, 4274, 1, 4274, 'ready');
INSERT INTO mdl_question (id, parent, name, ...) VALUES (4274, 2, 'python3_CS1302_prototype', ...);
```

### Verify the prototype is discoverable

Write a PHP script that bootstraps Moodle:
```php
<?php
define('CLI_SCRIPT', TRUE);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/check-prototype.php';
require_once('/var/www/html/config.php');
$coursectx = context_course::instance(<course_id>);
$qtype = new qtype_coderunner();
echo 'Prototype exists: ' . var_export($qtype->get_prototype('python3_CS1302_prototype', $coursectx, true), true) . PHP_EOL;
?>
```
Must return `true`. If it returns `false`, check that `mdl_question_bank_entries` and `mdl_question_versions` both exist and reference the correct IDs.

### OPcache prevents prototype changes from taking effect

PHP-FPM in this container runs with opcache enabled. After inserting prototype records, Moodle's `cache-clear` is **not sufficient** — the PHP process still holds stale results. Since PID 1 (php-fpm master) is root-owned and cannot be killed from the container, the only reliable fix is to **restart the Kubernetes pod**. Test with a PHP script as shown above before assuming the user needs a pod restart.

## CE-Quiz Group Override Management

CE-Quizzes use Moodle quiz **group overrides** to give each lab section its own time window. The pattern: CE-Quiz N runs during Lab N (Week N+2).

### Creating groups for lab sessions

Lab groups (T01, T02, LA1–LA4, LB1–LB3, etc.) must exist in the course before overrides are created. New groups are best created via Moodle API:

```php
define('CLI_SCRIPT', TRUE);
require_once('/var/www/html/config.php');
$data = (object)['courseid' => 3, 'name' => 'T01', 'description' => '', 'descriptionformat' => FORMAT_MOODLE];
$DB->insert_record('groups', $data);
```

### Setting up group overrides

1. **Delete stale overrides** first (from semester backups):
   ```php
   $DB->delete_records('quiz_overrides', ['quiz' => $quizId]);
   ```

2. **Create overrides** — each row specifies `groupid`, `timeopen`, `timeclose`. Set `timelimit` and `attempts` to match the quiz's own defaults (e.g., 2700 and 1) — **do NOT set them to 0**, which means "no override" in Moodle's UI and causes confusion.

3. **Purge caches** after DB changes:
   ```bash
   cd /var/www/html/public && moosh -n cache-clear
   ```

### Key table

| Table | Columns |
|---|---|
| `mdl_quiz_overrides` | `id`, `quiz`, `groupid`, `userid`, `timeopen`, `timeclose`, `timelimit`, `attempts` |

### Pitfalls

- Overrides from course backups carry last semester's group IDs and dates. Always delete stale overrides before recreating.
- `mdl_quiz_overrides` has `groupid` (NOT `group_id`) and `userid` — set the unused one to 0.
- Groups T01/T02/TA1 (teaching assistant sections) are separate from lab sections LA1–LE3, LF5–LH5.

## Role and Capability Management

### Role capability editing: Basic vs Advanced view

The role editing page (`admin/roles/define.php`) has **two views**:

1. **Basic view** (default) — shows only an **Allow** checkbox. Unchecked = Inherit. Prevent and Prohibit are **hidden**.
2. **Advanced view** — revealed by clicking the **"Show advanced"** button at the bottom of the form. Shows all four states: **Inherit / Allow / Prevent / Prohibit**.

**Pitfall**: If you see only an unchecked "Allow" checkbox, the capability is **Inherited** (not denied). The Student role inherits `moodle/user:editownprofile` from Authenticated user. To set Prevent or Prohibit, you **must** click "Show advanced" first.

### Capability permission states

| State | Value | Meaning |
|---|---|---|
| Not set (Inherit) | 0 | Use permission from higher context/parent role |
| Allow | 1 | Grant permission |
| Prevent | 2 | Deny unless overridden by Allow in a more specific context |
| Prohibit | 3 | Absolute deny — cannot be overridden by any role |

### How Moodle resolves capabilities

- Moodle evaluates capabilities across **all roles assigned** to a user in all relevant contexts.
- A user with Student role in a course also has Authenticated user role at system level — permissions combine.
- **Prohibit always wins** — if any role in the context has Prohibit, the capability is denied regardless of other Allow roles.
- Role sort order is cosmetic only — it does not affect permission resolution.
- `admin/cli/upgrade.php --non-interactive` only checks core Moodle version, not plugins. Always register plugins manually or via the web UI upgrade page.

### Preventing students from editing their profile/email

The `updateemailaddress` config **does not exist in Moodle 5.2** — it was removed in a recent version. The email field is always rendered as editable in `user/editlib.php` with no config check.

Options to prevent email changes:

1. **Auth plugin field lock** — `auth_email` has `field_lock_email = locked` (Site admin → Plugins → Authentication → Email). Only works for email-authenticated users. LTI users are unaffected. Check which auth plugins your users use by running a PHP script or moosh sql-run query instead.

2. **Student role Prohibit** — Go to Student role edit → click **"Show advanced"** → set `moodle/user:editownprofile` to **Prohibit**. This blocks the entire profile (not just email). Requires DB insertion via `assign_capability()` if the UI doesn't expose it.

3. **LDAP/DB auth plugins** — `auth_ldap`, `auth_db`, and `auth_shibboleth` all have `field_lock_email = locked` settings, but only apply to users authenticated via those methods.

## Pitfalls (continued)

### Always purge caches after database changes
After any raw SQL change to Moodle tables, **always purge caches** before verifying. The user cannot see the change otherwise. Use `moosh -n cache-clear` for this.

**Moodle 5.x removed `cache_helper::purge_reset()`** — using it throws "Call to undefined method". Use `purge_all_caches()` instead. See `moodle-cache-purge` skill for details.

### Moosh `php-eval` works in Moosh 1.27
`moosh php-eval` IS available in Moosh 1.27 and works for running arbitrary PHP with Moodle's `$DB` object available. Usage:
```bash
cd /var/www/html/public && moosh -n php-eval "echo \$DB->count_records('course') . PHP_EOL;"
```
Note: some Moodle API functions (`purge_all_caches()`, `context_course::instance()`, etc.) may not be available in the moosh bootstrap context — for those, write a standalone PHP script that requires `/var/www/html/config.php`.

### Moodle 5.x removed `php-eval.php`
`admin/cli/php-eval.php` no longer exists in Moodle 5.x. Use `moosh php-eval` or a standalone PHP script instead.

### Sending email via Moodle SMTP
When you need to send email (testing SMTP, notifications), use PHPMailer (bundled with Moodle) through a CLI script:
```php
<?php
define('CLI_SCRIPT', TRUE);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/send.php';
require_once('/var/www/html/config.php');
use PHPMailer\PHPMailer\PHPMailer;
use PHPMailer\PHPMailer\Exception;

$host = $CFG->smtphosts; // May include port like "smtp.example.com:587"
// Parse host:port
if (preg_match('/^(.*):(\d+)$/', $host, $m)) { $host = $m[1]; $port = (int)$m[2]; }
else $port = 587;

$mailer = new PHPMailer(true);
$mailer->isSMTP();
$mailer->Host = $host;
$mailer->Port = $port;
$mailer->SMTPSecure = $CFG->smtpsecure ?? '';
$mailer->SMTPAuth = !empty($CFG->smtpuser);
if (!empty($CFG->smtpuser)) { $mailer->Username = $CFG->smtpuser; $mailer->Password = $CFG->smtppass ?? ''; }
$mailer->setFrom($CFG->noreplyaddress ?? 'noreply@example.com');
$mailer->addAddress('recipient@example.com');
$mailer->Subject = 'Test';
$mailer->Body = 'Test body';
echo $mailer->send() ? 'Sent' : 'Failed';
?>
```
The email functions `email_to_user_addr()` and `email_get_from_address()` do NOT exist in Moodle 5.2 — use PHPMailer directly.

### `moosh sql-run` only supports single statements
Multi-statement SQL (e.g., `INSERT ... ; SET @x = ... ; SELECT ...`) fails with "Multiple sql statements found or bound parameters not used properly". Each `INSERT` or `UPDATE` must be a separate `sql-run` call. Also omit the trailing semicolon.

### Moodle XML question import is broken
`qformat_xml.php` is missing from this Moodle 5.2 installation, so `moosh question-import` and direct PHP import via `qformat_xml` both fail. The only reliable way to import questions/prototypes is direct SQL insertion via `moosh sql-run`.

## Publishing Courses as LTI Tools

"Publish as LTI tool" is implemented by the **`enrol_lti`** plugin (an enrolment plugin), NOT `mod_lti` (the activity module). Do not look in `mod_lti/settings.php` or `lib/ltiprovider/` for course publishing — that code handles Moodle acting as an LTI *consumer*, not provider.

### How it works

1. The `enrol_lti` plugin creates an enrolment instance of type `lti` on a course.
2. Corresponding records in `mdl_enrol_lti_tools` store the tool configuration (secret, grade/member sync settings, provisioning mode).
3. External platforms launch the course as an LTI tool and users are auto-enrolled via the LTI enrol instance.

### Key tables

| Table | Purpose |
|---|---|
| `mdl_enrol` (where `enrol='lti'`) | LTI enrolment instances (status=0 = enabled) |
| `mdl_enrol_lti_tools` | Tool config per course (secret, sync settings, roles) |
| `mdl_enrol_lti_deployment` | Deployment mappings between platforms and courses |
| `mdl_enrol_lti_app_registration` | Registered external LTI platforms |

### Checking if a course is published

```sql
SELECT t.id AS toolid, e.courseid, t.ltiversion, t.gradesync, t.membersync, e.status
FROM mdl_enrol_lti_tools t
JOIN mdl_enrol e ON e.id = t.enrolid
WHERE e.courseid = <course_id>
```

### UI location

- Course administration → Users → Enrolment methods → "Publish as LTI tool"
- Requires `moodle/course:enrolconfig` capability
- Published resources list: `/enrol/lti/index.php?courseid=<id>`

### Admin settings

Site administration → Plugins → Enrolments → Publish as LTI tool (admin category `enrolltifolder`)

## Setting Moodle Configuration Values

Use a PHP script that bootstraps Moodle and calls `set_config()`:

```php
<?php
define('CLI_SCRIPT', TRUE);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/set-config.php';
require_once('/var/www/html/config.php');
set_config('smtphosts', '<smtp-host>:587');
echo get_config('', 'smtphosts') . PHP_EOL;
?>
```

Save to `/tmp/set-config.php` and run `php /tmp/set-config.php 2>&1`. Verify the value with `get_config('', 'key')`. Always purge caches after.

### Pitfall: SMTP hosts config key is `smtphosts`, NOT `smptphosts`

Moodle's SMTP hosts setting uses the config key `smtphosts` (with an `h` before the `t`). The misspelled `smptphosts` is a common autocomplete trap — `set_config('smptphosts', ...)` silently creates a new DB row that Moodle **never reads**, leaving the UI showing "empty". Always verify with `get_config('', 'smtphosts')` after setting.

## SEB (Safe Exam Browser) Quiz Access

The `quizaccess_seb` plugin enforces Safe Exam Browser requirements on Moodle quizzes. Plugin lives at `/var/www/html/public/mod/quiz/accessrule/seb/`.

### SEB config modes (`requiresafeexambrowser`)

| Value | Constant | Meaning |
|---|---|---|
| `0` | `USE_SEB_NO` | SEB not required |
| `1` | `USE_SEB_CONFIG_MANUALLY` | Manually configured SEB settings |
| `2` | `USE_SEB_TEMPLATE` | Uses a saved SEB template |
| `3` | `USE_SEB_UPLOAD_CONFIG` | Upload a `.seb` config file |
| `4` | `USE_SEB_CLIENT_CONFIG` | Client-side SEB config |

### Key tables

| Table | Purpose |
|---|---|
| `mdl_quizaccess_seb_quizsettings` | Per-quiz SEB config (`quizid`, `cmid`, `templateid`, `requiresafeexambrowser`, feature flags) |
| `mdl_quizaccess_seb_template` | Named SEB templates (`id`, `name`) referenced by `templateid` |

### Access validation flow

When a user attempts quiz access:
1. Check `seb_required()` — skip if SEB not required
2. Check `can_bypass_seb()` — admin/teacher roles skip
3. Validate basic header (is request from SEB?)
4. **Validate config key** — compares stored hash with what SEB sends
5. **Validate browser exam key**

If config key fails, the plugin:
- Logs `action=prevented`, `component=quizaccess_seb` with `eventname=\quizaccess_seb\event\access_prevented`
- Stores reason in `other` JSON field: `{"reason":"Invalid SEB config key","savedconfigkey":"...","receivedconfigkey":null,"receivedbrowserexamkey":null}`
- Shows **"Launch SEB"** (`seb://` protocol link) and **"Download config"** (HTTP `.seb` file) buttons

### Debugging SEB access failures

When looking up users, be aware that **multiple users can share the same name** (e.g., Adam LTITEST exists as both `id=4` and `id=496`). Use `lastaccess` to identify the active account.

```php
$logs = $DB->get_records('logstore_standard_log', ['userid' => $uid, 'courseid' => $cid], 'id DESC', '*', 0, 10);
foreach ($logs as $log) {
    if ($log->component == 'quizaccess_seb') {
        $data = json_decode($log->other, true);
        echo $data['reason'] . "\n";
    }
}
```

**"Invalid SEB config key"** means the user's SEB client has stale config. The error page shows:
- **"Launch SEB"** — a `seb://` protocol link that opens SEB with fresh config from Moodle. This works immediately and is the preferred fix.
- **"Download config"** — an HTTP link to a `.seb` file for manual loading. Only needed if the `seb://` protocol handler isn't registered on the user's system.

### Updating SEB settings via DB

To assign a SEB template to a quiz (or change config mode):

```php
// Set quiz to use template (templateid=1, mode=2)
$DB->set_field('quizaccess_seb_quizsettings', ['templateid' => 1, 'requiresafeexambrowser' => 2], ['quizid' => $quizId]);
```

To update all quizzes in a course at once:
```php
$settings = $DB->get_records('quizaccess_seb_quizsettings');
foreach ($settings as $s) {
    $quiz = $DB->get_record('quiz', ['id' => $s->quizid]);
    if ($quiz && $quiz->course == $courseId) {
        $DB->set_field('quizaccess_seb_quizsettings', 'templateid', $templateId, ['id' => $s->id]);
        $DB->set_field('quizaccess_seb_quizsettings', 'requiresafeexambrowser', 2, ['id' => $s->id]);
    }
}
```

After DB changes, purge caches: `cd /var/www/html && php admin/cli/purge_caches.php`.

### Global SEB config

Query `mdl_config_plugins` where `plugin='quizaccess_seb'`:
- `showseblinks` — comma-separated: `seb`, `http` (which buttons to show)
- `autoreconfigureseb` — auto-configure SEB on launch
- `downloadlink` — URL for downloading SEB

### Batch template update — verified procedure (2026-09-14, cs1302a_26a)

- In **template mode** the SEB config (incl. URL filtering) is defined **entirely in the template XML** — `process_seb_template()` only layers per-quiz `allowuserquitseb`, quit password/URL, and enforced `startURL` / `sendBrowserExamKey` / modern-WebView on top. So switching `templateid` to a urlfilter template is sufficient for the filtering itself.
- **`allowuserquitseb` NULL → `allowQuit` silently becomes false** (the bool map treats non-1 as false). When making quizzes "identical to reference quiz X", set `allowuserquitseb` explicitly to match the reference quiz.
- Direct `$DB->update_record('quizaccess_seb_quizsettings', ...)` (set `templateid`, `allowuserquitseb`, `timemodified`, `usermodified`) works — no UI form post, no gateway/daemon restart.
- **MUST purge the three application caches** or students keep the stale config key ("Invalid SEB config key"): `foreach (['config', 'configkey', 'quizsettings'] as $c) \cache::make('quizaccess_seb', $c)->purge();`
- **Verify** by regenerating and inspecting the plist: `$cfg = quizaccess_seb\seb_quiz_settings::get_config_by_quiz_id($qid);` — grep for `<key>URLFilterEnable</key><true/>`, one `<key>expression</key>` per allowed domain, `allowQuit` as expected.
- Before applying: confirm which quizzes actually have SEB rows (`mdl_quizaccess_seb_quizsettings` is only populated for quizzes with SEB configured) and exclude test quizzes / non-restricted quizzes.

## Moodle 5.2 Schema & Data Notes (this instance)

Empirical facts from this Moodle 5.2.1 install (verify per version before reusing elsewhere):

- **`mdl_course_modules` has NO `name` column** in 5.2 — to list activities with their titles, join the module's instance table (`mdl_quiz.name`, `mdl_forum.name`, `mdl_label` — labels have no instance table; check `mdl_label` by cmid for `label` modules).
- **Section sequences can contain dangling cmids** (e.g. `course_sections.sequence` referencing a deleted cmid). Harmless — Moodle skips missing CMs — but a sign of unclean deletion.
- **`mdl_forum` has no `forummode`/`mandatorysubscribe`/`forumrules` columns** in 5.2 — check `describe_table('mdl_forum')` before querying; use `forcesubscribe` (0/1/2) and `trackingtype` instead.
- **Course context is `contextlevel = 50`** (not 70): `SELECT id FROM mdl_context WHERE contextlevel = 50 AND instanceid = <courseid>` — verified working for `mdl_role_assignments` lookups (2026-09-14).
- **Quiz scoring scales differ:** `mdl_quiz_attempts.sumgrades` is on the raw question-mark scale (e.g. E-Quiz 1 max = 22), while `mdl_quiz.grade` is the gradebook max (80). The authoritative % is the gradebook `mdl_grade_grades.finalgrade` for the quiz's `mdl_grade_items` row (already rescaled); never compute % as `sumgrades / quiz.grade`.
- **MCP `mcp__moodle_db__query` caveats:** (1) naive keyword filter rejects any SQL containing the substrings `DELETE` or `CREATE` even inside column names (`userdeleted`, `timecreated`); (2) results capped at 100 rows — paginate with `WHERE id > X ORDER BY id LIMIT 100`; (3) `describe_table` requires the `table` argument; (4) read-only — writes need the PHP bootstrap (see `moodle-db-access` skill).

## Text Filters & Emoticons (Moodle 5.2)

Why plain text like `(n)` renders as an emoji image, and where the settings actually live:

- **Emoticon sequences are NOT in a DB table** — the `mdl_emoticon` table was removed in Moodle 4.5. The list is JSON in `mdl_config.emoticons` (entries: `text`, `imagename`, `imagecomponent`, `altidentifier`, `altcomponent`). The default set includes `(y)`, `(n)`, `(h)`, `(heart)`, `(martin)`, `( )`, `(grr)` — so "1 (n) 2" in HTML/Markdown/Moodle-format text silently becomes an image.
- **UI management**: Site administration → Appearance → HTML settings → **Emoticons** (one checkbox per sequence). Prefer the UI form; if the user explicitly wants a direct edit, rewrite the JSON in `mdl_config` then `moosh -n cache-clear`. Reset-to-defaults page: `/admin/resetemoticons.php`.
- **Filter active state in 5.2**: there is NO `mdl_filter` table — the new filters API uses `mdl_filter_active` (columns `id`, `filter`, `contextid`, `active`, `sortorder`; e.g. `filter='emoticon'`, `contextid=1` = site-wide). Which formats the filter touches: `mdl_config_plugins` `plugin='filter_emoticon'`, `name='formats'` (this site: `1,4,0` = HTML, Markdown, MOODLE).
- To kill ALL emoticon conversion: disable the filter via Site policies → Text filters (affects all contexts) — don't just blank `mdl_config.emoticons`.
- `filter/emoticon/filter.php` is a deprecated stub in 4.5+; the real code is `filter/emoticon/classes/text_filter.php` (plain `str_replace` per sequence; skips `<pre>`, `<script>`, and `nolink` spans).
- **Inline `<code>` is NOT protected** — verified 2026-10-05 by running the real pipeline: `<pre>...</pre>` passes through untouched but `<code>(grr)</code>` still becomes an image. For CS content, only block-level `<pre>` (or disabling the filter) is safe.
- **This site's word-in-parens codes were manually renamed with a `1` prefix** (`(1n)`, `(1h)`, `(1y)`, `(1heart)`, `(1martin)`) to dodge code collisions — but `(grr)` was left bare and still converts. Always read the live `mdl_config.emoticons` JSON before claiming which sequences are active (a prior session wrongly reported plain `(n)` as enabled).
- For a CS-centric site the cleanest fix is disabling `filter_emoticon` entirely (set `active=0` on the `mdl_filter_active` row for `filter='emoticon'`, then `moosh -n cache-clear`) rather than pruning sequences one by one — a fragile list that misses one code (like `(grr)`) re-breaks the problem.

### Verify what the filter actually renders (CLI recipe)

Don't trust the browser or the DB dump — run the real `format_text()` pipeline in CLI PHP:

```php
define('CLI_SCRIPT', true);
require '/var/www/html/public/config.php';
$PAGE = new moodle_page();
$PAGE->set_url(new moodle_url('/'));
$PAGE->set_context(context_system::instance());
$PAGE->set_pagetype('site-index');
echo format_text($sample, FORMAT_MOODLE, ['noclean' => true]);
```

CLI gotchas (verified 2026-10-05):
- Do NOT call `$PAGE->set_state()` (fatal "Invalid state passed") and do NOT use `moodle_page::get_top_of_tree()` (method doesn't exist).
- `get_config('emoticons')` returns a **stdClass** (Moodle decodes the JSON config for you) — for the raw JSON string use `$DB->get_record('config', ['name'=>'emoticons'], 'value')`. Legacy `get_record()` is undefined in 5.2 CLI; use `$DB->get_record()`.
- `bin2hex()` the decoded `text` values to see exact sequence bytes — MCP query output double-escapes JSON and is ambiguous about prefixes/spaces.

### Moodle AI features (5.2) — where things live

The built-in AI subsystem (provider-agnostic; this site uses the `aiprovider_openaicompatible` provider pointing at an internal endpoint):

| Location | What |
|---|---|
| `mdl_ai_providers` | Provider config (name, provider class, `enabled`, JSON `config` with apiendpoint/apikey, JSON `actionconfig` per-action settings: `generate_text`, `generate_image`, `summarise_text`, `explain_text`) |
| `mdl_ai_action_register` | Registered actions per component |
| `mdl_ai_policy_register` | Per-user AI policy acceptances (contextid-scoped) |
| `mdl_ai_action_explain_text` / `mdl_ai_action_summarise_text` | Usage log — stores full prompt + generated content (privacy-sensitive!) |
| `mdl_course.enableaitools` | Course-level AI toggle |
| `mdl_course_modules.enableaitools` | Per-activity AI toggle (NULL/0 = off, 1 = on) |
| `/var/www/html/public/ai/` | Core AI plugin: `placement/` (courseassist, editor), `classes/aiactions/`, templates |
| `/var/www/html/public/lang/en/ai.php` | UI strings: `action_explain_text` = "Explain text", `action_summarise_text` = "Summarise text", responses labeled "Generated by AI" with **Regenerate** / Copy buttons |

- **Canonical doc link for students:** `https://docs.moodle.org/en/AI`. Note: docs.moodle.org is behind a Cloudflare challenge from this pod — `curl` returns 403; don't rely on fetching it to verify.
- **Quiz AI:** the explain/summarise actions can be applied to quiz question content (e.g. in CE-Quiz the "Explain text" action is configured to give hints, not answers, via a Socratic system instruction in `actionconfig`).
- To check AI availability for an activity: `SELECT id, enableaitools FROM mdl_course_modules WHERE id=<cmid>` (NULL means the column may predate the AI upgrade — effectively off).

### Multiple AI providers: which one actually serves (Moodle 5.2)

Verified 2026-09-14. There is **no single "default" provider** — `ai/classes/manager.php::process_action()` iterates the enabled, configured providers **in the order stored in `mdl_config_plugins` (plugin `core_ai`, name `provider_order`)** and **returns the first one that succeeds** (implicit fallback chain; all-fail → error).

- `provider_order` value is a comma-separated id list; a **leading comma is a harmless artifact** of the admin reorder UI (empty slot) — `explode()` skips the empty string.
- Check the active chain: `SELECT value FROM mdl_config_plugins WHERE plugin='core_ai' AND name='provider_order'` and cross-reference `mdl_ai_providers.id`.
- Per-action settings incl. model + system prompt live in `mdl_ai_providers.actionconfig` (JSON per action: `enabled`, `settings.model`, `settings.systeminstruction`). The `settings.providerid` field is **self-referential UI metadata only** — it does not override the global order.
- `mdl_ai_action_register` logs only the **plugin** name (e.g. `aiprovider_openaicompatible`), NOT which instance served — it cannot tell you which of two instances handled a request.
- **Provider health check** (OpenAI-compatible endpoints): `curl -s -m 15 http://<host:port>/v1/models -H "Authorization: Bearer <key>"` — the `max_model_len` field distinguishes otherwise identical endpoints (e.g. 64000 vs 65536).
- This instance (2026-09-14): `dive` (id 1, `dive.ai-chat.svc.cluster.local:8000`) and `spark` (id 2, `10.37.1.72:30000`), both `aiprovider_openaicompatible`, both serving model "Socrates" (sglang); `provider_order=',2,1'` → **spark primary, dive fallback**. With both healthy, all traffic lands on spark.

## Adding a Discussion to a Forum (e.g. Q&A FAQ entries)

For `qanda`-type forums (e.g. cs1302a_26a "CE-Quiz FAQ", forum id 11, cmid 659), each discussion is one Q&A: the **question is `mdl_forum_discussions.name`** and the **answer is a `mdl_forum_posts` row** with `discussion=<id>`, `parent=0`.

Pattern (PHP bootstrap, as admin user — check the author of existing entries first, e.g. `userid=2`):

```php
$now = time();
$d = new stdClass();
$d->course = 3; $d->forum = 11;
$d->name = 'Question text?';          // shown as discussion title
$d->userid = 2; $d->groupid = -1; $d->assessed = 1;
$d->timestart = 0; $d->timeend = 0; $d->pinned = 0; $d->timelocked = 0;
$did = $DB->insert_record('forum_discussions', $d);

$p = new stdClass();
$p->discussion = $did; $p->parent = 0; $p->userid = 2;
$p->created = $now; $p->modified = $now; $p->mailed = 0; $p->mailnow = 0;
$p->subject = $d->name;
$p->message = $answerHtml;            // messageformat 4 = HTML in this forum
$p->messageformat = 4; $p->messagetrust = 0; $p->attachment = '';
$p->totalscore = 0; $p->deleted = 0; $p->privatereplyto = 0;
$wordcount = str_word_count(strip_tags($answerHtml));
$charcount = strlen(strip_tags($answerHtml));
$p->wordcount = $wordcount; $p->charcount = $charcount;
$DB->insert_record('forum_posts', $p);
```

Then set `forum_discussions.firstpost` = new post id, `timemodified`/`usermodified`, and run `moosh -n cache-clear`. Verify by reloading the forum page.

## References

- `references/moosh-plugin-list-loop.md` — Moosh plugin-list failure transcript and diagnosis
- `references/moosh-path-discovery.md` — How Moosh finds Moodle root, `-m` flag silent failure, source-level diagnosis