<?php
/**
 * Moodle quiz per-question (per-slot) completion status.
 *
 * Usage: php question_progress.php <quizid> <slot> [courseid]
 * Example: php question_progress.php 58 2 3   (CE-Quiz 1, slot 2, course 3)
 *
 * Classifies every student who started the quiz into:
 *   answered   — slot reached a terminal state (complete/gradedright/gradedwrong/submitted)
 *   gave up    — terminal state gaveup/failed (reached it, abandoned, no answer)
 *   not reached— only `todo` steps so far (still on an earlier question / mid-attempt)
 *
 * ENVIRONMENT ASSUMPTIONS (verified cs1302a_26a / Moodle 5.2 fork, 2026-09-14):
 *  - webroot /var/www/html/public, run as www-data (cd /var/www/moodledata/.hermes first).
 *  - quiz_attempts.uniqueid == question_usages.id  (the attempt->usage link).
 *  - question_attempts.questionusageid + .slot + .questionid.
 *  - question_attempt_steps.questionattemptid == question_attempts.id; state column is `state`
 *    (NOT `event`); terminal states: complete/gradedright/gradedwrong/submitted/gaveup/failed.
 *  - get_records_sql is flaky: keep queries flat, chunk IN lists. No nested subqueries.
 */
define('CLI_SCRIPT', true);
define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php');
require_once('/var/www/html/public/lib/setup.php');
global $DB;

if ($argc < 3) {
    fwrite(STDERR, "Usage: php question_progress.php <quizid> <slot> [courseid]\n");
    exit(2);
}
$quizid = (int)$argv[1];
$slot = (int)$argv[2];
$courseid = isset($argv[3]) ? (int)$argv[3] : 3;

function t($label, $fn) {
    try { $r = $fn(); echo "OK  $label (" . count((array)$r) . ")\n"; return $r; }
    catch (Throwable $e) { echo "ERR $label: " . $e->getMessage() . "\n"; exit(1); }
}
$ANSWERED = ['complete', 'gradedright', 'gradedwrong', 'submitted'];
$GAVEUP   = ['gaveup', 'failed'];

// 1) all non-preview attempts
$all = t('attempts', fn() => $DB->get_records_sql(
    "SELECT id, userid, uniqueid, timefinish FROM {quiz_attempts} WHERE quiz = ? AND preview = 0", [$quizid]));
$submitted = []; $inprogress = []; $uidofusage = [];
foreach ($all as $a) {
    $uidofusage[(int)$a->uniqueid] = (int)$a->userid;
    if (!empty($a->timefinish)) $submitted[(int)$a->userid] = true;
    else $inprogress[(int)$a->userid] = true;
}
echo "attempts: " . count($all) . " | submitted users: " . count($submitted)
   . " | in-progress users: " . count($inprogress) . "\n";

// 2) this quiz's usages
$uin = implode(',', array_map('intval', array_keys($uidofusage)));

// 2a) slot -> question name map (distinct question for this quiz, any slot)
$map = $DB->get_records_sql(
    "SELECT DISTINCT qa.slot, qa.questionid FROM {question_attempts} qa WHERE qa.questionusageid IN ($uin) ORDER BY qa.slot");
echo "slot -> question map:\n";
$targetqid = null;
foreach ($map as $m) {
    $qname = $DB->get_field('question', 'name', ['id' => $m->questionid]);
    echo "  slot {$m->slot} -> q{$m->questionid} (" . substr($qname, 0, 40) . ")\n";
    if ((int)$m->slot === $slot) $targetqid = (int)$m->questionid;
}
if ($targetqid === null) { echo "slot $slot not found in this quiz\n"; exit(1); }

// 2b) slot's question attempts
$qa2 = t("slot$slot qas", fn() => $DB->get_records_sql(
    "SELECT id, questionusageid FROM {question_attempts} WHERE slot = ? AND questionusageid IN ($uin)", [$slot]));

// 3) states, chunked (steps table is huge; IN list must be small)
$qastate = []; // qaid => last non-todo state
if ($qa2) {
    $ids = array_map('intval', array_column($qa2, 'id'));
    foreach (array_chunk($ids, 30) as $chunk) {
        $qain = implode(',', $chunk);
        $steps = t('steps chunk', fn() => $DB->get_records_sql(
            "SELECT questionattemptid, sequencenumber, state FROM {question_attempt_steps} WHERE questionattemptid IN ($qain) ORDER BY questionattemptid, sequencenumber"));
        foreach ($steps as $s) {
            if ($s->state !== 'todo') $qastate[(int)$s->questionattemptid] = $s->state; // overwrite => last terminal
        }
    }
}

// 4) classify per user (best case wins across attempts)
$rank = ['answered' => 3, 'gaveup' => 2, 'notreached' => 1];
$usercls = [];
foreach ($qa2 as $r) {
    $uid = $uidofusage[(int)$r->questionusageid] ?? 0;
    if (!$uid) continue;
    $st = $qastate[(int)$r->id] ?? null;
    $cls = $st === null ? 'notreached' : (in_array($st, $ANSWERED) ? 'answered' : 'gaveup');
    if (!isset($usercls[$uid]) || $rank[$cls] > $rank[$usercls[$uid]]) $usercls[$uid] = $cls;
}
$nans = count(array_filter($usercls, fn($c) => $c === 'answered'));
$ngave = count(array_filter($usercls, fn($c) => $c === 'gaveup'));
$nnot = count(array_filter($usercls, fn($c) => $c === 'notreached'));
echo "users who answered slot $slot: $nans | gave up: $ngave | not reached: $nnot\n";

// 5) names + groups for the missing
$missing = array_filter($usercls, fn($c) => $c !== 'answered');
$uids = array_keys($missing);
$mi = ['u' => [], 'g' => []];
if ($uids) {
    $in = implode(',', array_map('intval', $uids));
    $mi['u'] = $DB->get_records_sql("SELECT id, firstname, lastname, email FROM {user} WHERE id IN ($in)");
    $g = $DB->get_records_sql(
        "SELECT gm.userid, g2.name FROM {groups_members} gm JOIN {groups} g2 ON g2.id = gm.groupid WHERE g2.courseid = $courseid AND gm.userid IN ($in)");
    foreach ($g as $r) $mi['g'][(int)$r->userid][] = $r->name;
}

function istag($email, $groups) {
    $t = [];
    if (in_array('helpers', $groups)) $t[] = 'helper';
    if (strpos($email, 'ltitest') !== false) $t[] = 'lti-test';
    if (strpos($email, '@example.com') !== false) $t[] = 'test-account';
    return $t;
}

$gaveup = array_filter($missing, fn($c) => $c === 'gaveup');
$notreached = array_filter($missing, fn($c) => $c === 'notreached');

echo "\n=== GAVE UP on slot $slot (reached, no answer): " . count($gaveup) . " ===\n";
$i = 0;
foreach ($gaveup as $uid => $c) {
    $u = $mi['u'][$uid]; $g = $mi['g'][$uid] ?? [];
    printf("%d. %-28s | %-34s | %s%s\n", ++$i, $u->lastname . ' ' . $u->firstname, $u->email,
        implode(', ', $g), istag($u->email, $g) ? ' [' . implode(',', istag($u->email, $g)) . ']' : '');
}
echo "\n=== NOT REACHED slot $slot yet (still todo / mid-attempt): " . count($notreached) . " ===\n";
$i = 0;
foreach ($notreached as $uid => $c) {
    $u = $mi['u'][$uid]; $g = $mi['g'][$uid] ?? [];
    $open = isset($inprogress[$uid]) ? ' [quiz still open]' : '';
    $tag = istag($u->email, $g);
    printf("%d. %-28s | %-34s | %s%s%s\n", ++$i, $u->lastname . ' ' . $u->firstname, $u->email,
        implode(', ', $g), $open, $tag ? ' [' . implode(',', $tag) . ']' : '');
}
echo "\ntotal not completed: " . count($missing) . " of " . count($usercls) . " started\n";
echo "NOTE: if the quiz is still open, 'not reached' = still working, not final. Re-run after the window closes.\n";
