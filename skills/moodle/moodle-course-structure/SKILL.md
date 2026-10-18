---
name: moodle-course-structure
description: "Maintain Moodle course structure: group/grouping lifecycle, quiz group mode (course_modules), quiz group-override consistency audits, and inserting/moving course topics (sections). Teaching Team label is the source of truth for who teaches which groups."
---

# Moodle Course Structure Maintenance

Groups, groupings, quiz group modes, and course topics. Covers the full lifecycle: create, rename, add to grouping, audit, remove.

## Triggers

- Create/rename/delete groups or groupings; "add group X to grouping Y"
- Set or align quiz group mode / grouping across multiple quizzes
- "Are the CE-Quiz overrides consistent?" — audit group overrides
- Add, rename, or move a course topic (section)

## Rule 1: Teaching Team label is the source of truth

Each course has a "Teaching Team" label listing the lecturer's lecture sections (CA1, CB1…) and lab-tutor sections (LA1/LB1/T01…). **Different courses have different instructors — never assume one course's instructor→group mapping applies to another.** Always read the label before adding/removing groups or overrides:

```php
$cms = $DB->get_records('course_modules', ['course' => $courseid]);
foreach ($cms as $cm) {
    $mod = $DB->get_record('modules', ['id' => $cm->module]);
    if ($mod->name === 'label') {
        $label = $DB->get_record('label', ['id' => $cm->instance]);
        if ($label && stripos($label->name, 'Teaching Team') !== false) {
            echo $label->intro;  // lists lecturer + lab tutor sections
        }
    }
}
```

## Rule 2: Group / grouping lifecycle

- Create group: `$DB->insert_record('groups', ['courseid' => $cid, 'name' => 'X'])`
- Create grouping: `$DB->insert_record('groupings', ['courseid' => $cid, 'name' => 'X'])`
- Add group to grouping: the join table is **`groupings_groups`** (plural on BOTH sides — NOT `grouping_groups`):
  `$DB->insert_record('groupings_groups', ['groupingid' => $groupingId, 'groupid' => $groupId])`
- Rename group: `$DB->set_field('groups', 'name', $new, ['id' => $gid])`. For ordered names (group0…group99) **zero-pad** (group00…group09) — Moodle's groups list is alphabetical, so zero-padding is what makes numeric order display correctly.
- **Remove a group in this order:** (1) its `quiz_overrides`, (2) `groups_members`, (3) the `groups` row. Wrong order leaves orphaned overrides that pollute later audits. Verify override count per group first (`get_records('quiz_overrides', ['groupid' => $gid])`).

## Rule 3: Quiz group mode lives on `course_modules`, not `quiz`

The quiz edit form reads `$this->_cm` — `groupmode`/`groupingid` are on the **`course_modules`** record. Setting them on the `quiz` table has no effect. This explains UI/DB "mismatches" where the form shows a grouping the quiz table doesn't have.

- `groupmode`: 0 = No groups, 1 = Visible groups, 2 = Separate groups
- To change:
  ```php
  $DB->set_field('course_modules', 'groupmode', 1, ['id' => $cmid]);
  $DB->set_field('course_modules', 'groupingid', $groupingId, ['id' => $cmid]);
  ```
- To align all quizzes to a reference quiz's settings: list CM id + quiz name + groupmode + groupingid for every quiz of that type, diff, and list only the outliers for confirmation.
- **Pitfall — CM id ≠ quiz id, and differs per course.** Always re-query and echo the quiz NAME inside the script that applies changes. (One session updated CM 51/77 believing they were CE-Quizzes; they were E-Quizzes in a different course and had to be reverted.)
- Grouping IDs also differ per course (e.g. "Lec" = 3 in one course, 7 in another, 23 in a third) — never carry an ID across courses.

## Rule 4: Auditing override consistency

Before diagnosing "inconsistent overrides", print **every** override (id, group, DOW, time) for **every** quiz in scope — do not extrapolate a pattern from one quiz. In one session only the Demo CE-Quiz had a wrong group assignment; CE-Quiz 1–9 were all correct. Fix only actual outliers, with the exact override IDs, after user confirmation.

## Rule 5: Inserting / moving course topics (sections)

Sections live in `mdl_course_sections` keyed by `course` + `section` (the displayed order). To insert a new topic at position N:

1. Insert the new section with `section=99` (high placeholder), `visible=1`, `sequence=0`, `name='Project'`.
2. Update all existing sections with `section >= N` to `section+1`, **in descending order** (16→17, 15→16, …, N→N+1) to avoid duplicate section numbers mid-shift.
3. Set the new section's `section` from 99 to N.

Activities move with their topic automatically: `course_modules.section` stores the `course_sections.id` (which is unchanged), so nothing else needs touching.

## Verify + cache (non-negotiable)

Chain the cache clear into the same command line as the script — the user has had to remind repeatedly:

```bash
php /tmp/script.php 2>&1 && cd /var/www/html/public && moosh -n cache-clear
```

Afterwards re-run a read-only verification script that prints the final state (group list, section order, override table) and confirms it matches intent before reporting done.

## Rule 6: Midterm venue / invigilator labels (cs1302a_26a, course 3)

The per-group **midterm venue + invigilator** labels live in the **orphan section 21** (the section that actually holds the Midterm quizzes + rules page). The section *row* literally named "Midterm Quiz" (`course_sections.id=21`, `section=13`) is a **different, hidden, EMPTY** row — do not confuse them.

The venue labels are `label` activities, **group-gated via `course_modules.availability`** (a `{"type":"group","id":<gid>}` rule), one per exam group. Map (label cmid = `course_modules.id`; label row id = `cm.instance`):

- cmid **122** = group **m1** (gid 47) — Venue **LI 4109**
- cmid **123** = group **m2** (gid 48) — Venue **LI 4208**
- cmid **124** = group **m3** (gid 49)
- cmid **125** = group **m4** (gid 51)
- cmid **126** = group **m5** (gid 52)
- cmid **127** = group **m6** (gid 53)
- cmid **128** = group **m7** (gid 76)
- cmid **129** = **grouping 6** (not a single group)
- cmid **121** = profile-gated (`firstname=Test` AND `lastname=Student`) — the sample/placeholder card, not a real group
- cmid 118 = hidden "exam rules" page; cmid 119 = hidden intro label; cmid 120 = red "no venue arranged" warning

Label format (moodle format 0, HTML):
```
<ul><li>Venue: <strong>LI 4109</strong></li>
<li>Invigilators: <strong>NAME (Chief)</strong></li></ul>
```
(When a second invigilator is named, format as `<strong>CHIEF (Chief), SECOND</strong>`.)

**To update invigilators for a group:** find the cmid whose availability `group.id` = the group's `groups.id`; read `label.intro` via `JOIN {label} ON label.id = cm.instance` (key on **label id**, not cmid); `str_replace` the `Invigilators: ... (Chief), ...` placeholder (must appear exactly once — verify `substr_count==1`); `set_field('label','intro',...)` + bump `label.timemodified`; then `purge_caches()`. ⚠️ `core\output\cacheable::reset_cm_content_hash` does NOT exist on this build (throws "Class not found") — use `purge_caches()` (or `moosh -n cache-clear`).

## Deployment reference

- User workflow for all of the above: **list the exact changes, wait for explicit confirmation, then apply.**
- Courses: cs1302_25b (id=2), cs1302a_26a (id=3), cs1302_26a (id=7).
- CE-Quiz quizzes: course 2 → 19–37 (demo 19, CE odds 21–37); course 7 → 192–210 (demo 192, CE evens 194–210); course 3 → 56–74 (demo 56, CE evens 58–74).
- User's Obsidian vault: `/var/www/moodledata/.hermes/obsidian-vault/` — when the user says "write it to obsidian", write a `.md` note there (do not go hunting for the path).
