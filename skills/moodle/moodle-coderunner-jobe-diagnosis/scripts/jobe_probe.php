<?php
// jobe_probe.php — READ-ONLY Jobe health + head-of-line-blocking probe.
// Reads jobe_host/jobe_apikey from the live Moodle config, then fires:
//   1) trivial script            (expect ~0.2s, outcome 15)
//   2) bounded 100k-iter loop    (expect ~0.2s)
//   3) infinite loop             (expect killed ~cputime+1s, outcome 13)
//   4) 30 concurrent jobs: 15 trivial + 15 infinite loops (HOL-blocking check)
// Safe to run while students are active: only REST 'runs' calls, no config writes.
// Usage: php jobe_probe.php
define('CLI_SCRIPT', true);
define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php');
require_once('/var/www/html/public/lib/setup.php');

$c = $CFG;
$port = !empty($c->dbport) ? (int)$c->dbport : 3306;
$host = $c->dbhost ?: 'localhost';
$m = new mysqli($host, $c->dbuser, $c->dbpass, $c->dbname, $port);
$m->set_charset('utf8mb4');
$jobeserver = ''; $apikey = '';
$r = $m->query("SELECT name, value FROM mdl_config_plugins WHERE plugin='qtype_coderunner' AND name IN ('jobe_host','jobe_apikey')");
if ($r) while ($x = $r->fetch_assoc()) { if ($x['name'] == 'jobe_host') $jobeserver = $x['value']; else $apikey = $x['value']; }
if (!$jobeserver || !$apikey) { fwrite(STDERR, "jobe_host/jobe_apikey not found in config\n"); exit(1); }
$base = (strpos($jobeserver, 'http') === 0 ? $jobeserver : 'http://' . $jobeserver) . '/jobe/index.php/restapi/runs';
echo "Jobe base: $base\n";

function jcall($base, $apikey, $code) {
    $post = ['run_spec' => ['language_id' => 'python3', 'sourcecode' => $code, 'sourcefilename' => '__tester__.python3', 'input' => '', 'file_list' => []]];
    $ch = curl_init($base);
    curl_setopt_array($ch, [
        CURLOPT_POST => true, CURLOPT_POSTFIELDS => json_encode($post),
        CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 120,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Accept: application/json', 'User-Agent: CodeRunner', 'X-API-KEY: ' . $apikey],
    ]);
    $body = curl_exec($ch);
    $err = curl_error($ch);
    $http = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $t = curl_getinfo($ch, CURLINFO_TOTAL_TIME);
    curl_close($ch);
    $j = json_decode($body);
    return ['t' => $t, 'http' => $http, 'outcome' => ($j && isset($j->outcome)) ? $j->outcome : '?', 'err' => $err];
}
function one($label, $r) { printf("  [%s] HTTP %s, %.1f s, outcome=%s%s\n", $label, $r['http'], round($r['t'], 1), $r['outcome'], $r['err'] ? ' CURLERR:' . $r['err'] : ''); }

echo "\n1) trivial script:\n";
one('trivial', jcall($base, $apikey, "print('hi')"));
echo "\n2) bounded 100k-iter loop:\n";
one('loop100k', jcall($base, $apikey, "x=0\nfor i in range(100000): x+=1\nprint(x)"));
echo "\n3) infinite loop (should be killed by cputime limit):\n";
one('INFINITE', jcall($base, $apikey, "while True:\n    pass"));

echo "\n4) HOL-blocking test: 30 concurrent (15 trivial + 15 infinite loops):\n";
$N = 30; $mh = curl_multi_init(); $t0 = microtime(true);
$loop = "while True:\n    pass"; $triv = "print('hi')";
$handles = [];
for ($i = 0; $i < $N; $i++) {
    $code = ($i % 2 == 0) ? $triv : $loop;
    $post = ['run_spec' => ['language_id' => 'python3', 'sourcecode' => $code, 'sourcefilename' => '__tester__.python3', 'input' => '', 'file_list' => []]];
    $ch = curl_init($base);
    curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_POSTFIELDS => json_encode($post), CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 180,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Accept: application/json', 'User-Agent: ' . 'CodeRunner', 'X-API-KEY: ' . $apikey]]);
    curl_multi_add_handle($mh, $ch);
    $handles[$i] = ['ch' => $ch, 'triv' => ($i % 2 == 0)];
}
$active = null;
do { curl_multi_exec($mh, $active); curl_multi_select($mh, 0.05); } while ($active > 0);
$wall = microtime(true) - $t0;
$tt = []; $ll = [];
for ($i = 0; $i < $N; $i++) {
    $t = curl_getinfo($handles[$i]['ch'], CURLINFO_TOTAL_TIME);
    $handles[$i]['triv'] ? $tt[] = $t : $ll[] = $t;
}
$avg = function ($a) { return $a ? array_sum($a) / count($a) : 0; };
printf("  wall=%.1fs | TRIVIAL n=%d avg=%.1fs max=%.1fs | LOOPS n=%d avg=%.1fs max=%.1fs\n",
    round($wall, 1), count($tt), $avg($tt), max($tt), count($ll), $avg($ll), max($ll));
if (max($tt) > 2.0) {
    echo "  *** HEAD-OF-LINE BLOCKING: trivial checks were queued behind loop jobs ***\n";
    echo "  => 'check freeze' during bursts is explained by single-Jobe queueing. Fixes: scale jobe_host (;-list), lower wsmaxcputime.\n";
} else {
    echo "  trivial checks not materially delayed at this concurrency.\n";
}
curl_multi_close($mh);
