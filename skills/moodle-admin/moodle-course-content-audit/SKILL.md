---
name: moodle-course-content-audit
description: "Read-only consistency audit of a Moodle course: dump all text content (labels, pages, quiz intros, forums, assignments, URLs, LTI, announcements), cross-check schedules/dates/links/grades/groups for inconsistencies, report by severity. Use for 'check course X for issues/inconsistent content'."
---

# Moodle Course Content Audit (read-only)

Systematic inconsistency check across all text content of a course. Triggered by requests like "check if there are any issues / inconsistent content in course X".

## Triggers

- "Check course X for issues / inconsistencies / stale content"
- Pre-semester review of a freshly cloned or restored course
- "Does the course content match the announcement / schedule?"

**Read-only by design.** List findings; the user confirms fixes per the standing workflow (list exact changes → wait → apply).

## Workflow

### 1. Structure dump (MCP read-only SQL, see `moodle-mcp-db-query`)

```sql
-- sections in display order
SELECT id, name, sequence FROM mdl_course_sections WHERE course = <cid> ORDER BY section;
-- every activity + group mode
SELECT cm.id, cm.section, m.name AS modulename, cm.visible, cm.groupmode, cm.groupingid
FROM mdl_course_modules cm JOIN mdl_modules m ON m.id = cm.module
WHERE cm.course = <cid> ORDER BY cm.section, cm.id;
```

### 2. Full text dump (PHP bootstrap — content is longtext, dump to a file)

One PHP script (pattern in `moodle-db-access`) that writes every label intro, page content, quiz name+intro+timeopen/timeclose, forum name+intro, assignment intro+duedate, URL name+url, choicegroup intro, LTI names, groups, groupings to `/tmp/<course>_dump.txt`, then `read_file` the dump. Strip HTML with `html_entity_decode(strip_tags(...))` + whitespace collapse, but ALSO keep raw variants for link extraction (`preg_match_all('/href="([^"]+)"/')`) and for inspecting mangled markdown in label names.

### 3. Cross-checks (the actual audit)

Run these classes of checks and record outliers:

1. **Copy-paste errors** — forum/assignment/label intros that mention the wrong assessment (e.g. "Project FAQ" intro still saying "Clarifications for CE-Quiz"; a "(copy)" label left in a section).
2. **Broken links** — every `href` in content: `mod/resource/view.php?id=N` → verify `mdl_resource.id=N` exists IN THIS COURSE (course-relative `../` links resolve to the course dir). Absolute URLs → `curl -sk -o /dev/null -w '%{http_code}'` — remember the site base path `/cs1302a-eq` (bare root paths 404).
3. **Date/time consistency** — announcement times vs quiz `timeopen`/`timeclose` (e.g. welcome post "18:30-19:30" vs quiz window ending 19:45); verify weekdays with `date -d <ts> +%A`; midterm lock labels ("locked until X") vs quiz timeopen.
4. **Schedule vs grouping** — CE-Quiz group overrides must match the lab-section schedule (see `moodle-cequiz-schedule-propagation`); groups present in the Teaching Team label vs groups that actually have overrides (orphan groups = e.g. a T03 with no overrides).
5. **Dangling deleted-group refs** — `groupings_groups` rows whose `groupid` has no `groups` row (harmless but messy; show per-grouping counts).
6. **Placeholder/unfinished content** — labels with "???" / "..." content, visible URL resources with empty `url`, "Venue" labels visible to all students while the announcement says "venue to be announced".
7. **Gradebook** — `aggregationcoef2` sum over visible items (must be 1.0 by design; see `moodle-gradebook`); compare display scale (`grademax` of the course item) with the sibling course (e.g. /1025 raw vs /100) — FLAG, don't fix.
8. **Naming consistency** — mock-exam/quiz naming (25A vs 2025), grade item names vs quiz names.
9. **Grouping sanity for live activities** — choicegroup registration: map each option's `groupid` → group name, verify 100% coverage / no dups / no missing (student-facing, highest risk); check group members (LTI test users like `*LTITEST` + staff are probing artifacts, not real registrations).
10. **Announcement vs course structure** — the welcome announcement references sections/pages (e.g. "Syllabus section") that must actually exist; it also carries the grade percentages to compare against the gradebook weights.

### 4. Report format (user-approved shape from the 2026-08-27 audit)

Group findings by severity with emoji headers:
- **🔴 Clear content errors** (wrong text, broken links) — quotable, with CM/forum ids
- **🟠 Schedule / time discrepancies** — needs a user decision, present both sides
- **🟡 Gradebook / structural** — "needs your confirmation"
- **🟢 Housekeeping / cleanup** — low student impact
Then end with: "Quick wins I'd fix immediately: … Decisions needed from you: … Want me to fix the quick wins now (I'll list each exact change before applying), or just the specific ones you pick?"

Include CM ids / forum ids / quiz ids / override ids for every finding so fixes are one-line commands. No fixes during the audit.

## Pitfalls

- **MCP `query` parameter is named `query`** (not `sql`), 100-row cap — aggregate or paginate. Keyword filter blocks `created`/`deleted`/`timecreated` column names.
- **`mdl_quiz_overrides` has NO `course` column** — query per quiz id (`WHERE quiz = ?`).
- **`mdl_grade_items` is plural** (singular `grade_item` in PHP `get_records` → bare "Error reading from database"); no `weight` column (it's `aggregationcoef2`); `mdl_grade_categories` has no `sortorder`/`idnumber`/`letterbox`. See `moodle-gradebook` → `references/grade-items-schema.md`.
- **`mdl_forum_discussions` title is `name`** (not `subject`); the news-forum post's `firstpost` → `forum_posts.message` holds the announcement text.
- **PHP `get_records` on wrong table/column fails silently with a bare error** — if a script stops early mid-dump, isolate the failing section by sections instead of re-running everything.
- **Choicegroup options have no `name` column** — the displayed label is the group name; verify via `groups.name`. `mdl_choicegroup_answers` does not exist.
- **Don't report the CE-Quiz schedule as wrong from one quiz** — the whole 9-week pattern must match the template (see the cequiz-schedule-propagation skill) before flagging.
- **Section numbering ≠ topic numbering** (topic "105" can be display position 1); use the `section` number, not `course_sections.id`.
