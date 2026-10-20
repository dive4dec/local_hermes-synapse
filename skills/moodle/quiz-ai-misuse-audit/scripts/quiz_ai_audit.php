<?php
// Portable params (see skills/_conventions/PORTABLE.md). Override via env; defaults match a standard layout.
$WEBROOT  = getenv('MHS_WEBROOT')  ?: '/var/www/html/public';
$DATA_DIR = getenv('MHS_DATA_DIR') ?: '/var/www/moodledata';

// Quiz AI-misuse audit — TYPE-AWARE step-trace analysis (Check for MC, Precheck for CodeRunner).
// Setup for YOUR deployment (env vars or edit the two require lines):
//   MOODLE_ROOT  = path to your Moodle root (dir containing config.php)   [default <webroot>]
//   HERMES_HOME  = your hermes home to run from                            [default <datadir>/.hermes]
// Usage: set $QUIZ, then:  cd $HERMES_HOME && timeout 300 php -d display_errors=1 /tmp/quiz_ai_audit.php
// Handles the key pitfalls:
//   - get_records_sql keys by FIRST selected column -> always SELECT id first
//   - usort/array_merge reindex int keys -> sort array_keys() separately
//   - CodeRunner "Precheck" is a '-precheck' flag in step_data, NOT a step state
//     (counting only state='complete' misses every Precheck -> false positives)
define('CLI_SCRIPT', true);
define('MOODLE_INTERNAL', true);
$MOODLE_ROOT = getenv('MOODLE_ROOT') ?: '/var/www/html/public';  // <-- change for your install
require($MOODLE_ROOT . '/config.php');
require_once($MOODLE_ROOT . '/lib/setup.php');
global $DB;

$QUIZ = 57;   // set to your quiz id
$CID  = 3;    // set to your course id (used only for group names)
$VERIFY_TOP = 15;  // students with total verifications <= this are "rare verifier"
$SCORE_MIN = 90;   // ...and scoring at least this %

$Q = fn($sql, $p = []) => $DB->get_records_sql($sql, $p);
function t($l,$fn){ try { return $fn(); } catch (Throwable $e){ echo "ERR $l: ".$e->getMessage()."\n"; exit(1);} }

$attempts = t('at', fn() => $Q("SELECT id, userid, uniqueid, timestart, timefinish, sumgrades FROM {quiz_attempts} WHERE quiz = $QUIZ AND preview = 0 AND timefinish > 0"));
$uids = array_unique(array_map('intval', array_column($attempts, 'userid')));
$in = implode(',', $uids);
$users = t('u', fn() => $Q("SELECT id, firstname, lastname, email FROM {user} WHERE id IN ($in)"));
$groups = [];
$g = t('g', fn() => $Q("SELECT gm.userid, gr.name FROM {groups_members} gm JOIN {groups} gr ON gr.id = gm.groupid WHERE gr.courseid = $CID AND gm.userid IN ($in)"));
foreach ($g as $r) $groups[(int)$r->userid][] = $r->name;

$uins = implode(',', array_unique(array_map('intval', array_column($attempts, 'uniqueid'))));
$qas = t('qas', fn() => $Q("SELECT qa.id, qa.questionusageid, qa.slot, qa.maxmark, q.qtype
    FROM {question_attempts} qa JOIN {question} q ON q.id = qa.questionid
    WHERE qa.questionusageid IN ($uins)"));

$qaids = array_map('intval', array_column($qas, 'id'));
$check = []; $precheck = []; $graded = []; $gradedRight = [];
foreach (array_chunk($qaids, 100) as $chunk) {
    $cin = implode(',', $chunk);
    $rows = t('st', fn() => $Q("SELECT qast.id, qast.questionattemptid, qast.state,
            (CASE WHEN qsd.name = '-precheck' THEN 1 ELSE 0 END) AS ispre
        FROM {question_attempt_steps} qast
        LEFT JOIN {question_attempt_step_data} qsd ON qsd.attemptstepid = qast.id AND qsd.name = '-precheck'
        WHERE qast.questionattemptid IN ($cin)"));
    foreach ($rows as $s) {
        $q = (int)$s->questionattemptid;
        if ($s->ispre) $precheck[$q] = ($precheck[$q]??0)+1;
        elseif ($s->state === 'complete') $check[$q] = ($check[$q]??0)+1;
        if (in_array($s->state, ['gradedright','gradedpartial','gradedwrong'])) {
            $graded[$q] = 1;
            if ($s->state === 'gradedright') $gradedRight[$q] = 1;
        }
    }
}

$am = [];
foreach ($attempts as $a) {
    $uid = (int)$a->userid; $usage = (int)$a->uniqueid;
    $dur = (int)$a->timefinish - (int)$a->timestart;
    $right = 0.0; $maxq = 0.0; $mcCheck = 0; $codePre = 0; $gradedQ = 0;
    $perQ = [];
    foreach ($qas as $qa) {
        if ((int)$qa->questionusageid !== $usage) continue;
        $q = (int)$qa->id; $slot = (int)$qa->slot;
        if ($slot === 1) continue;
        $maxq += (float)$qa->maxmark;
        $v = $check[$q] ?? 0; $p = $precheck[$q] ?? 0;
        $isMC = ($qa->qtype === 'multichoice');
        $qv = $isMC ? $v : $p;             // TYPE-AWARE verification
        if ($isMC) $mcCheck += $v; else $codePre += $p;
        $final = $graded[$q] ? ($gradedRight[$q] ? 'R' : 'P') : '-';
        $perQ[$slot] = [$qv, (float)$qa->maxmark, $final];
        if ($graded[$q] ?? 0) { $gradedQ++; if ($gradedRight[$q] ?? 0) $right += (float)$qa->maxmark; }
    }
    $verify = $mcCheck + $codePre;
    $unver = 0; foreach ($perQ as $s) if ($s[0] === 0) $unver++;
    $am[$uid] = ['dur'=>$dur, 'score'=>(float)$a->sumgrades, 'maxq'=>$maxq,
        'pct'=> $maxq?round(100*(float)$a->sumgrades/$maxq,1):0,
        'mcCheck'=>$mcCheck, 'codePre'=>$codePre, 'verify'=>$verify, 'unver'=>$unver,
        'graded'=>$gradedQ, 'perQ'=>$perQ, 'att'=>$a];
}

$fin = [];
foreach ($am as $uid=>$r) { $u=$users[$uid]??null; if(!$u || stripos($u->email,'altitest')!==false) continue; $fin[$uid]=$r; }

$vd = array_count_values(array_map(fn($r)=>$r['verify'], $fin)); ksort($vd);
echo "=== verify (MC-Checks + Code-Prechecks) distribution, n=".count($fin)." ===\n";
echo json_encode($vd)."\n";
$ps = array_map(fn($r)=>$r['pct'],$fin); sort($ps);
$pc = fn($p) => $ps[(int)floor($p/100*(count($ps)-1))];
echo "score pct: p10=".round($pc(10),1)." p25=".round($pc(25),1)." p50=".round($pc(50),1)." p75=".round($pc(75),1)."\n";
$durs = array_map(fn($r)=>$r['dur'], $fin); sort($durs);
echo "duration med=".round($durs[(int)floor(0.5*(count($durs)-1))]/60,1)."min\n\n";

echo "=== RARE VERIFIERS (verify <= $VERIFY_TOP), any score ===\n";
$low = array_filter($fin, fn($r)=>$r['verify'] <= $VERIFY_TOP);
ksort($low);
printf("%-24s %-12s %7s %5s %4s %4s %4s\n","name","group","dur(m)","pct%","mcChk","codePre","unver");
foreach ($low as $uid=>$r) { $u=$users[$uid];
    printf("%-24s %-12s %7.1f %5.0f %4d %4d %4d\n", mb_substr(trim($u->lastname.' '.$u->firstname),0,24),
        mb_substr(implode(',',$groups[$uid]??['-']),0,12), $r['dur']/60, $r['pct'], $r['mcCheck'], $r['codePre'], $r['unver']);
}

echo "\n=== FOCUS: verify <= $VERIFY_TOP AND score >= $SCORE_MIN% ===\n";
$foc = array_filter($fin, fn($r)=>$r['verify'] <= $VERIFY_TOP && $r['pct'] >= $SCORE_MIN);
$fk = array_keys($foc); usort($fk, fn($a,$b)=> $foc[$a]['verify']<=>$foc[$b]['verify'] ?: $foc[$a]['pct']<=>$foc[$b]['pct']);
printf("%-24s %-12s %7s %5s %4s %4s %4s\n","name","group","dur(m)","pct%","mcChk","codePre","unver");
foreach ($fk as $uid) { $u=$users[$uid]; $r=$foc[$uid];
    printf("%-24s %-12s %7.1f %5.0f %4d %4d %4d\n", mb_substr(trim($u->lastname.' '.$u->firstname),0,24),
        mb_substr(implode(',',$groups[$uid]??['-']),0,12), $r['dur']/60, $r['pct'], $r['mcCheck'], $r['codePre'], $r['unver']);
}

echo "\n=== per-slot verification matrix (slots 2-11 MC Checks, 12-17 Code Prechecks; x=verify count, /R or /P = final) ===\n";
$show = [];
foreach ($fin as $uid=>$r) {
    $nm = trim($users[$uid]->lastname.' '.$users[$uid]->firstname);
    if (($r['verify'] <= $VERIFY_TOP && $r['pct'] >= $SCORE_MIN)) $show[$uid] = $nm;
}
$slots = array_map(fn($qa)=>(int)$qa->slot, $qas);
foreach ($show as $uid=>$nm) { $r=$fin[$uid]; $line=[];
    foreach (range(2, max($slots)+0) as $slot) { $s = $r['perQ'][$slot] ?? [0,0,'-']; $line[] = str_pad($s[0],2).'/'.$s[2]; }
    printf("%-18s: mcChk=%-2d codePre=%-3d pct=%-5s | %s\n", mb_substr($nm,0,18), $r['mcCheck'], $r['codePre'], $r['pct'].'%', implode(' ', $line));
}
echo "\nNOTE: 0 on an MC slot = never hit Check (rare/flag). 0 on a code slot = never Prechecked (can be benign for 1-line code, but combined w/ fast+high = flag). A student with HIGH code-precheck counts (iterating) is NOT a 'few checks' flag — do not flag on low mcCheck alone.\n";
