---
name: moodle-course-maintenance
description: "Maintain Moodle course content: rename labels/activities, update contact info, manage completion settings, diagnose hidden access restrictions."
---

# Moodle Course Content Maintenance

Bulk updates to Moodle course activities, labels, and settings.

> **`references/group-grouping-cleanup.md`** — procedure for removing stale lab/tutorial groups + quiz overrides, adding groups to groupings, and quiz group-mode/grouping settings (`course_modules` fields). Load it for any group/grouping/override work.
> **`references/activity-intro-editing.md`** — procedure for editing any activity's description text (the `mdl_<mod>.intro` + `introformat` pair): strict-replacement PHP pattern, Moodle format constants (4 = Markdown), and how to verify rendering when the live site is login-gated (`format_text()` in CLI). Load it for any "fix the description text of <activity>" request.
> **`references/rename-string-sweep.md`** — full recipe for renaming a string (tool name, URL, label…) across an entire course: site-wide occurrence sweep (labels/pages/quizzes/assigns/URLs/forum posts/question banks), the negative-lookahead PHP replace that protects `@@PLUGINFILE@@` image filenames, and the verify step. Load it for any "rename X to Y everywhere" request.
> **`references/autolink-activitynames.md`** — Moodle's `activitynames` filter auto-links any whole-word activity name in course text (why "Safe **Exam** Browser" links to the Exam quiz). Matching rules, the `<span class="nolink">` escape hatch, and how to verify a rename moves the link correctly by rendering via `format_text()` with a module context. Load it whenever a rename could create/kill/re-target an autolink, or when asked "why is this word linked to the wrong activity?".
> **`references/calendar-event-sync.md`** — why calendar event descriptions go STALE after direct DB edits to activity intros (events store a pre-rendered snapshot copy), the `quiz_refresh_events()` fix with before/after verification, and the instructor UI path (saving quiz settings regenerates events; dragging a calendar event *reschedules* the quiz). Load it whenever a course-calendar description doesn't match the activity's current text after an edit.

## Triggers

- User asks to rename, clean up, or standardize activity/label titles
- User asks to update the **description/intro text** of any activity (wiki, assign, forum, quiz, ...)
- User asks to update lecturer/contact information in course labels
- User reports a **calendar** description is out of date after an intro edit, or asks how to refresh calendar events (`references/calendar-event-sync.md`)
- User asks about completion tracking settings across activities (grade-based completion: see `references/activity-completion-mechanics.md`)
- User asks to enable/disable a text filter for specific activities (e.g. "turn off 'Convert URLs into links and images' for all the CE-Quizzes") — see "Toggling a text filter per activity" below
- User asks to diagnose why students can't access an activity
- User asks to add/remove lab or tutorial groups, quiz group overrides, or groupings

## Key concepts

### Label title vs content

- **Title** is stored in `mdl_label.name` — this is what students see in the course listing
- **Content** is stored in `mdl_label.intro` as HTML/Markdown
- To rename: `$DB->set_field('label', 'name', 'New Title', ['id' => $labelid])`
- To update content: `$DB->set_field('label', 'intro', '<content>', ['id' => $labelid])`

### Completion settings on course_modules

| Value | Meaning |
|---|---|
| `0` | No completion tracking |
| `1` | Manual self-reporting |
| `2` | Automatic (require completion) |

`completion=2` **with no criteria selected** (no grade/view rule) is effectively broken — nothing can ever be auto-completed. When the user reports "completion setting is invalid", suspect missing criteria, not the mode.

**"Receiving a grade" / "Receiving a passing grade" map to two `course_modules` columns — there is NO separate pass-threshold field on `course_modules`:**

| UI element (Moodle 5.x) | Column |
|---|---|
| ☑ Receiving a grade | `completiongradeitemnumber = 0` (NULL = not enabled) |
| ○ sub-option: "Receiving a passing grade" | `completionpassgrade = 1` (0 = any grade) |
| The pass mark itself | `grade_items.gradepass` of the activity's grade item (e.g. 30/100, 6/20) |

Quiz-specific: quiz custom rules (exhaust-attempts, min-attempts) live on the `mdl_quiz` table (`completionattemptsexhausted`, `completionminattempts`) and only activate when `completionattemptsexhausted=1`. Full mechanics, the Mock exam/midterm audit snapshot (all 3 <course> courses), duplicates/legacy anomalies, and the apply+verify workflow: **`references/activity-completion-mechanics.md`**

### Hidden access restrictions

The `availability` JSON field on `course_modules` can restrict access even when `groupmode=0` and `groupingid=0`. Always check:

```php
$cm = $DB->get_record('course_modules', ['id' => $cmid]);
echo $cm->availability; // null = no restriction
```

Common patterns:
- `{"type":"grouping","id":N}` — requires membership in grouping N
- `{"type":"group","id":N}` — requires membership in group N

Clear with: `$DB->set_field('course_modules', 'availability', null, ['id' => $cmid])`

## Workflow for bulk renaming

1. List all target activities with `get_records('course_modules')` and filter by module type. **Join to the instance table as `cm.instance = t.id` AND `cm.module = (SELECT id FROM mdl_modules WHERE name='<mod>')`** — instance ids are per-module, not globally unique; joining on `instance` alone (or `WHERE cm.instance IN (...)` without the module filter) silently matches unrelated modules with colliding ids (verified 2026-08-28: phantom rows across 2 courses).
2. **Renaming a string (not just titles)?** Find ALL occurrences first — every instance table's `name`/`intro`/`content`, quiz intros, forum post `content`, question-bank texts — and classify each hit (display name vs real uploaded file vs URL). Full recipe: **`references/rename-string-sweep.md`**.
3. Show the user current → new names as a labeled list / bullet list — **never a Markdown table** (the user is on Matrix, where tables do not render)
4. Wait for confirmation
5. Apply with `$DB->set_field()` in a loop
6. Re-scan to prove 0 leftovers, then purge cache: `cd <webroot> && moosh -n cache-clear`

## Workflow for updating contact labels

1. Read current content: `$DB->get_record('label', ['id' => $labelid])` then `echo $label->intro`
2. Identify outdated sections (lecturer assignments, office hours, TAs)
3. Show user what will change
4. Wait for confirmation
5. Write updated content with `$DB->set_field('label', 'intro', $new_content, ['id' => $labelid])`
6. Purge cache

## Pitfalls

- **`cm.instance` ids are per-module, not unique:** joining a CM to an instance table on `cm.instance = t.id` alone (or filtering `WHERE cm.instance IN (...)` with no `cm.module =` filter) silently matches other modules that reused the same numeric id. Always add the module filter (`cm.module = (SELECT id FROM mdl_modules WHERE name='<mod>')`). Verified 2026-08-28: a page/label/lti join without it returned phantom rows from course 2.
- **Plain `str_replace` on content clobbers uploaded filenames:** page/label/quiz bodies reference real files as `@@PLUGINFILE@@/OldName_file.jpg`. Renaming a tool/label string with a naive replace breaks those image refs. Use the negative-lookahead replace from `references/rename-string-sweep.md` (and/or verify file hits are classified as file refs before touching content).
- **Label title ≠ content:** The `name` column holds the display title. The `intro` column holds the body. Don't confuse them.
- **`availability` hides access restrictions:** `groupmode=0` + `groupingid=0` is NOT sufficient — check `availability` too.
- **Copy-proliferated titles:** Labels created by copying get titles like "Assignments (copy) (copy) (copy)". Clean these to "Assignment 3".
- **Cloudflare blocks CityU pages:** `scholars.<domain>` and `www.cs.<domain>` staff pages may return Cloudflare challenges. Ask the user instead of scraping.
- **Always purge cache:** User gets frustrated when they can't see changes. Run `moosh -n cache-clear` after every edit.
- **CLI `format_text()` verification needs a logged-in user — AND a context, or it returns the text 100% unfiltered (no filters applied at all).** A script without `$USER` (e.g. `format_text($text, FORMAT_HTML, ['context' => $ctx])` in a bare CLI bootstrap) emits the input unchanged — including no `urltolink` links, no `activitynames` autolinks — which can masquerade as "the filter change broke rendering" (happened 2026-09-02: disabling urltolink per-activity, the no-user render showed raw URLs *and* activity names unlinked everywhere, including in unmodified contexts and at course level). Fix: `global $USER; $USER = get_admin();` at the top of the verification script, then re-render; the same test immediately shows autolinks/URL-links again in unmodified contexts. Never conclude a filter is dead from a no-user render — always diff a modified context against an unmodified **control** context in the same logged-in run.
- **`$DB->get_record()` returns numeric columns as STRINGS:** strict comparisons like `$row->active === -1` fail (string `-1` !== int `-1`) and can print false PROBLEM flags on successful writes. Cast in assertions: `(int)$row->active === -1`.
- **LTI activities:** Check `$mod->name === 'lti'` to find JupyterHub LTI activities. Title is in `mdl_lti.name`.

## Toggling a text filter for specific activities

When asked to turn a filter on/off for specific activities (e.g. "turn off 'Convert URLs into links and images' for all the CE-Quizzes"):

1. **Map the UI filter label to the plugin name:** "Convert URLs into links and images" = `urltolink`; the activity-name autolinker = `activitynames` — they are DIFFERENT filters, and disabling one does not touch the other. For unknown labels, check the `filter/<name>/` plugin dirs and their language strings.
2. **Check current state** (table schema + value semantics in `moodle-mcp-db-query` pitfall 23): `SELECT * FROM mdl_filter_active WHERE filter = '<name>'` — a row at `contextid = 1` is the site-wide default; a row at the activity's module context is a per-activity override; **no row = inherit**.
3. **Resolve each activity's module contextid** — contextlevel 70 with `instanceid = <cmid>`, or simply `context_module::instance($cmid)->id` in PHP.
4. **Apply with the standard function**, not hand-inserted rows (identical to the UI's activity Preferences → Text filters toggle):

   ```php
   require_once('<webroot>/lib/filterlib.php');
   filter_set_local_state('urltolink', $contextid, TEXTFILTER_OFF);   // or TEXTFILTER_ON
   // filter_set_local_state(..., TEXTFILTER_INHERIT) deletes the override row
   ```
5. `cd <webroot> && moosh -n cache-clear`
6. **Verify WITH A CONTROL** — render a test string containing a raw URL (plus an activity name, if autolinks matter) via `format_text()` (requires a logged-in user + context — see the pitfall below). Check:
   - in each **modified** activity's module context → URL renders as plain text; activity autolinks (if only urltolink was disabled) still present
   - in one **unmodified** activity's context AND the course context → URL still linked
   The control proves the override is scoped to the target activities and nothing site-wide changed. (Verified 2026-09-02 on the 10 <coursecode> CE-Quizzes.)
   - **Regex trap when detecting urltolink in rendered output (bitten 2026-09-05):** do NOT match on `href="https://dive..."` to find URL-links — on this site the `activitynames` autolinks (SEB → `.../mod/page/view.php?id=191`, Midterm → `.../mod/quiz/view.php?id=130`) share the same host, so that regex matches autolinks and produced a 100% false "STILL LINKED" sweep (all 27 newly-off quizzes AND the already-off control flagged bad while the DB state was correct). Distinguish by link shape: urltolink wraps the URL itself → `<a href="URL" class="_blanktarget">URL</a>`; activitynames wraps the activity name → `<a class="autolink" title="NAME" href="...">NAME</a>`. Test for `class="_blanktarget"` (urltolink present) and separately for `class="autolink"` (autolinks survived).

## Workflow for inserting a new course section (topic)

Inserting a section mid-list requires shifting, because `section` numbers must be unique per course:

1. Insert a `course_sections` row with `section=99` (temp placeholder), `sequence=0`, `visible=1`, `visibleoncoursepage=1`, `required=0`
2. Shift ALL existing sections with `section >= target` up by 1, iterating in **descending** order (highest first) to avoid unique-key collisions
3. Set the new row's `section` to the target position (e.g., 2)
4. Purge: `cm_info::purge_coursecache($courseid)` in the PHP script, then `cd <webroot> && moosh -n cache-clear`
5. Verify with a `get_records('course_sections', ['course' => $id], 'section ASC')` listing

Pitfalls:
- **Do NOT call `core_course\output\local\cache\modinfo::purge()`** — class not found in this Moodle version (fatal). Use `cm_info::purge_coursecache()` + moosh cache-clear.
- **Shift in descending order** — ascending order causes duplicate `section` values mid-loop.
