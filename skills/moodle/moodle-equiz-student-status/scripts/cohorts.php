<?php
/**
 * Moodle quiz student-status cohorts (read-only).
 *
 * Usage: php cohorts.php <courseid> "<quiz name>" [threshold_pct]
 * Example: php cohorts.php 3 "E-Quiz 1" 30
 *
 * Prints three cohorts:
 *   A. Failed        — enrolled + submitted + gradebook mark <= threshold
 *   B. Not attempted — enrolled + no finished non-preview attempt
 *   C. Not enrolled  — on LTI group-sync roster (ltigroups) but no Moodle account
 * Plus: "submitted, grade pending" (submitted but gradebook grade not computed yet).
 *
 * ENVIRONMENT ASSUMPTIONS (verified cs1302a_26a / course 3):
 *  - Moodle webroot /var/www/html/public, run as www-data.
 *  - LTI plugin table mdl_ltigroups_roster(courseid, eid, userid, assignments).
 *  - quiz_attempts uses `sumgrades` (NOT sumgrade); that column is on the
 *    QUESTION mark scale, NOT quiz.grade — do not compute % from it directly.
 *  - Keep SQL flat (no nested subqueries): this driver silently fails some.
 */
define('CLI_SCRIPT', true);
define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php');
require_once('/var/www/html/public/lib/setup.php');
global $DB;

if ($argc < 3) {
    fwrite(STDERR, "Usage: php cohorts.php <courseid> \"<quiz name>\" [threshold_pct]\n");
    exit(2);
}
$courseid = (int)$argv[1];
$quizname = $argv[2];
$threshold = $argc > 3 ? (float)$argv[3] : 30.0;

// ---------- 1. Resolve ids ----------
$quiz = $DB->get_record('quiz', ['course' => $courseid, 'name' => $quizname]);
if (!$quiz) {
    fwrite(STDERR, "Quiz not found: course $courseid / '$quizname'\n");
    exit(2);
}
$quizid = (int)$quiz->id;
$gibookmax = (float)$quiz->grade; // gradebook max for this quiz

$gi = $DB->get_record('grade_items', ['itemmodule' => 'quiz', 'iteminstance' => $quizid]);
if (!$gi) {
    fwrite(STDERR, "No grade item for quiz $quizid (grade not configured?) — will fall back to raw sumgrades.\n");
}

// ---------- 2. Enrolled active students ----------
$ctx = $DB->get_record('context', ['contextlevel' => 50, 'instanceid' => $courseid]);
$ctxid = (int)$ctx->id;
$studentrole = (int)$DB->get_field('role', 'id', ['shortname' => 'student']);

$ra = $DB->get_records('role_assignments', ['contextid' => $ctxid, 'roleid' => $studentrole]);
$roleuids = array_flip(array_map('intval', array_column($ra, 'userid')));

$enrols = $DB->get_records('enrol', ['courseid' => $courseid, 'status' => 0]);
$ae = implode(',', array_map('intval', array_keys($enrols)));
$ue = $DB->get_records_sql("SELECT DISTINCT userid FROM {user_enrolments} WHERE enrolid IN ($ae) AND status = 0");
$enrolled = [];
foreach ($ue as $r) {
    if (isset($roleuids[(int)$r->userid])) $enrolled[(int)$r->userid] = true;
}

// ---------- 3. Attempts ----------
$atts = $DB->get_records('quiz_attempts', ['quiz' => $quizid, 'preview' => 0], '', 'id, userid, sumgrades, timefinish');
$submitted = []; // uid => best raw sumgrades
$nfin = 0;
foreach ($atts as $a) {
    if (!empty($a->timefinish)) {
        $nfin++;
        $sg = (float)$a->sumgrades;
        if (!isset($submitted[$a->userid]) || $sg > $submitted[$a->userid]) $submitted[$a->userid] = $sg;
    }
}

// ---------- 4. Gradebook grades (authoritative %) ----------
$grades = []; // uid => finalgrade (raw string)
if ($gi) {
    $g = $DB->get_records('grade_grades', ['itemid' => $gi->id]);
    foreach ($g as $row) $grades[(int)$row->userid] = $row->finalgrade;
}

// ---------- 5. User + group enrichment (one query each, over enrolled) ----------
$enrollist = array_keys($enrolled);
$uidsall = array_unique(array_merge($enrollist, array_keys($submitted)));
$uin = implode(',', array_map('intval', $uidsall));
$users = $DB->get_records_sql("SELECT id, firstname, lastname, email FROM {user} WHERE id IN ($uin)");
$grows = $DB->get_records_sql(
    "SELECT gm.userid, g2.name AS gname FROM {groups_members} gm JOIN {groups} g2 ON g2.id = gm.groupid WHERE g2.courseid = $courseid AND gm.userid IN ($uin)"
);
$gmap = [];
foreach ($grows as $gr) $gmap[(int)$gr->userid][] = $gr->gname;

function istag($email, $groups): array {
    $tags = [];
    if (in_array('helpers', $groups)) $tags[] = 'helper';
    if (strpos($email, 'ltitest') !== false) $tags[] = 'lti-test';
    if (strpos($email, '@example.com') !== false) $tags[] = 'test-account';
    return $tags;
}
function fmtuser($uid): array {
    global $users, $gmap;
    $u = $users[$uid] ?? null;
    if (!$u) return ['name' => "user#$uid", 'email' => '', 'groups' => []];
    return ['name' => $u->lastname . ' ' . $u->firstname, 'email' => $u->email, 'groups' => $gmap[$uid] ?? []];
}

// ---------- 6. Cohort A: submitted + enrolled + grade <= threshold ----------
$A = []; $pending = [];
foreach ($submitted as $uid => $sg) {
    if (!isset($enrolled[$uid])) continue;
    $fg = $grades[$uid] ?? null;
    $u = fmtuser($uid);
    if (is_null($fg) || trim((string)$fg) === '') {
        $pending[] = ['uid' => $uid] + $u + ['tags' => istag($u['email'], $u['groups'])];
        continue;
    }
    $v = (float)$fg;
    $pct = $gibookmax > 0 ? $v / $gibookmax * 100 : null;
    if ($pct === null || $pct <= $threshold + 0.0001) {
        $A[] = ['uid' => $uid] + $u + ['tags' => istag($u['email'], $u['groups']),
                                        'score' => $v, 'max' => $gibookmax, 'pct' => $pct, 'raw' => $sg];
    }
}
usort($A, fn($x, $y) => $x['pct'] <=> $y['pct']);

// ---------- 7. Cohort B: enrolled, no submitted attempt ----------
$B = [];
foreach ($enrolled as $uid => $x) {
    if (isset($submitted[$uid])) continue;
    $u = fmtuser($uid);
    $B[] = ['uid' => $uid] + $u + ['tags' => istag($u['email'], $u['groups'])];
}
usort($B, fn($x, $y) => strcmp($x['name'], $y['name']));

// ---------- 8. Cohort C: roster without Moodle account ----------
$C = [];
$roster = $DB->get_records_sql(
    "SELECT eid, assignments FROM {ltigroups_roster} WHERE courseid = $courseid AND (userid IS NULL OR userid = 0)"
);
foreach ($roster as $r) {
    $a = json_decode($r->assignments, true);
    $C[] = ['eid' => $r->eid, 'lec' => $a['Lec'] ?? '?', 'lab' => $a['Lab'] ?? '?'];
}
usort($C, fn($x, $y) => strcmp($x['eid'], $y['eid']));

// ---------- 9. Sanity checks ----------
$check1 = count($submitted) + count(array_filter(array_keys($enrolled), fn($u) => !isset($submitted[$u])));
$ok1 = $check1 === count($enrolled);

// ---------- 10. Report ----------
$real = fn($s) => empty($s['tags']);
echo "Course: $courseid | Quiz: $quizname (id $quizid) | gradebook max: $gibookmax | threshold: {$threshold}%\n";
echo "Enrolled active students: " . count($enrolled) . " | submitted (finished): " . count($submitted) . " | sanity(submitted+not==enrolled): " . ($ok1 ? 'OK' : "FAIL ($check1)") . "\n\n";

echo "=== A. FAILED (<= {$threshold}%, gradebook) — " . count($A) . " total, " . count(array_filter($A, $real)) . " real ===\n";
foreach ($A as $s) {
    $tag = $s['tags'] ? '  [' . implode(',', $s['tags']) . ']' : '';
    printf("  %-28s | %-36s | %5.1f%% (%.2f/%.0f, raw %.2f) | %s%s\n",
        $s['name'], $s['email'], $s['pct'], $s['score'], $s['max'], $s['raw'], implode(',', $s['groups']), $tag);
}

if ($pending) {
    echo "\n--- Submitted but gradebook grade not computed yet: " . count($pending) . " ---\n";
    foreach ($pending as $s) {
        $tag = $s['tags'] ? '  [' . implode(',', $s['tags']) . ']' : '';
        printf("  %-28s | %-36s | %s%s\n", $s['name'], $s['email'], implode(',', $s['groups']), $tag);
    }
}

echo "\n=== B. NOT ATTEMPTED (enrolled, no finished attempt) — " . count($B) . " total, " . count(array_filter($B, $real)) . " real ===\n";
foreach ($B as $s) {
    $tag = $s['tags'] ? '  [' . implode(',', $s['tags']) . ']' : '';
    printf("  %-28s | %-36s | %s%s\n", $s['name'], $s['email'], implode(',', $s['groups']), $tag);
}

echo "\n=== C. NOT ENROLLED (on LTI roster, no Moodle account) — " . count($C) . " ===\n";
foreach ($C as $s) {
    printf("  %-36s | Lec %s | Lab %s\n", $s['eid'], $s['lec'], $s['lab']);
}
