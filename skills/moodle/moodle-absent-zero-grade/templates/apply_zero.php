<?php
// Zero-grade absent students for one quiz.
// Usage: php apply_zero.php [--commit]
//   Without --commit: dry run (all transactions rolled back).
// EDIT $STUDENTS (attemptid => userid) per batch; verify each attemptid/userid
// pair against mdl_quiz_attempts FIRST (read-only).
// Backup: /tmp/<quizid>_absent_backup.json (pre-attempt rows, for reversal).
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php'); require_once('/var/www/html/public/lib/setup.php');
global $DB;

$COMMIT = in_array('--commit', $argv, true);
$quizid    = 59;   // E-Quiz 2 (EDIT)
$courseid  = 3;    // cs1302a_26a (EDIT)
$gradeItem = 61;   // grade_items.id for this quiz:
                   //   get_record('grade_items',['itemmodule'=>'quiz','iteminstance'=>$quizid,'courseid'=>$courseid])->id
$byuser    = 494;  // grading teacher (VERIFY bound account first!)
$COMMENT   = "Marked 0: the student was absent from the lecture session where answers were sampled for explanation and could not explain the working. Awarded 0 per course policy.";

$STUDENTS = [
  // attemptid => userid  (EDIT per batch)
  16011 => 629,
];

require_once('/var/www/html/public/mod/quiz/locallib.php');
require_once('/var/www/html/public/mod/quiz/classes/quiz_attempt.php');
require_once('/var/www/html/public/question/engine/lib.php');
require_once('/var/www/html/public/question/engine/datalib.php');

function dieerr($m){ fwrite(STDERR,"ERROR: $m\n"); exit(2); }
// CORRECT manual-step count (attemptstepid -> question_attempt_steps.id)
function manual_marks_in_usage($usageid){
  global $DB;
  return $DB->count_records_sql("SELECT COUNT(*) FROM {question_attempt_step_data} d
     WHERE d.name='-mark'
       AND d.attemptstepid IN (SELECT s.id FROM {question_attempt_steps} s
            WHERE s.questionattemptid IN (SELECT id FROM {question_attempts} WHERE questionusageid={$usageid} AND slot>1))");
}

$backup = ['ts'=>date('c')];

foreach ($STUDENTS as $attemptid => $userid) {
  echo "=== attempt $attemptid userid $userid ===\n";
  $ao = \mod_quiz\quiz_attempt::create($attemptid);
  $at = $ao->get_attempt();
  if ((int)$at->userid !== $userid) dieerr("attempt $attemptid belongs to {$at->userid}, not $userid");
  if (!$ao->is_finished()) dieerr("attempt $attemptid not finished");

  $usageid = (int)$at->uniqueid;
  $scoresslots = [];
  $qbyid = $DB->get_records_sql("SELECT id,qtype FROM {question} WHERE id IN (SELECT questionid FROM {question_attempts} WHERE questionusageid={$usageid})");
  foreach ($ao->get_slots('all') as $slot) {
    if ($qbyid[$ao->get_question_attempt($slot)->get_question_id()]->qtype === 'description') continue;
    $scoresslots[] = $slot;
  }
  $n = count($scoresslots);
  $pre = manual_marks_in_usage($usageid);
  echo "  scored slots=$n  pre-existing manual marks=$pre (expect 0)\n";
  if ($pre > 0) dieerr("attempt $attemptid already has manual marks ($pre) - stopping");

  $gg = $DB->get_record('grade_grades', ['itemid'=>$gradeItem, 'userid'=>$userid]);
  $backup["attempt_$attemptid"] = [
    'attempt' => ['id'=>$attemptid,'sumgrades'=>$at->sumgrades,'timemodified'=>$at->timemodified],
    'grade_grades' => $gg ? (array)$gg : null,
  ];

  $tx = $DB->start_delegated_transaction();
  try {
    // attempt's real usage object (private $quba) — do NOT rebuild a fresh usage
    $ref = new ReflectionProperty(\mod_quiz\quiz_attempt::class,'quba'); $ref->setAccessible(true);
    $quba = $ref->getValue($ao);
    $ts = time();
    foreach ($scoresslots as $slot) {
      $ao->get_question_attempt($slot)->manual_grade($COMMENT, 0, FORMAT_MOODLE, $ts, $byuser);
    }
    question_engine::save_questions_usage_by_activity($quba);

    // in-tx guard: all manual steps actually in the DB (correct join)
    $inTx = manual_marks_in_usage($usageid);
    if ($inTx !== $n) { try{$tx->rollback(new Exception('aborted'));}catch(Exception $e){} dieerr("in-tx check: $inTx/$n manual steps for attempt $attemptid"); }

    $DB->set_field('quiz_attempts','sumgrades','0', ['id'=>$attemptid]);
    $DB->set_field('quiz_attempts','timemodified',$ts, ['id'=>$attemptid]);
    \mod_quiz\quiz_settings::create($quizid)->get_grade_calculator()->recompute_final_grade($userid);
    $at2 = $DB->get_record('quiz_attempts',['id'=>$attemptid]);
    $gg2 = $DB->get_record('grade_grades',['itemid'=>$gradeItem,'userid'=>$userid]);
    echo "  in-tx: sumgrades=".number_format((float)$at2->sumgrades,5)." rawgrade=".number_format((float)$gg2->rawgrade,5)."\n";
  } catch (Exception $e) {
    try{$tx->rollback(new Exception('aborted'));}catch(Exception $e2){}
    dieerr("apply attempt $attemptid: ".get_class($e).": ".$e->getMessage());
  }

  if ($COMMIT) {
    try {
      $ctx = $ao->get_quizobj()->get_context();
      foreach ($scoresslots as $slot) {
        $qa = $ao->get_question_attempt($slot);
        \mod_quiz\event\question_manually_graded::create([
          'objectid'=>$qa->get_question_id(),'courseid'=>$ao->get_courseid(),'context'=>$ctx,
          'other'=>['quizid'=>$quizid,'attemptid'=>$attemptid,'slot'=>$slot],
        ])->trigger();
      }
    } catch (Exception $e) { try{$tx->rollback(new Exception('aborted'));}catch(Exception $e2){} dieerr("events attempt $attemptid: ".$e->getMessage()); }
    $tx->allow_commit();
    // post-commit re-verify
    $pc = manual_marks_in_usage($usageid);
    $chk = $DB->get_record('quiz_attempts',['id'=>$attemptid]);
    $g3  = $DB->get_record('grade_grades',['itemid'=>$gradeItem,'userid'=>$userid]);
    if ($pc !== $n) dieerr("post-commit check failed: $pc/$n steps for attempt $attemptid");
    echo "  COMMITTED: steps $pc/$n  sumgrades=".number_format((float)$chk->sumgrades,5)." rawgrade=".number_format((float)$g3->rawgrade,5)."\n";
  } else {
    try{$tx->rollback(new Exception('dry-run'));}catch(Exception $e){}
    echo "  dry-run: rolled back\n";
  }
}

file_put_contents('/tmp/'.basename(__FILE__, '.php').'_backup.json', json_encode($backup));
if (!$COMMIT) { echo "\nDRY RUN complete. Backup: /tmp/".basename(__FILE__, '.php')."_backup.json\n"; exit(0); }
purge_caches();
echo "\nALL COMMITTED. (Run: cd /var/www/html/public && moosh -n cache-clear)\n";
