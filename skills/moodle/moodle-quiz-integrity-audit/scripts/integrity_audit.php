<?php
// Portable params (see skills/_conventions/PORTABLE.md). Override via env; defaults match a standard layout.
$WEBROOT  = getenv('MHS_WEBROOT')  ?: '/var/www/html/public';
$DATA_DIR = getenv('MHS_DATA_DIR') ?: '/var/www/moodledata';

// moodle-quiz-integrity-audit — reusable per-question step-trace audit.
// Copy, edit the CONFIG block, run:
//   cd <datadir>/.hermes && php -d display_errors=1 /tmp/integrity_audit.php
// Reads only (no writes). Outputs: stats, PRIMARY flags, WATCH list, and the
// no-check-anomaly cohort with per-question traces.
define('CLI_SCRIPT', true);
define('MOODLE_INTERNAL', true);
require($WEBROOT.'/config.php');
require_once($WEBROOT.'/lib/setup.php');
global $DB;
$Q = fn($sql, $p = []) => $DB->get_records_sql($sql, $p);
function t($l, $fn) { try { return $fn(); } catch (Throwable $e) { echo "ERR $l: " . $e->getMessage() . "\n"; exit(1); } }

// ===== CONFIG =====
$QUIZ      = 58;          // mdl_quiz.id  (CE-Quiz 1 = 58)
$COURSE    = 3;           // course id, for group lookup (<coursecode> = 3)
$INFO_SLOT = 1;           // first non-graded slot (info page)
$MAX_SCORE = 4;           // sum of maxmark over graded slots (DO NOT use mdl_quiz.grade)
$MIN_SCORE = 0.75;        // primary: min score fraction
$FAST_SEC  = 720;         // primary: max duration seconds (12 min)
$WATCH_SEC = 900;         // watch list: max duration seconds (15 min)
$SKIP_EMAIL_SUBSTR = 'altitest'; // test accounts
// ==================

$attempts = t('at', fn() => $Q("SELECT id, userid, uniqueid, timestart, timefinish, sumgrades FROM {quiz_attempts} WHERE quiz = ? AND preview = 0 AND timefinish > 0", [$QUIZ]));
$uins = implode(',', array_unique(array_map('intval', array_column($attempts, 'uniqueid'))));
$in   = implode(',', array_unique(array_map('intval', array_column($attempts, 'userid'))));
$users = t('u', fn() => $Q("SELECT id, firstname, lastname, email, auth FROM {user} WHERE id IN ($in)"));
$groups = [];
$g = t('g', fn() => $Q("SELECT gm.id, gm.userid, g2.name FROM {groups_members} gm JOIN {groups} g2 ON g2.id = gm.groupid WHERE g2.courseid = ? AND gm.userid IN ($in)", [$COURSE]));
foreach ($g as $r) $groups[(int)$r->userid][] = $r->name;

$rows = [];
$qtypeSeen = [];
foreach ($attempts as $a) {
    $uid = (int)$a->userid; $u = $users[$uid] ?? null;
    if (!$u || stripos((string)$u->email, $SKIP_EMAIL_SUBSTR) !== false) continue;
    // verify true score scale from maxmark (should equal $MAX_SCORE)
    $qas = t('qas', fn() => $Q("SELECT qa.id, qa.slot, qa.maxmark, qa.responsesummary, q.qtype FROM {question_attempts} qa JOIN {question} q ON q.id = qa.questionid WHERE qa.questionusageid = ?", [(int)$a->uniqueid]));
    $sumMax = 0;
    foreach ($qas as $q) { if ((int)$q->slot > $INFO_SLOT) { $sumMax += (float)$q->maxmark; $qtypeSeen[$q->qtype] = 1; } }
    $scale = $sumMax > 0 ? $sumMax : $MAX_SCORE;

    $checks = 0; $prechecks = 0; $views = 0; $right = 0; $graded = 0; $noVerify = 0; $filled = 0;
    $traces = []; $gradeTimes = [];
    foreach ($qas as $q) {
        if ((int)$q->slot <= $INFO_SLOT) continue;
        if (trim((string)$q->responsesummary) !== '') $filled++;
        // TYPE-AWARE: Check = state 'complete' (MC/standard); Precheck = '-precheck' step_data flag (CodeRunner).
        // A Precheck step's state can be 'todo' OR 'complete' — the flag is what identifies it.
        $steps = t('st', fn() => $Q("SELECT qast.id, qast.sequencenumber, qast.state, qast.timecreated,
                (CASE WHEN qsd.name = '-precheck' THEN 1 ELSE 0 END) AS ispre
            FROM {question_attempt_steps} qast
            LEFT JOIN {question_attempt_step_data} qsd ON qsd.attemptstepid = qast.id AND qsd.name = '-precheck'
            WHERE qast.questionattemptid = ?", [(int)$q->id]));
        usort($steps, fn($x, $y) => (int)$x->sequencenumber <=> (int)$y->sequencenumber);
        $seq = []; $verified = false; $final = null;
        foreach ($steps as $s) {
            if ($s->state === 'todo' && !$s->ispre) $views++;
            if ($s->ispre) { $prechecks++; $verified = true; }
            elseif ($s->state === 'complete') { $checks++; $verified = true; }
            if (in_array($s->state, ['gradedright', 'gradedpartial', 'gradedwrong'])) {
                $final = $s->state; $graded++;
                if ($s->state === 'gradedright') { $right++; $gradeTimes[] = (int)$s->timecreated; }
            }
            $seq[] = $s->state . ($s->ispre ? '(P)' : '');
        }
        if ($final && !$verified) $noVerify++;
        $traces[(int)$q->slot] = $seq;
    }
    $dur = (int)$a->timefinish - (int)$a->timestart;
    $score = (float)$a->sumgrades;
    $scorePct = $score / $scale;
    $verifies = $checks + $prechecks; // total verifications (Check + Precheck)
    $retries = $verifies - $graded;
    $spread = $gradeTimes ? (max($gradeTimes) - min($gradeTimes)) : null;
    $firsttry = ($right === count(array_diff(array_keys($traces), [$INFO_SLOT]))) && ($retries <= 0);

    $rows[] = [
        'uid' => $uid, 'name' => trim($u->lastname . ' ' . $u->firstname), 'email' => $u->email,
        'grp' => implode(',', $groups[$uid] ?? ['-']), 'dur' => $dur, 'score' => $score,
        'scorePct' => $scorePct, 'right' => $right, 'checks' => $checks, 'prechecks' => $prechecks,
        'views' => $views, 'noVerify' => $noVerify, 'graded' => $graded, 'retries' => $retries,
        'filled' => $filled, 'spread' => $spread, 'firsttry' => $firsttry, 'traces' => $traces,
    ];
}
if (isset($qtypeSeen['coderunner'])) {
    echo "NOTE: quiz contains CodeRunner questions — verification counted type-aware (Check for MC, Precheck for code). Without this, code-question Prechecks are invisible and debugging-heavy students get false-flagged.\n\n";
}

// PRIMARY: high score + fast + all-first-try + never self-verified (no Check and no Precheck)
$primary = array_filter($rows, fn($r) => $r['scorePct'] >= $MIN_SCORE && $r['dur'] <= $FAST_SEC && $r['firsttry'] && $r['noVerify'] >= count(array_diff(array_keys($r['traces']), [$INFO_SLOT])));
// WATCH: fast + high, not already primary
$watch = array_filter($rows, fn($r) => $r['scorePct'] >= $MIN_SCORE && $r['dur'] <= $WATCH_SEC && !isset($primary[$r['uid']]));
// no-verify cohort detail (any noVerify>0), most severe first
$nc = array_filter($rows, fn($r) => $r['noVerify'] > 0);
$primaryKeys = array_keys($primary); $watchKeys = array_keys($watch); $ncKeys = array_keys($nc);
usort($primaryKeys, fn($a, $b) => $primary[$a]['dur'] <=> $primary[$b]['dur']);
usort($watchKeys,   fn($a, $b) => $watch[$a]['dur'] <=> $watch[$b]['dur']);
usort($ncKeys,      fn($a, $b) => ($nc[$b]['noVerify'] <=> $nc[$a]['noVerify']) ?: ($nc[$a]['dur'] <=> $nc[$b]['dur']));

$durs = array_map(fn($r) => $r['dur'], $rows); sort($durs);
$pk = fn($p) => $durs[(int)floor($p / 100 * (count($durs) - 1))];
echo "finished real attempts: " . count($rows) . " | dur(s) min={$durs[0]} med=" . $pk(50) . " p90=" . $pk(90) . " max=" . $durs[count($durs) - 1] . "\n";
echo "score>=threshold: " . count(array_filter($rows, fn($r) => $r['scorePct'] >= $MIN_SCORE)) . "/" . count($rows) . "\n\n";

echo "=== PRIMARY FLAGS (" . count($primary) . "): high score + fast + first-try-all-right + NEVER self-verified ===\n";
$i = 0;
foreach ($primaryKeys as $k) { $r = $primary[$k]; $i++;
    printf("%2d. %-24s %-28s %-14s %dmin %s/%s noVerify=%d checks=%d prechecks=%d spread=%ds filled=%d\n", $i,
        mb_substr($r['name'], 0, 24), $r['email'], mb_substr($r['grp'], 0, 14),
        (int)($r['dur'] / 60), $r['right'], $MAX_SCORE, $r['noVerify'], $r['checks'], $r['prechecks'], $r['spread'] ?? -1, $r['filled']); }

echo "\n=== WATCH (" . count($watch) . "): fast + high but with some verification (weaker signal) ===\n";
$i = 0;
foreach ($watchKeys as $k) { $r = $watch[$k]; $i++; if ($i > 15) { echo "  ..." . (count($watch) - 15) . " more\n"; break; }
    printf("%2d. %-24s %-28s %-14s %dmin %s/%s checks=%d prechecks=%d noVerify=%d\n", $i,
        mb_substr($r['name'], 0, 24), $r['email'], mb_substr($r['grp'], 0, 14),
        (int)($r['dur'] / 60), $r['right'], $MAX_SCORE, $r['checks'], $r['prechecks'], $r['noVerify']); }

echo "\n=== NO-VERIFY ANOMALY DETAIL (scored questions graded without any Check/Precheck) ===\n";
foreach ($ncKeys as $k) { $r = $nc[$k];
    echo "\n" . $r['name'] . ' | ' . $r['email'] . ' | ' . $r['grp'] . " | " . (int)($r['dur'] / 60) . "min | " . $r['right'] . "/" . $MAX_SCORE . " | noverify=" . $r['noVerify'] . " | checks=" . $r['checks'] . " | prechecks=" . $r['prechecks'] . " | spread=" . ($r['spread'] ?? '-') . "s\n";
    foreach ($r['traces'] as $slot => $seq) echo "    s$slot: " . implode(',', $seq) . "\n"; }

echo "\nNOTE: primary flag is an INDICATOR, not proof. Verify by pulling responsesummary and comparing for verbatim matches / off-campus IP (moodle_audit_quiz).\n";
