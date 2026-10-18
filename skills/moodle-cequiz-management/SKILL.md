---
name: moodle-cequiz-management
description: "Manage CE-Quiz (Collaborative E-Quiz) timing and group overrides in Moodle. Maps lab sessions to quiz override windows based on the weekly lab schedule and semester schedule."
---

# Moodle CE-Quiz Management

Manage CE-Quiz timing and group overrides. CE-Quizzes are weekly lab-based formative assessments where each lab section gets its own quiz window via group overrides.

## Triggers

- User asks to fix CE-Quiz timing or group overrides
- "CE-Quiz 1 timing", "group overrides", "quiz schedule"
- Lab sessions need to be mapped to quiz override windows
- New semester starts and quiz times need updating

## Key concepts

- **CE-Quiz N runs in the week of Lab N** — CE-Quiz 1 = Week 3 (Lab1 week), CE-Quiz 2 = Week 4 (Lab2 week), etc.
- **E-Quiz N runs the week BEFORE CE-Quiz N** — one week early. E.g., CE-Quiz 1 in Week 3 → E-Quiz 1 in Week 2.
- **Lab0** is a demo CE-Quiz with no group overrides (single global window, all groups share the same time)
- Each lab section is a **Moodle group** with its own time override (50-minute window)
- **Override `timelimit` and `attempts` MUST match the quiz defaults** — set `timelimit=2700` (45 min) and `attempts=1`. Setting `timelimit=0` does NOT inherit — it breaks the override.
- **Helpers group** (id=<helpergid>) gets a special override: opens **one week before** the quiz, unlimited attempts (`attempts=0`), same timelimit.
- **Catch-up weeks** — Weeks 5/6/7/8 have shifted Thursday sessions. CE-Quiz 3 (Week 5) has no Thu labs → Thu labs are added as catch-up in Week 6. CE-Quiz 4 → catch-up in Week 7. CE-Quiz 5 → catch-up in Week 8.

## Workflow

### 1. Read the schedules from Obsidian vault

```bash
<datadir>/.hermes/obsidian-vault/<coursecode>.Weekly.Lab.Schedule.md
<datadir>/.hermes/obsidian-vault/<coursecode>.Semester.Schedule.md
```

### 2. Identify which groups have lab sessions that week

Match the week number from the semester schedule to the lab session times in the weekly schedule. Each group name (T01, LA2, LB1, etc.) maps to a Moodle group ID.

### 3. Delete stale overrides and create new ones

Use a Moodle CLI script (see steps below). Always delete old overrides first, then create new ones.

### 4. Update global quiz window

Set `timeopen` to Monday 00:00 and `timeclose` to Sunday 23:59 of the relevant week.

## Creating groups

Missing groups (e.g., new lab sections this semester) need to be created first:

```php
define('CLI_SCRIPT', TRUE);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/fix.php';
require_once('/var/www/html/config.php');

$data = (object) [
    'courseid' => <cid>,        // <coursecode>
    'name' => 'T01',
    'description' => '',
    'descriptionformat' => FORMAT_MOODLE,
];
$id = $DB->insert_record('groups', $data);
cache_helper::purge_by_event('changesincourse');
```

## Setting overrides

```php
define('CLI_SCRIPT', TRUE);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/fix.php';
require_once('/var/www/html/config.php');
date_default_timezone_set('Asia/Hong_Kong');

$quizId = 58;

// Delete existing overrides
$DB->delete_records('quiz_overrides', ['quiz' => $quizId]);

// Update global window
$DB->set_field('quiz', 'timeopen', strtotime('2026-09-14 00:00:00'), ['id' => $quizId]);
$DB->set_field('quiz', 'timeclose', strtotime('2026-09-20 23:59:00'), ['id' => $quizId]);

// Group ID lookup — read from mdl_groups
$g = ['T01'=>93, 'T02'=>94, 'T03'=>292, 'TA1'=>95, 'LA1'=>64, 'LA2'=>56, 'LA3'=>63, 'LA4'=>70,
      'LB1'=>62, 'LB2'=>69, 'LB3'=>72, 'LC1'=>68, 'LC2'=>58, 'LC3'=>77];

// Create overrides — 50-minute windows
$slots = [
    ['2026-09-14 10:00', ['T03']],
    ['2026-09-14 14:00', ['LA4']],
    ['2026-09-14 15:00', ['T01','TA1','LA3']],
    // ...
];
foreach ($slots as $slot) {
    $tOpen = strtotime($slot[0]);
    $tClose = $tOpen + 50*60;
    foreach ($slot[1] as $gn) {
        $data = (object)[
            'quiz' => $quizId, 'groupid' => $g[$gn], 'userid' => 0,
            'timeopen' => $tOpen, 'timeclose' => $tClose,
            'timelimit' => 2700, 'attempts' => 1,
        ];
        $DB->insert_record('quiz_overrides', $data);
    }
}
cache_helper::purge_by_event('changesincourse');
```

## Quiz ID mapping (<coursecode>, course id=3)

| Quiz name | ID | Section |
|---|---|---|
| Quiz for testing SEB | 55 | 22 |
| Demo CE-Quiz | 56 | 22 |
| E-Quiz 1 | 57 | 23 |
| CE-Quiz 1 | 58 | 23 |
| E-Quiz 2 | 59 | 24 |
| CE-Quiz 2 | 60 | 24 |
| ... (E-Quiz 3 through CE-Quiz 9, IDs 61–74) | | |

## Pitfalls

- **Editing a quiz's `intro` directly in the DB leaves calendar events STALE** — quiz calendar events store their own pre-rendered HTML copy of the intro (`mdl_event.description = format_module_intro('quiz', $quiz, $cmid)` set by `quiz_update_events()`). After any direct `mdl_quiz.intro` edit, run `quiz_refresh_events($courseid, $quiz)` per quiz (mod/quiz/lib.php) to regenerate events — it rewrites only descriptions, times/overrides are untouched. Verify by checking `mdl_event.description` for the quizzes (`WHERE modulename='quiz' AND instance IN (...)`). (Discovered 2026-08-29: CE-Quiz instruction edits showed "Safe Exam Browser" on the course calendar while the quiz page showed "SEB".) **Instructor/website path (no agent needed):** opening the quiz's *Edit settings* and clicking *Save and display* re-runs `quiz_update_events()` unconditionally — that's the supported way to refresh events from the UI; there is no bulk "refresh all" button, and dragging an event in the calendar changes the quiz's open/close time (don't use it to force a refresh).
- **`mdl_event` schema here (Moodle 5.x):** `id,name,description,format,categoryid,courseid,groupid,userid,repeatid,component,modulename,instance,type,eventtype,timestart,timeduration,timesort,visible,uuid,sequence,timemodified,subscriptionid,priority,location` — course filter is `courseid` (not `course`), quiz FK is `instance` (not `quiz`), times are `timestart`/`timeduration` (not `startdate`/`enddate`).
- **Always use `date_default_timezone_set('Asia/Hong_Kong')`** — Moodle stores timestamps as UTC but the user works in HKT. Without explicit timezone, PHP uses the server default which may differ.
- **`$DB->set_field()` requires `['id' => $quizId]` as array** — `set_field('quiz', 'timeopen', $ts, 'id', $quizId)` (string key) fails. Use `set_field('quiz', 'timeopen', $ts, ['id' => $quizId])`.
- **Set overrides to EXACT quiz defaults, not zero** — `timelimit=2700`, `attempts=1`. Setting `timelimit=0` does NOT inherit the quiz value — it breaks. The user corrected this explicitly.
- **E-Quiz timing** — each E-Quiz N should open one week before its corresponding CE-Quiz N (global window only, no group overrides needed for E-Quizzes).
- **Moodle cache purge** — the user demands `moosh -n cache-clear` BEFORE every verification check, not after. If you skip this step, the user will not be able to confirm the changes.
- **Delete overrides before creating** — never append; always start fresh to avoid stale entries.
- **Read group IDs from the DB** — group IDs change between semesters. Never hardcode; query `mdl_groups WHERE courseid = <cid>`.
- **Groups must exist before creating overrides** — create missing groups first.
- **CE-Quiz N ≠ Week N** — CE-Quiz 1 runs in Week 3 (Lab1). CE-Quiz number matches Lab number, not Week number.
- **Lab0 has no group overrides** — it's a demo with a single global window.