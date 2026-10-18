<?php
define('CLI_SCRIPT', true);
define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php');
require_once('/var/www/html/public/lib/setup.php');
global $DB;
$Q = fn($sql, $p = []) => $DB->get_records_sql($sql, $p);
function t($l,$fn){ try { return $fn(); } catch (Throwable $e){ echo "ERR $l: ".$e->getMessage()."\n"; exit(1);} }

$attempts = t('at', fn() => $Q("SELECT id, userid, uniqueid, timestart, timefinish, sumgrades FROM {quiz_attempts} WHERE quiz = 58 AND preview = 0 AND timefinish > 0"));
$uins = implode(',', array_unique(array_map('intval', array_column($attempts, 'uniqueid'))));
$uids = array_unique(array_map('intval', array_column($attempts, 'userid')));
$in = implode(',', $uids);
$users = t('u', fn() => $Q("SELECT id, firstname, lastname, email, auth FROM {user} WHERE id IN ($in)"));
$groups = [];
$g = t('g', fn() => $Q("SELECT gm.id, gm.userid, g2.name FROM {groups_members} gm JOIN {groups} g2 ON g2.id = gm.groupid WHERE g2.courseid = 3 AND gm.userid IN ($in)"));
foreach ($g as $r) $groups[(int)$r->userid][] = $r->name;

// IPs per user from logstore (last 3h of the session)
$minstart = min(array_map('intval', array_column($attempts, 'timestart')));
$ipdata = t('ip', fn() => $Q("SELECT id, userid, timecreated, ip FROM {logstore_standard_log} WHERE courseid = 3 AND userid IN ($in) AND timecreated >= ?", [$minstart]));
$ipByUser = [];
foreach ($ipdata as $r) {
    $uid = (int)$r->userid;
    if ($r->ip) { $ipByUser[$uid][$r->ip] = ($ipByUser[$uid][$r->ip] ?? 0) + 1; }
}

$rows = [];
foreach ($attempts as $a) {
    $uid = (int)$a->userid;
    $u = $users[$uid] ?? null;
    if (!$u || stripos($u->email, 'altitest') !== false) continue;
    $qas = t('qas', fn() => $Q("SELECT id, slot, maxmark FROM {question_attempts} WHERE questionusageid = ?", [(int)$a->uniqueid]));
    $checks = 0; $views = 0; $right = 0; $graded = 0; $noComplete = 0; $gradedTotal = 0;
    $qTraces = [];
    $firstAct = null; $lastAct = null;
    foreach ($qas as $q) {
        if ((int)$q->slot === 1) continue;
        $steps = t('st', fn() => $Q("SELECT id, sequencenumber, state, fraction, timecreated FROM {question_attempt_steps} WHERE questionattemptid = ?", [(int)$q->id]));
        usort($steps, fn($x,$y) => (int)$x->sequencenumber <=> (int)$y->sequencenumber);
        $seq = []; $hasComplete = false; $final = null; $finalT = null;
        foreach ($steps as $s) {
            $tc = (int)$s->timecreated;
            $firstAct = $firstAct === null ? $tc : min($firstAct, $tc);
            $lastAct = $lastAct === null ? $tc : max($lastAct, $tc);
            if ($s->state === 'todo') $views++;
            if ($s->state === 'complete') { $checks++; $hasComplete = true; }
            if (in_array($s->state, ['gradedright','gradedpartial','gradedwrong'])) {
                $final = $s->state; $finalT = $tc;
                $graded++; $gradedTotal++;
                if ($s->state === 'gradedright') $right++;
            }
            $seq[] = $s->state;
        }
        // no-complete anomaly: a scored (graded) question with no preceding complete
        if ($final && !$hasComplete) $noComplete++;
        $qTraces[(int)$q->slot] = $seq;
    }
    $dur = (int)$a->timefinish - (int)$a->timestart;
    $score = (float)$a->sumgrades; // out of 4
    $rows[] = [
        'uid' => $uid, 'name' => trim($u->lastname.' '.$u->firstname), 'email' => $u->email,
        'grp' => implode(',', $groups[$uid] ?? ['-']),
        'dur' => $dur, 'score' => $score, 'right' => $right, 'checks' => $checks,
        'views' => $views, 'noComplete' => $noComplete, 'graded' => $graded,
        'traces' => $qTraces,
        'ips' => $ipByUser[$uid] ?? [],
    ];
}

// suspicion score: higher = more suspicious
// components: fast (dur low), high score, no-check anomaly
foreach ($rows as &$r) {
    $susp = 0;
    $susp += $r['noComplete'] * 3;                 // strongest: graded w/o any check
    $susp += ($r['dur'] <= 600) ? 3 : ($r['dur'] <= 720 ? 2 : ($r['dur'] <= 900 ? 1 : 0)); // fast
    $susp += $r['score'];                          // correctness
    $susp += max(0, (4 - $r['checks'])) * 0.5;     // fewer checks
    $r['susp'] = round($susp, 2);
}
unset($r);
usort($rows, fn($a,$b) => $b['susp'] <=> $a['susp']);

echo "cohort (finished, real): " . count($rows) . "\n\n";
echo "=== TOP 25 by suspicion ===\n";
printf("%-4s %-22s %-14s %-9s %5s %5s %6s %5s %5s %s\n", "#", "name", "group", "mins", "score", "chk", "nocomp", "views", "susp", "IPs");
$i = 0;
foreach ($rows as $r) {
    if ($i++ > 24) break;
    $ipl = '';
    if ($r['ips']) { $top = $r['ips']; arsort($top); $ipl = implode(',', array_slice(array_keys($top), 0, 2)); }
    printf("%-4d %-22s %-14s %-9d %5.1f %5d %6d %5d %5.1f %s\n",
        $i, mb_substr($r['name'],0,22), mb_substr($r['grp'],0,14), (int)($r['dur']/60), $r['score'], $r['checks'], $r['noComplete'], $r['views'], $r['susp'], $ipl);
}

// The no-complete cohort, full detail
echo "\n=== NO-CHECK ANOMALY (scored questions graded WITHOUT any Check) ===\n";
$nc = array_filter($rows, fn($r) => $r['noComplete'] > 0);
usort($nc, fn($a,$b) => ($b['noComplete'] <=> $a['noComplete']) ?: ($a['dur'] <=> $b['dur']));
foreach ($nc as $r) {
    $ipl = $r['ips'] ? implode(', ', array_keys($r['ips'])) : 'no-ip';
    echo "\n".$r['name'].' | '.$r['email'].' | '.$r['grp']." | ".(int)($r['dur']/60)."min | score ".$r['right']."/4 | nocomp=".$r['noComplete']." | ips=".$ipl."\n";
    foreach ([2,3,4,5] as $s) if (isset($r['traces'][$s])) echo "    s$s: " . implode(',', $r['traces'][$s]) . "\n";
}
echo "\ntotal no-check-anomaly students: " . count($nc) . "\n";
