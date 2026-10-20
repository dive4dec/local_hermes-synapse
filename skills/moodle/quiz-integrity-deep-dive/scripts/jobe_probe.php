<?php
// Portable params (see skills/_conventions/PORTABLE.md). Override via env; defaults match a standard layout.
$WEBROOT  = getenv('MHS_WEBROOT')  ?: '/var/www/html/public';
$DATA_DIR = getenv('MHS_DATA_DIR') ?: '/var/www/moodledata';

// Jobe health probe — run from the Moodle pod:
//   cd <datadir>/.hermes && timeout 300 php skills/moodle/quiz-integrity-deep-dive/scripts/jobe_probe.php
// Tests: trivial script, big loop, infinite loop (must be killed ~5-6s), and
// 12 concurrent infinite-loop jobs (must all return, ~8s wall). Read-only.
define('CLI_SCRIPT', true);
define('MOODLE_INTERNAL', true);
require($WEBROOT.'/config.php');
require_once($WEBROOT.'/lib/setup.php');
$host = get_config('qtype_coderunner', 'jobe_host');
$apikey = get_config('qtype_coderunner', 'jobe_apikey');
echo "jobe_host=$host\n";

function jobe($code, $timeout = 120, $ch = null) {
    global $host, $apikey;
    $postbody = ['run_spec' => ['language_id' => 'python3', 'sourcecode' => $code,
        'sourcefilename' => '__tester__.python3', 'input' => '', 'file_list' => []]];
    if (!$ch) {
        $ch = curl_init("http://$host/jobe/index.php/restapi/runs");
        curl_setopt_array($ch, [
            CURLOPT_POST => true, CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => $timeout,
            CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Accept: application/json',
                'User-Agent: CodeRunner', "X-API-KEY: $apikey"],
        ]);
    } else {
        curl_setopt_array($ch, [CURLOPT_POSTFIELDS => json_encode($postbody)]);
    }
    curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($postbody));
    $t0 = microtime(true);
    $body = curl_exec($ch);
    $err = curl_error($ch);
    $http = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $dt = round(microtime(true) - $t0, 1);
    $j = json_decode($body);
    $outcome = $j ? ($j->outcome ?? 'n/a') : '?';
    echo "  HTTP $http, {$dt}s, outcome=$outcome" . ($err ? " CURLERR:$err" : "") . "\n";
    if (!$ch->owned) { curl_close($ch); }
    return $ch;
}

echo "single trivial:\n";  jobe('print("hi")');
echo "single 100k-iter loop:\n"; jobe("x=0\nfor i in range(100000): x+=1\nprint(x)");
echo "single INFINITE LOOP (expect ~6s, outcome=13 time-limit):\n"; jobe("while True:\n    pass");

echo "12 concurrent infinite-loop jobs (expect all return in ~8s wall):\n";
$mh = curl_multi_init();
$t0 = microtime(true);
for ($i = 0; $i < 12; $i++) {
    $ch = curl_init("http://$host/jobe/index.php/restapi/runs");
    $postbody = ['run_spec' => ['language_id' => 'python3', 'sourcecode' => 'x=0\nwhile x<10**12: x+=1',
        'sourcefilename' => '__tester__.python3', 'input' => '', 'file_list' => []]];
    curl_setopt_array($ch, [CURLOPT_POST => true, CURLOPT_POSTFIELDS => json_encode($postbody),
        CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 120,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Accept: application/json',
            'User-Agent: CodeRunner', "X-API-KEY: $apikey"]]);
    curl_multi_add_handle($mh, $ch);
}
$active = null;
do { curl_multi_exec($mh, $active); curl_multi_select($mh, 0.05); } while ($active > 0);
echo "  wall time: " . round(microtime(true) - $t0, 1) . "s for all 12\n";
curl_multi_close($mh);
echo "VERDICT: if single runs are <1s, infinite loop ~5-6s, and 12 concurrent all return quickly,\n"
   . "the runner is healthy and 'infinite loops hung the server' cannot explain dropped checks.\n";
