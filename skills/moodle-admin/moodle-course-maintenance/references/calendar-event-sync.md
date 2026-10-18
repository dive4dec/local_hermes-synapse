# Syncing calendar events after direct DB edits to activity descriptions

## Why calendar text goes stale

Moodle calendar events store a **pre-rendered snapshot copy** of the activity's description — not a live reference. When quiz events are built, `quiz_update_events()` (mod/quiz/lib.php) writes:

```php
$event->description = format_module_intro('quiz', $quiz, $cmid, false); // pre-filtered HTML
$event->format = FORMAT_HTML;
```

So editing `mdl_quiz.intro` (or any module's intro) **directly in the DB** leaves existing `mdl_event` rows holding the old text until the events are regenerated. Symptom (2026-08-29, cs1302a_26a CE-Quizzes): the quiz pages showed "SEB" while the course calendar still showed "Safe Exam Browser" in every opens/closes event.

Two corollaries:
- The snapshot is **pre-filtered** — calendar text already contains resolved `<a class="autolink">` tags from whatever activity names existed at build time (e.g. "midterm" → Midterm quiz, "Exam" → Exam quiz). Rebuilding events picks up current autolinks.
- Each quiz carries ~12 events (opens/closes × main + group overrides: T01/T02/TA1/helpers + close), so one intro edit touches ~120 event rows across 10 quizzes.

## The fix (PHP)

`quiz_refresh_events($courseid, $instance)` → `quiz_update_events($quiz)`: rebuilds that quiz's events from current settings. It diffs against the old events, so unchanged times/overrides/priorities are untouched — only names/descriptions get rewritten. There is no single "refresh all events" call in this flow; loop per quiz:

```php
require_once('/var/www/html/public/mod/quiz/lib.php');
foreach ($quizids as $qid) {
    $quiz = $DB->get_record('quiz', ['id' => $qid], '*', MUST_EXIST);
    quiz_refresh_events($courseid, $quiz);
}
```

Verify before/after:
1. Event count per quiz is unchanged: `SELECT COUNT(*) FROM mdl_event WHERE modulename='quiz' AND instance=<qid>` (before == after — confirms no events lost).
2. Old string absent / new string present in every `description` (`LIKE '%old%'` count == 0).
3. Render one event's description through the real pipeline: `format_text($event->description, FORMAT_HTML, ['context' => context_module::instance($cmid)])` and check the autolink `href`/`title` point where you want.

5.x `mdl_event` schema traps (full column list in the `moodle-mcp-db-query` skill, pitfall 20): course column = `courseid` (not `course`), activity FK = `instance` (not `quiz`), times = `timestart`/`timeduration` (not `startdate`/`enddate`).

## The standard UI path (what an instructor does — verified in code 2026-08-29)

- **Saving the quiz's settings refreshes its events.** The quiz edit page's Save button runs `quiz_update_instance()` → `quiz_after_add_or_update()` → `quiz_update_events($quiz)` — called **unconditionally** on every save, even with no fields changed. So: open the quiz → Edit settings → Save and display.
- There is **no bulk "refresh all events" button** and no cron hook for quiz events — one save per quiz.
- **Do NOT drag a calendar event to force a refresh** — moving an event's timestart goes through `mod_quiz_core_calendar_event_timestart_updated()`, which *changes the quiz's open/close time* and then regenerates events with the new time. Dragging is a reschedule, not a no-op refresh.

## Cross-reference

- Direct DB intro editing itself (strict replacement guard, format constants, render-verify): `references/activity-intro-editing.md`.
- Autolink behavior of the snapshot text: `references/autolink-activitynames.md`.
- The same pitfall is also noted in the `moodle-cequiz-management` skill (CE-Quiz domain).
