<?php
/**
 * jobe_capacity_probe.php — measure a Jobe pod's REAL concurrent-execution
 * parallelism (read-only; safe to run during a live quiz).
 *
 * Usage:  php jobe_capacity_probe.php [loop_counts_csv]
 * Default batch sizes: 8,16,32,48. Baseline for one loop ≈ 6.2 s
 * (5 s CPU limit + ~1.2 s overhead) — adjust BASELINE if wsmaxcputime differs.
 *
 * Theory: configured "N runners" = concurrent slots, not CPUs. A CPU-saturating
 * infinite loop pins one core until the 5 s kill. Firing N loops at once:
 *   implied parallelism ≈ N / ceil(wall / BASELINE)
 * If that is well below the configured slot count, the pod is CPU-quota-bound:
 * normal checks queue behind loops AND Jobe's own Apache/PHP is starved —
 * that is the in-class "check freeze". Fix = more CPU / more pods, NOT more slots.
 */
if (!defined('CLI_SCRIPT')) die('CLI only');
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php');
require_once('/var/www/html/public/lib/setup.php');

// jobe_host / jobe_apikey from coderunner config (single-host assumption)
$host = $DB->get_record('config_plugins', ['plugin' => 'qtype_coderunner', 'name' => 'jobe_host'], 'value');
$host = trim(explode(';', $host->value ?? '')[0]);
$key  = $DB->get_record('config_plugins', ['plugin' => 'qtype_coderunner', 'name' => 'jobe_apikey'], 'value')?->value ?? '';
$BASELINE = 6.2;
$counts = isset($argv[1]) ? array_map('intval', explode(',', $argv[1])) : [8, 16, 32, 48];

$loop  = "while True:\n    pass";
$code  = "print('x')";
$ep    = $host . '/jobe/index.php/restapi/runs';

function burst($ep, $key, $list) {
    $N = count($list); $mh = curl_multi_init(); $start = microtime(true);
    for ($i = 0; $i < $N; $i++) {
        $pb = ['run_spec' => ['language_id' => 'python3', 'sourcecode' => $list[$i],
                              'sourcefilename' => '__tester__.python3', 'input' => '', 'file_list' => []]];
        $ch = curl_init($ep);
        curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_POSTFIELDS => json_encode($pb),
            CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 300,
            CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Accept: application/json',
                                   'User-Agent: CodeRunner', 'X-API-KEY: ' . $key]]);
        curl_multi_add_handle($mh, $ch); $hs[$i] = $ch;
    }
    $active = null;
    do { curl_multi_exec($mh, $active); curl_multi_select($mh, 0.05); } while ($active > 0);
    $wall = microtime(true) - $start;
    $ts = [];
    foreach ($hs as $ch) $ts[] = curl_getinfo($ch, CURLINFO_TOTAL_TIME);
    return [round($wall, 1), round(array_sum($ts) / count($ts), 1), round(max($ts), 1)];
}

echo "Jobe: $ep\nBaseline (1 loop) = {$BASELINE}s\n\n";
foreach ($counts as $n) {
    $a = burst($ep, $key, array_fill(0, $n, $loop));
    $implied = round($n / ceil($a[0] / $BASELINE), 0);
    printf("%-4d loops -> wall=%5.1f avg=%5.1f max=%5.1f   (implied parallelism ~%d)\n",
           $n, $a[0], $a[1], $a[2], $implied);
    usleep(500000);
}
$a = burst($ep, $key, array_fill(0, end($counts), $code));
printf("sanity: %-3d trivial -> wall=%5.1f avg=%5.1f max=%5.1f (should be <1s if pod idle)\n",
       end($counts), $a[0], $a[1], $a[2]);
echo "\nReading: if implied parallelism << configured slots, the pod is CPU-quota-bound.\n";
echo "30 trivial checks are then fine; the freeze appears in MIXED load (loops pin cores).\n";
