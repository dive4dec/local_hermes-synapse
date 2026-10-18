/usr/bin/bash: _parse_usage: line 16: syntax error near unexpected token `('
/usr/bin/bash: _parse_usage: line 16: ` -?(\[)+([a-zA-Z0-9?]))'
/usr/bin/bash: error importing function definition for `_parse_usage'
/usr/bin/bash: _longopt: line 6: syntax error near unexpected token `('
/usr/bin/bash: _longopt: line 6: ` --!(no-*)dir*)'
/usr/bin/bash: error importing function definition for `_longopt'
# Group & Grouping Cleanup (CS1302 courses)

When removing stale lab/tutorial groups and their quiz overrides.

## Determine which groups are valid — read the Teaching Team label FIRST

Never assume from the previous semester. The "Teaching Team" label in each course lists the current lecturers and the lab groups they teach. Groups NOT in that list are stale and candidates for removal.

```php
$cms = $DB->get_records('course_modules', ['course' => $courseid]);
foreach ($cms as $cm) {
    $mod = $DB->get_record('modules', ['id' => $cm->module]);
    if ($mod->name === 'label') {
        $label = $DB->get_record('label', ['id' => $cm->instance]);
        if (stripos($label->intro, 'Teaching Team') !== false) {
            echo $label->intro; // parse: Lecturer: X, Lab tutor: A/B/C
        }
    }
}
```

Known mappings (verify against the label each time — changes per semester). In the
example below, instructor names are generic placeholders; on your course, look up
each tutor/TA's surname from `mdl_user` (join via `mdl_role_assignments`) and the
group labels from `mdl_groups`.
- **<course-B> (<cid>):** <instructor-1> (lectures …; labs …), <instructor-2> (…), <ta-coordinator>. Some tutorial groups are stale here.
- **<course-A> (<cid>):** <instructor-3> (lectures …; labs …), <ta-coordinator>. Some lab/tutorial groups are stale here.
- Also: class groups (C*), "helpers", and exam/makeup groups are kept even if not listed as lab groups.

## Procedure (user-specified order)

1. **List first, confirm second.** Show a table: group name, group ID, override count, reason for removal. Wait for explicit confirmation. Do NOT list from memory — query the DB immediately before presenting.
2. **Delete overrides first** (`quiz_overrides` where `groupid` = X), then `groups_members`, then the `groups` row. Removing the group first orphans the overrides.
3. **Purge cache** (`cd /var/www/html/public && moosh -n cache-clear`) — user will not see the removal otherwise.

## Related: adding a group to a grouping

- The join table is `groupings_groups` (plural on both sides) — NOT `grouping_groups` ("Table does not exist").
- Look up the grouping by name: `$DB->get_record('groupings', ['courseid' => $courseid, 'name' => 'Lab'])`.
- `$DB->insert_record('groupings_groups', ['groupingid' => $gid, 'groupid' => $gid2])` then cache-clear.

## Related: quiz group mode / grouping

- `groupmode` and `groupingid` for a quiz live on the **`course_modules`** row, not the `quiz` table. The edit form reads from the CM record; the quiz table values are NULL and irrelevant.
- Set via `$DB->set_field('course_modules', 'groupmode', 1, ['id' => $cmid])` + same for `groupingid`.
- Group mode values: 0=No groups, 1=Visible groups, 2=Separate groups.

## Pitfalls

- **Cross-semester ID rot:** group IDs from an earlier semester (or from the `moodle-cequiz-schedule-propagation` skill's reference table) may no longer exist — resolve by name at runtime.
- **Demo CE-Quiz has overrides** (e.g., quiz 56 in cs1302a_26a, quiz 192 in cs1302_26a) — include it when propagating a new group's overrides.
- **Don't confuse quiz CMs:** when listing "CE-Quiz N" changes, verify CM→quiz→name mapping by query in the same step you present the plan. In one session, E-Quiz CMs 51/77 were treated as CE-Quiz CMs and the wrong override row was swapped (Wed slot instead of Mon slot); both required a revert.
- **`$DB->get_records_sql()` fails** in this environment — use `get_records()`/`get_record()` with hash conditions.
- **`core_course\output\local\cache\modinfo::purge()` does not exist** — use `cm_info::purge_coursecache($courseid)` + moosh cache-clear.
