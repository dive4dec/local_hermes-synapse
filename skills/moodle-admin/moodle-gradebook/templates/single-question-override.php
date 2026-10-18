<?php
// Portable params (see skills/_conventions/PORTABLE.md). Override via env; defaults match a standard layout.
$WEBROOT  = getenv('MHS_WEBROOT')  ?: '/var/www/html/public';
$DATA_DIR = getenv('MHS_DATA_DIR') ?: '/var/www/moodledata';

// Single-question quiz manual override (mark + comment) — verified working 2026-10-01
// (u563, E-Quiz 3 quiz61 Q8 'short-circuit - function call' slot9 q3639,
//  1/1 -> 0; sumgrades 18.06667 -> 17.06667; gradebook 62.84059 -> 59.36233 = x80/23).
//
// Run:  cd <datadir>/.hermes && timeout 300 php -d display_errors=1 /tmp/single_q.php
//
// NO explicit DB transaction: on this build $DB->commit_transaction() and
// $DB->rollback_transaction() are PROTECTED from global scope ("Call to protected
// method … from global scope"). Safety instead comes from:
//   read-only pre-flight guards -> JSON backup of touched rows -> engine apply ->
//   post-apply guards (fresh reads) -> explicit sumgrades + gradebook recompute ->
//   fresh verification. If a guard fails AFTER the engine write, restore from backup.
// (A crashed script with an open delegated transaction auto-aborts at exit, so
//  pre-write crashes leave no partial state — but verify, don't assume.)
define('CLI_SCRIPT', true);
define('MOODLE_INTERNAL', true);
require($WEBROOT.'/config.php');
require_once($WEBROOT.'/lib/setup.php');
require_once($WEBROOT.'/question/engine/lib.php');
require_once($WEBROOT.'/question/engine/datalib.php');
require_once($WEBROOT.'/mod/quiz/locallib.php');
require_once($WEBROOT.'/mod/quiz/classes/quiz_attempt.php');
global $DB;

// ---------------- EDIT THESE ----------------
$COURSEID = getenv('MHS_COURSE_ID') ? (int)getenv('MHS_COURSE_ID') : 0;  // <cid> — set MHS_COURSE_ID (run mhs-setup) or edit
$QUIZ     = 61;       // quiz id
$ATTEMPT  = 16499;    // mdl_quiz_attempts.id of the finished attempt
$SLOT     = 9;        // slot of the target question
$QID      = 3639;     // question id (pre-flight cross-checks against $SLOT)
$USERID   = 563;      // student
$BYUSER   = 494;      // grader (teacher)
$MARK     = 0;        // mark to award
$COMMENT  = 'Marked 0: the student was present but was unable to explain the working for this question when sampled. Awarded 0 per course policy.';
$OLD_SUM  = 18.06667; // expected current sumgrades
$NEW_SUM  = 17.06667; // expected new sumgrades = OLD - marks currently earned on this question
$BACKUP   = '/tmp/quiz61_single_q_backup.json';
// ---------------------------------------------

function fail($msg) { fwrite(STDERR, "ABORT: $msg\n"); exit(1); }

// ---------- 1. Pre-flight guards (read-only) ----------
$at = $DB->get_record('quiz_attempts', ['id' => $ATTEMPT]);
if ((int)$at->userid !== $USERID || (int)$at->quiz !== $QUIZ || $at->state !== 'finished')
    fail('attempt/user/quiz/state mismatch');
if ((float)$at->sumgrades !== (float)$OLD_SUM)
    fail("sumgrades {$at->sumgrades} != expected $OLD_SUM (already applied?)");
// NOTE: questionusageid = quiz_attempts.uniqueid, NOT .id
$qa = $DB->get_record('question_attempts', ['questionusageid' => $at->uniqueid, 'questionid' => $QID]);
if (!$qa || (int)$qa->slot !== $SLOT) fail('slot/questionid mismatch — re-resolve the question');
$pre = $DB->count_records_sql(
    "SELECT COUNT(*) FROM {question_attempt_step_data} d
     JOIN {question_attempt_steps} s ON s.id = d.attemptstepid
     JOIN {question_attempts} q2 ON q2.id = s.questionattemptid
     WHERE d.name = '-mark' AND q2.questionusageid = ?", [$at->uniqueid]);
if ($pre > 0) fail("pre-existing -mark steps = $pre (double grade)");

// ---------- 2. Backup ----------
$gi = $DB->get_record('grade_items', ['itemmodule' => 'quiz', 'iteminstance' => $QUIZ, 'courseid' => $COURSEID]);
$gg = $DB->get_record('grade_grades', ['userid' => $USERID, 'itemid' => $gi->id]);
file_put_contents($BACKUP, json_encode([
    'quiz_attempts' => (array)$at,
    'grade_grades'  => $gg ? (array)$gg : null,
    'grade_item_id' => $gi->id,
    'ts'            => date('c'),
], JSON_PRETTY_PRINT));
echo "backup written to $BACKUP\n";

// ---------- 3. Apply (question engine) ----------
$attempt = \mod_quiz\quiz_attempt::create($ATTEMPT);
$rp = new ReflectionProperty('mod_quiz\quiz_attempt', 'quba');
$rp->setAccessible(true);
$quba = $rp->getValue($attempt);   // verified fallback if get_question_usage() is absent
$qaobj = $attempt->get_question_attempt($SLOT);
$qaobj->manual_grade($COMMENT, $MARK, FORMAT_MOODLE, time(), $BYUSER);
question_engine::save_questions_usage_by_activity($quba);
echo "manual_grade applied + usage saved\n";

// ---------- 4. Post-apply guards (fresh reads) ----------
$mk = $DB->count_records_sql(
    "SELECT COUNT(*) FROM {question_attempt_step_data} d
     JOIN {question_attempt_steps} s ON s.id = d.attemptstepid
     JOIN {question_attempts} q2 ON q2.id = s.questionattemptid
     WHERE d.name = '-mark' AND q2.questionusageid = ? AND q2.id = ?", [$at->uniqueid, $qa->id]);
$mkElse = $DB->count_records_sql(
    "SELECT COUNT(*) FROM {question_attempt_step_data} d
     JOIN {question_attempt_steps} s ON s.id = d.attemptstepid
     JOIN {question_attempts} q2 ON q2.id = s.questionattemptid
     WHERE d.name = '-mark' AND q2.questionusageid = ? AND q2.id <> ?", [$at->uniqueid, $qa->id]);
if ($mk !== 1) fail("expected 1 -mark on target, got $mk");
if ($mkElse !== 0) fail("-mark leaked to other slots: $mkElse");
$qstate = $DB->get_field_sql(
    "SELECT s.state FROM {question_attempt_steps} s
     WHERE s.questionattemptid = {$qa->id} ORDER BY s.sequencenumber DESC LIMIT 1", []);
if ($qstate !== 'mangrwrong') fail("target state $qstate != mangrwrong");

// ---------- 5. Total + gradebook ----------
$DB->set_field('quiz_attempts', 'sumgrades', $NEW_SUM, ['id' => $ATTEMPT]);
$DB->set_field('quiz_attempts', 'timemodified', time(), ['id' => $ATTEMPT]);
\mod_quiz\quiz_settings::create($QUIZ)->get_grade_calculator()->recompute_final_grade($USERID);

// ---------- 6. Verify (fresh reads) ----------
$chk = $DB->get_record('quiz_attempts', ['id' => $ATTEMPT], 'sumgrades,state');
$gg2 = $DB->get_record('grade_grades', ['userid' => $USERID, 'itemid' => $gi->id], 'rawgrade,finalgrade');
if ((float)$chk->sumgrades !== (float)$NEW_SUM) fail("sumgrades {$chk->sumgrades} != $NEW_SUM");
if ($chk->state !== 'finished') fail("state {$chk->state} != finished");
if ($gg2->rawgrade === null) fail('grade_grades row missing after recompute');
echo "VERIFY OK: sumgrades={$chk->sumgrades} gradebook raw={$gg2->rawgrade}\n";

// ---------- 7. Audit event + caches ----------
$cm = $DB->get_record('course_modules', ['instance' => $QUIZ,
    'module' => $DB->get_field('modules', 'id', ['name' => 'quiz'])]);
\mod_quiz\event\question_manually_graded::create([
    'objectid'      => $QID,
    'context'       => context_module::instance($cm->id),   // context::instance() does not exist
    'relateduserid' => $USERID,
    'other'         => ['quizid' => $QUIZ, 'attemptid' => $ATTEMPT, 'slot' => $SLOT],
])->trigger();
purge_caches();
echo "DONE\n";
