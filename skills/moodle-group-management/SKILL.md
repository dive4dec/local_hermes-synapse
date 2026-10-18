---
name: moodle-group-management
description: "Manage Moodle groups and quiz group overrides: creating groups, adding/removing overrides, cleaning stale groups, and handling group mode settings."
---

# Moodle Group and Quiz Override Management

Manage groups, groupings, and quiz group overrides in Moodle courses.

## Triggers

- Create or delete groups in a course
- Add or remove quiz group overrides
- Clean up stale groups not taught by current instructors
- Configure quiz group mode or grouping
- "remove group", "add override", "group mode", "separate groups"

## Creating a group

```php
$groupid = $DB->insert_record('groups', [
    'courseid' => $courseid,
    'name'     => 'LB4',
]);
```

## Adding quiz group overrides

For each quiz, insert one row per group in `quiz_overrides`:

```php
$DB->insert_record('quiz_overrides', [
    'quiz'      => $quizid,
    'groupid'   => $groupid,
    'userid'    => 0,
    'timeopen'  => strtotime('2026-09-14 14:00:00'),
    'timeclose' => strtotime('2026-09-14 14:50:00'),
    'timelimit' => 2700,   // MUST match quiz default, not 0
    'attempts'  => 1,      // MUST match quiz default, not 0
]);
```

**CRITICAL:** `timelimit=0` and `attempts=0` do NOT inherit from quiz defaults — Moodle uses them literally. Always set to the actual quiz values (typically 2700 and 1).

## SEN / user-level time overrides (extended exam/midterm time)

Distinct from group overrides: SEN accommodations give **each student a different** extended time (e.g. +25% / +70% / +75% + rest breaks), so use **user-level** `quiz_overrides` (one row per student per quiz) — a group override can't carry a different value per member.

```php
$DB->insert_record('quiz_overrides', [
    'quiz'      => $quizid,
    'userid'    => $uid,     // the student
    'groupid'   => 0,         // 0 = user override (not group)
    'timelimit' => 6300,     // TOTAL time incl. rest breaks, in seconds
    'attempts'  => null,      // NULL = inherit quiz default (see pitfall)
]);
```

Key points:
- **`timelimit` = the TOTAL** (base + extra% + rest breaks), in seconds. Moodle has ONE continuous timer — no "pause for break" — so fold rest into the total (e.g. 60 min base + 75% = 105 min = 6300s; 60 min + 70% + 5 min rest = 107 min = 6420s).
- **`attempts = NULL` inherits the quiz default; `attempts = 0` = unlimited.** Verified: the existing exam/midterm group overrides on course <cid> all carry `attempts=NULL` and those quizzes stay 1-attempt, so NULL preserves the one-shot rule; the override display renders `0` as "unlimited". For a time-only SEN extension, leave `attempts` NULL. (Inverse of the group-override rule above where 0 is a literal zero — for groups you must write the real value, for a time-only user override NULL is the safe choice.)
- Resolve target quizzes by name+course (**Midterm**, **Exam**, and the **"(makeup)"** variants), read each base `timelimit`/`attempts` first, and **confirm with the user whether makeup sittings get the same extension** before applying.
- **List pre-existing overrides first** — these quizzes often carry stale *group* overrides (e.g. old SEN groups s1/s2 now empty) that don't affect the students; don't delete or conflate them. Then insert only the new user rows.
- **Include the mock midterms + mock exams** (always-open, unlimited attempts, don't count toward grade) in the same pass — it lets each student **self-verify their extended timer** before the real sitting (ask them to open the mock and confirm the countdown shows their total minutes). Confirm BOTH the makeup-sitting question and the mocks question with the user before applying.
- **Populate the `reason` field** (plus `reasonformat = FORMAT_MOODLE`) on each user override with the student's name + the extension rationale — per-student accommodations get audited later, so leave a trail.
- List the exact per-student × per-quiz changes and **wait for explicit confirmation** before writing (standard house workflow).
- After: `cd <webroot> && moosh -n cache-clear`, then re-query to verify.

`mdl_quiz_overrides` columns (this build): `id, quiz, userid, groupid, timeopen, timeclose, timelimit, attempts, password` — there is **no `reviewattempt`** column (SELECTing it fails).

## Removing groups with overrides (ORDER MATTERS)

1. **Delete overrides first** — query `quiz_overrides` by `groupid` and delete rows
2. **Delete group members** — `delete_records('groups_members', ['groupid' => $gid])`
3. **Delete the group** — `delete_records('groups', ['id' => $gid])`

If you delete the group first, orphaned `quiz_overrides` rows remain pointing to non-existent group IDs.

## Finding which groups have overrides

For a given set of group IDs, iterate (avoid `$DB->get_records_sql()` which fails in this environment):

```php
foreach ($groupIds as $gid) {
    $overrides = $DB->get_records('quiz_overrides', ['groupid' => $gid]);
    // ...
}
```

## Quiz group mode and groupings

**`groupmode` and `groupingid` are stored in `mdl_course_modules`, NOT in `mdl_quiz`.**

The quiz edit form reads from `$this->_cm` (the `course_modules` record), which the parent `moodleform_mod` class uses to populate the Groups section. The `mdl_quiz` table's groupmode/groupingid fields are NULL and irrelevant.

```php
// WRONG — always NULL, even when the UI shows "Separate groups"
$q = $DB->get_record('quiz', ['id' => $quizid]);
echo $q->groupmode;

// CORRECT — this is what the quiz edit form reads
$cm = $DB->get_record('course_modules', ['id' => $cmid]);
echo $cm->groupmode;   // 0=No groups, 1=Visible groups, 2=Separate groups
echo $cm->groupingid;  // grouping id, or 0 for none
```

- `groupmode`: 0 = No groups (`NOGROUPS`), 1 = Visible groups (`VISIBLEGROUPS`), 2 = Separate groups (`SEPARATEGROUPS`)
- `groupingid`: links to `mdl_groupings.id`, 0 = no grouping

If the Groups section is missing from a quiz edit form, check `course_modules.groupmode` — if it's 0 (No groups) and the course isn't forcing group mode, the section may be hidden by JS (`hideIf` in `moodleform_mod.php`). To make it visible, set `groupmode` to 1 or 2 on the `course_modules` row.

### Groupings

Groupings organize groups into sets (e.g., "Lec", "Lab"). Create via:

```php
$giding = $DB->insert_record('groupings', ['courseid' => $courseid, 'name' => 'Lec']);
$DB->insert_record('grouping_groups', ['groupingid' => $giding, 'groupid' => $groupid]);
```

**The join table is `grouping_groups`** (singular "grouping"), NOT `groupings_groups`.

### Listing groups in a grouping

```php
$members = $DB->get_records('grouping_groups', ['groupingid' => $groupingId]);
foreach ($members as $m) {
    $g = $DB->get_record('groups', ['id' => $m->groupid]);
}
```

### Adding groups to an existing grouping

```php
$DB->insert_record('grouping_groups', ['groupingid' => $groupingId, 'groupid' => $groupId]);
```

- **Follow-up confirmation email (recurring):** after the overrides are applied, the user gets an **individual email per student** (each student's numbers differ). Approved structure (user-approved 2026-10-06, mirrors the instructor's own CS2310 template): Subject `[COURSECODE] Midterm — your time extension and exam policies`; sections `Your time extension` (per-student % + per-sitting totals, rest folded in, ending "calculations are tentative and may be changed if there are mistakes") → `Please check` → `Device policy` (no personal laptops — cannot be inspected, privacy; use provided machines) → `No time extension for CE-Quiz` (CE-Quizzes = TBL in-class assignments, team discussion not isolated rooms; SEN students encouraged to use student helpers). In `Please check`: ask them to confirm the venue and time **on the course homepage** — **do NOT hardcode the venue or times into the email** (user correction 2026-10-06: "do not put the venue and time. Ask students to check on the course homepage"); also check Midterm + both mocks for question/instruction/answer errors; note the final Exam is not yet available for checking. Breaks-on-top phrasing: "…= 204 min, plus two 5-min breaks (at 45 and 90 min) = 214 minutes total"; breaks-within phrasing: "…= 210 minutes total (breaks within the total)". Totals MUST match the `timelimit` applied in the override. Send flow per the `email-student-group` skill (draft → confirm → raw ESMTP, per-student, ~1s pacing).
- **Resolving a student's exam venue from group/grouping (course <cid>, 2026):** exam venues are **labels carrying group/grouping availability** on the `course_modules` row (NOT quiz availability): `cm.availability = {"op":"&","c":[{"type":"group","id":47}]}` or `[{"type":"grouping","id":6}]`; the label's `intro` holds "Venue: … Invigilators: …". Student's groups (`groups_members` where `groups.courseid = <cid>`) → their grouping(s) via `grouping_groups` → the label whose CM availability references it. Verified 2026-10-06: m1 (gid 47) → cmid 122 "<hall> B7701"; m2 (gid 48) → cmid 123 "<hall> G7510 (NOT B7510)"; **SEN grouping 6 (= groups s1/s2/s3, gids 50/74/395) → cmid 129 "<hall> B7530", <Staff-Zhao> (Chief)** — all SEN students share that one venue. The m3–m8 exam groups are typically still empty at planning time (their venue labels may not exist yet), and a warning label ("You have not been arranged a midterm venue…") targets unassigned students. The midterm quiz's own CM carries `groupmode=1, groupingid=7` — but the venue is the *label*, not the quiz.

## Determining which groups to keep

When asked to clean up groups, **check the Teaching Team label** in the course to determine which groups are actually taught by the current instructors:

1. Find the Teaching Team label: search `mdl_label` for `intro` containing "Teaching Team"
2. Parse the label to extract lab tutor assignments (e.g., "Lab tutor: T01/TA1/T02")
3. Only groups listed in the Teaching Team (plus "helpers") should be kept

Never assume group naming patterns — always verify against the actual Teaching Team label for each course.

## Listing students with no group

Common ask: "which enrolled students aren't in any course group?" (5.x columns — see `moodle-mcp-db-query` skill for the full quirk list):

```sql
SELECT u.id, u.firstname, u.lastname, u.email
FROM mdl_user u
WHERE u.id IN (
  SELECT ue.userid
  FROM mdl_user_enrolments ue
  JOIN mdl_enrol e ON e.id = ue.enrolid AND e.courseid = <courseid>
  JOIN mdl_role_assignments ra ON ra.userid = ue.userid
  JOIN mdl_context c ON c.id = ra.contextid AND c.contextlevel = 50 AND c.instanceid = <courseid>
  JOIN mdl_role r ON r.id = ra.roleid AND r.shortname = 'student'
  LEFT JOIN mdl_groups_members gm ON gm.userid = ue.userid
  LEFT JOIN mdl_groups g ON g.id = gm.groupid AND g.courseid = <courseid>
  WHERE ue.status = 0 AND gm.userid IS NULL
)
ORDER BY u.lastname, u.firstname;
```

Pitfalls:

- A student with **multiple active enrolment plugins** (e.g. manual + LTI) produces multiple `mdl_user_enrolments` rows — use `COUNT(DISTINCT u.id)` for counts, or the total will exceed the roster size.
- Course scope on groups is `mdl_groups.courseid` (NOT `course`).
- LTI **test accounts** (email `e_*e_lti_test@<domain>`, username `enrol_lti…`) regularly show up as the only unassigned users — flag them separately rather than presenting them as real students.
- This counts membership in *any* course group. If the user means a specific grouping (e.g. project groups), also check `mdl_grouping_groups` + that grouping's members.
- **The list changes between asks** — the LTI group sync and manual assignments run in the background; if the user asks the same question twice, re-run the query rather than reusing a previous answer.

## Purging caches

After any group or override changes:

```bash
cd <webroot> && moosh -n cache-clear
```

Always run `moosh -n cache-clear` — PHP script cache purges alone are insufficient.

## Pitfalls

- **Delete overrides before groups** — orphaned rows otherwise remain in `quiz_overrides`.
- **Demo CE-Quiz needs overrides too** — don't forget it when adding overrides to all CE-Quizzes.
- **`timelimit=0` and `attempts=0` are literal zeros** — they do NOT inherit from the quiz. Set them to the actual quiz values.
- **`$DB->get_records_sql()` fails** — iterate with `get_records()` instead.
- **Quiz group settings can appear in UI despite DB being NULL** — Moodle serves cached values or inherits from course `defaultgroupingid`. Always `moosh -n cache-clear` after changes.
- **`grouping_groups` table name** — the join table between groupings and groups is `grouping_groups` (singular), NOT `groupings_groups`. Using the wrong name causes "Error reading from database".
- **Different courses have different teaching teams** — <other-coursecode> is taught by <Instructor-A> and <Instructor-B>; <coursecode> is taught by <Instructor-C>. Don't assume the same groups should exist across courses. Always check the Teaching Team label in each course.