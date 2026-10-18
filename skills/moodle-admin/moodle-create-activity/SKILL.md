---
name: moodle-create-activity
description: "Create Moodle course activities (forum, quiz, assignment, etc.) via direct DB inserts when moosh activity-add fails due to Moodle 5.x theme initialization guards."
---

# Create Moodle Activities Programmatically

## When to use this skill

Trigger when the user asks to add a new activity (forum, quiz, assignment, label, etc.) to a course section and `moosh activity-add` is not available or fails.

## Why moosh activity-add fails in Moodle 5.x

`moosh activity-add` uses Moodle's test data generator, which initializes the theme/rendering pipeline. Moodle 5.x throws a `codingerror` when output is initialized during activity creation:

```
Coding error detected: Creating a mod_<module> activity initialised the theme and output!
```

`forum_add_instance()` via `moosh php-eval` also fails — it expects a pre-existing `course_modules` record and tries to resolve its context, which triggers the same output initialization.

## Reliable approach: direct DB inserts

### Step 1: Find the module ID and section

```php
$modid = $DB->get_field('modules', 'id', ['name' => 'forum']);
$section = $DB->get_record('course_sections', ['course' => $courseid, 'section' => $sectionnum]);
```

### Step 2: Insert course_modules

```php
$cm = new stdClass();
$cm->course = $courseid;
$cm->module = $modid;
$cm->section = $section->id;  // course_sections.id, NOT section number
$cm->visible = 1;
$cm->intro = '';
$cmid = $DB->insert_record('course_modules', $cm);
```

### Step 3: Insert the activity instance

```php
$instance = new stdClass();
$instance->course = $courseid;
// ... activity-specific fields ...
$instanceid = $DB->insert_record('forum', $instance);
```

### Step 4: Link CM to instance

```php
$DB->set_field('course_modules', 'instance', $instanceid, ['id' => $cmid]);
```

### Step 5: Add CM to section sequence

```php
$section = $DB->get_record('course_sections', ['id' => $section->id]);
$section->sequence = ($section->sequence ? $section->sequence . ',' : '') . $cmid;
$DB->update_record('course_sections', $section);
```

### Step 6: Create context

```php
require_once($CFG->dirroot . '/lib/accesslib.php');
context_module::instance($cmid, true);
```

### Step 7: Purge cache (both required)

```bash
rm -rf <datadir>/cache/local_file/core_coursemodinfo/{courseid}-c-cache/
cd <webroot> && moosh -n cache-clear
```

## Forum-specific field reference

```php
$instance->type = 'qa';           // 'qa', 'news', 'single', 'general'
$instance->name = 'Forum Name';
$instance->intro = 'Description';
$instance->introformat = 1;       // 1 = FORMAT_HTML
$instance->assessed = 0;
$instance->maxattachments = 0;
$instance->maxbytes = 0;
$instance->forcesubscribe = 0;    // 0 = optional subscription
$instance->autosubscribe = 0;     // 0 = don't auto-subscribe all users
```

## Wiki-specific field reference

See `references/wiki-activity.md` for the full detail: group-mode access semantics (SEPARATEGROUPS vs VISIBLEGROUPS), the proven two-phase peer-review pattern (flip `course_modules.groupmode` 1→2 at the review deadline, then PREVENT `mod/wiki:editpage` for students at the module context at the end deadline), comment gating via `config.usecomments`, and the missing group-dropdown navigation limitation (link each group page directly with `&wid=<wikiid>&group=<groupid>&title=<firstpagetitle>`).

Quick field reference:

```php
$instance->name = 'Group Project Pages';
$instance->intro = '...';
$instance->introformat = 1;      // FORMAT_HTML
$instance->firstpagetitle = 'Project';
$instance->wikimode = 'collaborative';   // one wiki per group (use 'individual' for one per user)
$instance->defaultformat = 'html';       // one of: html, creole, nwiki
$instance->forceformat = 1;
$instance->editbegin = 0;        // decorative — NEVER enforced by module code
$instance->editend = 0;          // decorative — NEVER enforced by module code
// On the course_modules row:
$cm->groupmode = 1;              // 1 = SEPARATEGROUPS; flip to 2 (VISIBLEGROUPS) to open cross-group viewing
$cm->groupingid = 25;            // restrict to a grouping
```

## Pitfalls

- **`course_modules.section` must be `course_sections.id`** (NOT the section number). For example, section number 1 in course <other-coursecid> has `id=<helpergid>`, so use `89`. Moodle's integrity check will fail if this is wrong.
- **`course_sections.sequence` must include the new CM id**, or the activity won't render in the UI even though it exists in the DB. Append it: `$section->sequence = $section->sequence . ',' . $cmid`.
- **Context must be created explicitly**: `context_module::instance($cmid, true)` — without it, capabilities and permissions won't work.
- **`moosh -n cache-clear` alone is insufficient**. You must also delete the file cache: `rm -rf <datadir>/cache/local_file/core_coursemodinfo/{courseid}-c-cache/`.
- **`insert_record` may return an existing ID** if the autoincrement counter wrapped. Verify by querying the returned ID — if it has pre-existing data, the ID was reused.
- **Stale CMs from failed attempts.** A failed `moosh activity-add` leaves orphaned `course_modules` records. Check for duplicates if the user sees wrong content.
- **When copying forum discussions between courses**, update `forum_discussions.firstpost` to point to the NEW post IDs. Moodle's SQL does `JOIN {forum_posts} ON fp.id = d.firstpost` — if `firstpost=0`, the discussion is silently filtered out. Also set `usermodified` to a valid user id.
- Forum type values: `qanda` (NOT `qa`), `general`, `single`, `news`
- **Best approach**: Use the Moodle UI when possible. It handles all caching, contexts, sequences, and foreign keys correctly.
