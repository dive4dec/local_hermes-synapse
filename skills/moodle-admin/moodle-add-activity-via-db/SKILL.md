---
name: moodle-add-activity-via-db
description: Creating Moodle activities (forum, quiz, assignment, etc.) via database or PHP API with proper cache handling.
---

# Creating Moodle Activities via moosh php-eval

**Do NOT insert `course_modules` and activity table records directly via SQL.** Moodle caches module info in `core_coursemodinfo` file cache, and direct DB inserts don't rebuild it. The activity will never appear in the UI.

## Correct approach

Use Moodle's PHP API through `moosh -n php-eval`:

```php
require_once($CFG->dirroot . '/mod/ACTIVITY/lib.php');

$modform = new stdClass();
$modform->course = $courseid;
$modform->name = 'Activity Name';
$modform->intro = 'Description';
$modform->introformat = 1;
$modform->sectionnum = $section_number;
// ... activity-specific fields ...

$cm = null;
ACTIVITY_add_instance($modform, $cm);
```

## If direct DB insert is unavoidable

1. Get module id: `$DB->get_field('modules', 'id', ['name' => 'ACTIVITY'])`
2. Insert `course_modules` record (section = section number, not section id)
3. Insert activity table record
4. Link CM to instance: `$DB->set_field('course_modules', 'instance', $activityid, ['id' => $cmid])`
5. Create context: `context_module::instance($cmid, true)`
6. **Purge file cache**: `rm -rf <datadir>/cache/local_file/core_coursemodinfo/{courseid}-c-cache/`
7. Run `moosh -n cache-clear`

## Forum-specific fields

```php
$forum->type = 'qanda';        // Q&A mode (NOT 'qa')
$forum->forcesubscribe = 0;    // Optional subscription
$forum->autosubscribe = 0;
```

## Pitfalls

- **`moosh activity-add`** uses Moodle's test generator which triggers theme initialization errors in CLI context — it doesn't work
- **`add_module()`** function doesn't exist — use `add_moduleinfo()` if needed
- **`forum_add_instance()`** expects `$modform->coursemodule` to be set to a valid CM id, but the CM doesn't exist until the instance is created — a chicken-and-egg problem. Use the activity generator instead.
- Always purge `core_coursemodinfo` cache after any direct DB changes to course modules
- Forum type values: `general`, `single`, `qanda` (NOT `qa`)
- Forum instance IDs can collide with pre-existing entries after course clones
- **`course_modules.section`** must be the `course_sections.id` (not the section number). For example, section number 1 in course <other-coursecid> has `id=<helpergid>`, so use `89`.
- **`course_sections.sequence`** must include the new CM id, or the activity won't render. Append it: `$DB->set_field('course_sections', 'sequence', $old_sequence . ',' . $cmid, ['id' => $section_id])`.
- **Lesson learned**: If API calls fail, use the Moodle UI to create the activity. It handles all caching, contexts, and sequences correctly.

## Copying forum discussions/posts between forums

Verified working on this site 2026-08-23 (FAQ post copied <coursecode> forum 11 → <other-coursecode> forum 12, new discussion 22). Use a PHP bootstrap script (MCP query tool is read-only).

1. Read the source discussion + its non-deleted posts (`deleted = 0`). For a FAQ-style discussion expect exactly 1 root post; its id must equal the discussion's `firstpost`.
2. Insert into `forum_discussions`: `course` = target course id, `forum` = target forum id, `name` = title (NOT `subject` — column doesn't exist), `firstpost` = 0 initially, `userid`/`usermodified` = author, `groupid` copied from source (usually -1), `assessed` = 1, `timemodified` = `time()`, `pinned` = 0, `timelocked` = 0, `timestart`/`timeend` = 0.
3. Insert into `forum_posts` with `discussion` = new discussion id (NOT `discussionid`), `parent` = 0, copy `subject`, `message`, `messageformat`, `messagetrust`, `attachment`; `created`/`modified` = `time()`; `deleted` = 0; `mailnow`/`mailed`/`totalscore`/`privatereplyto` = 0.
4. **Set `firstpost` to the new post id** — if left at 0, the discussion list silently filters the discussion out.
5. **Verify with the exact list-view JOIN** — the forum page lists discussions via `SELECT ... FROM {forum_discussions} d JOIN {forum_posts} p ON p.discussion = d.id WHERE d.forum = ? AND p.parent = 0`. Run that query (MCP query tool is fine) and confirm the new row appears with a valid `firstpost`. Also check the forum's CM `groupmode` — if >0, group visibility applies.
6. `moosh -n cache-clear` — forum lists don't use the coursemodinfo cache, but run it as the standard post-DB-change rule.

### Pitfalls

- **Do NOT verify CLI-side with `forum_get_discussions()`** — its first argument is a **`$cm`** (course_modules record), not the forum instance, and it requires a logged-in user. This build has **no `login_as()`** (checked: not in `lib/moodlelib.php`, no alternative in `lib/`), so CLI calls return 0 discussions and mislead you into thinking the copy failed. Run the raw JOIN instead.
- **MCP keyword filter:** `mdl_forum_posts.created`/`deleted` column names trigger "dangerous keyword" rejections — select without them, or use PHP. (Covered in `moodle-mcp-db-query` skill.)
- Copy `message` byte-for-byte (no reformatting); keep `messageformat` (4 = Moodle markdown) and `messagetrust`.
