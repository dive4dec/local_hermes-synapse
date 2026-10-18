# Zero-out recipe (verified 2026-10-07, cs1302a_26a, quiz 63/64)

Working script shape. Two modes: whole-attempt (loop all scored slots) and
single-slot. Both end with the same sumgrades refresh + recompute.

## Whole-attempt
```php
<?php
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php'); require_once('/var/www/html/public/lib/setup.php');
global $DB;
require_once('/var/www/html/public/mod/quiz/locallib.php');
require_once('/var/www/html/public/mod/quiz/classes/quiz_attempt.php');

$QUIZID = 63; $grader = 494; // Chung Chan
$comment = 'Mark set to 0: student was not present when sampled to explain the E-Quiz 4 submission. See course email dated 2026-10-07.';
$targets = [16823 => 677, 16929 => 731]; // attemptid => userid

foreach ($targets as $attemptid => $uid) {
    // 1. backup (attempt, question_attempts, step_data, quiz_grades, grade_grades)
    //    to /tmp/<quiz>_at<attemptid>_pre.json — do this BEFORE anything else
    $attemptobj = \mod_quiz\quiz_attempt::create($attemptid);
    if ($attemptobj->get_userid() != $uid) { fwrite(STDERR, "ABORT user mismatch\n"); exit(1); }

    // 2. scored slots = all slots whose question qtype != 'description'
    $scoreslots = [];
    foreach ($attemptobj->get_slots('all') as $slot) {
        $qtype = $DB->get_field('question', 'qtype', ['id' => $attemptobj->get_question_attempt($slot)->get_question_id()]);
        if ($qtype !== 'description') $scoreslots[] = $slot;
    }

    // 3. manual grade each scored slot (mark=0 + comment)
    $ts = time();
    foreach ($scoreslots as $slot) {
        $attemptobj->get_question_attempt($slot)->manual_grade($comment, 0, FORMAT_MOODLE, $ts, $grader);
    }

    // 4. save the shared quba (protected property via reflection;
    //    get_question_usage() is unit-test-guarded and throws in CLI)
    $ref = new ReflectionObject($attemptobj);
    $prop = $ref->getProperty('quba'); $prop->setAccessible(true);
    $quba = $prop->getValue($attemptobj);
    question_engine::save_questions_usage_by_activity($quba);

    // 5. refresh sumgrades from the engine total, save attempt row
    $attemptobj->get_attempt()->sumgrades = $quba->get_total_mark();
    $DB->update_record('quiz_attempts', $attemptobj->get_attempt());

    // 6. recompute gradebook (PROTECTED in this build -> reflection)
    $m = $ref->getMethod('recompute_final_grade'); $m->setAccessible(true); $m->invoke($attemptobj);

    // 7. audit events per slot
    $ctx = $attemptobj->get_quizobj()->get_context();
    foreach ($scoreslots as $slot) {
        \mod_quiz\event\question_manually_graded::create([
            'objectid' => $attemptobj->get_question_attempt($slot)->get_question_id(),
            'courseid' => $attemptobj->get_courseid(), 'context' => $ctx,
            'other' => ['quizid' => $QUIZID, 'attemptid' => $attemptid, 'slot' => $slot],
        ])->trigger();
    }
    // 8. echo pre/post sumgrades + quiz_grades + grade_grades for the log
}
```

## Single-slot variant
Same, but:
- step 2 → pick the ONE slot (verify question name matches first; Question N = slot N+1)
- step 3 → one `manual_grade` call on that slot only
- pre-sumgrades is echoed for the report (e.g. 22 → 20)
- `get_total_mark()` handles the arithmetic; do not subtract by hand.

## After the batch
```php
require_once('/var/www/html/public/lib/gradelib.php');
grade_regrade_final_grades($courseid);
```
then in the shell: `cd /var/www/html/public && moosh -n cache-clear`.

## Verification (independent MCP read, never the same PHP process)
```sql
SELECT qa.id, qa.sumgrades, qg.grade, gg.rawgrade, gg.finalgrade, gg.overridden
FROM mdl_quiz_attempts qa
JOIN mdl_quiz_grades qg ON qg.quiz=qa.quiz AND qg.userid=qa.userid
JOIN mdl_grade_items gi ON gi.itemmodule='quiz' AND gi.iteminstance=<quizid>
JOIN mdl_grade_grades gg ON gg.itemid=gi.id AND gg.userid=qa.userid
WHERE qa.id IN (...);
```
and confirm the manual steps exist:
```sql
SELECT s.questionattemptid, s.state, d.name, LEFT(d.value,70) v
FROM mdl_question_attempt_steps s
JOIN mdl_question_attempt_step_data d ON d.attemptstepid = s.id
WHERE s.questionattemptid IN (SELECT id FROM mdl_question_attempts
  WHERE questionusageid IN (SELECT uniqueid FROM mdl_quiz_attempts WHERE id IN (...)))
  AND d.name IN ('-mark','-comment');
```
Expected: `mangrwrong` state, `-mark` = 0, comment text present. All four
aggregate fields (sumgrades, quiz_grades, rawgrade, finalgrade) must agree.

## Run
`cd /var/www/moodledata/.hermes && php /tmp/<script>.php 2>&1 | grep -v REQUEST_URI`
(Run as www-data; the PHP bootstrap in config.php does the DB wiring.)
