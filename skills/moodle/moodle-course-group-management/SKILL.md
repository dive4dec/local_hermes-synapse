---
name: moodle-course-group-management
description: "Manage Moodle course groups: create, delete, audit membership, and maintain quiz group overrides. Covers finding stale groups, removing unused groups safely, and adding new groups with consistent overrides across CE-Quizzes."
---

# Moodle Course Group Management

Manage groups and group-based quiz overrides in Moodle courses.

## Triggers

- "add a group", "remove a group", "delete group"
- "who teaches which groups", "group membership"
- "stale groups", "orphaned overrides"
- "add override for group", "remove override"
- Group/override cleanup or audit in any course

## Create a group

```php
$gid = $DB->insert_record('groups', [
    'courseid' => $courseid,
    'name'     => 'LB4',
]);
```

## Delete a group (safely)

**Order matters** — always delete dependents before the group:

1. Delete quiz overrides: `$DB->delete_records('quiz_overrides', ['groupid' => $gid])`
2. Delete group members: `$DB->delete_records('groups_members', ['groupid' => $gid])`
3. Delete the group: `$DB->delete_records('groups', ['id' => $gid])`

## Find orphaned overrides

`$DB->get_records_sql()` is broken in this environment — iterate per group ID instead:

```php
foreach ($groupIds as $gid) {
    $orphans = $DB->get_records('quiz_overrides', ['groupid' => $gid]);
    foreach ($orphans as $o) {
        $DB->delete_records('quiz_overrides', ['id' => $o->id]);
    }
}
```

## Add group overrides to CE-Quizzes

Each override needs `timelimit=2700` and `attempts=1` (must match quiz defaults — 0 does NOT inherit).

```php
$DB->insert_record('quiz_overrides', [
    'quiz'      => $quizId,
    'groupid'   => $groupId,
    'userid'    => 0,
    'timeopen'  => strtotime('2026-09-14 14:00:00'),
    'timeclose' => strtotime('2026-09-14 14:50:00'),
    'timelimit' => 2700,
    'attempts'  => 1,
]);
```

Always purge caches after: `cache_helper::purge_by_event('all_group_overrides_added')` + `moosh -n cache-clear`.

## <other-coursecode> group reference (course <other-coursecid>)

Active lab groups taught by course instructors only:

| Instructor | Groups |
|---|---|
| <Instructor-A> | CB1, CC1, LB1, LC1, LB3, LC3, LB4 |
| <Instructor-B> | CA1, LA1, LA2, LA3, LA4, LB2, LC2 |

Other: helpers (unlimited attempts). T\* tutorial groups and stale groups (CD\*, CE\*, LD\*, LE\*, LH5, LG5, LF5, CH1, CF1, CG1) have been removed.

## Pitfalls

- **Delete overrides BEFORE groups** — orphaned overrides are invisible but wasted data.
- **`$DB->get_records_sql()` fails** — iterate with `get_records()` per ID instead.
- **`timelimit=0` / `attempts=0` do NOT inherit** — set explicit values matching the quiz defaults.
- **Always run `moosh -n cache-clear`** after PHP script — `cache_helper::purge_by_event()` alone is insufficient.
