<?php
// campus-smtp-email batch sender.
// Usage:  php /var/www/moodledata/.hermes/skills/moodle/campus-smtp-email/scripts/send_mail.php \
//             --from <staff-email> --from-name "<Instructor-Name>" \
//             --subject "..." --body-file /tmp/body.txt \
//             (--to a@x.com[,b@y.com,...] | --roster "SELECT u.id,u.firstname,u.lastname,u.email FROM ... WHERE ...")
//          --log /tmp/batch.log  (optional; default /tmp/send_<ts>.log)
// Exit 0 = all accepted; exit 2 = some failed (log shows which).

error_reporting(E_ALL);

function argv_get($name, $default = null) {
    global $argv;
    foreach ($argv as $i => $a) {
        if ($a === '--' . $name && isset($argv[$i + 1])) return $argv[$i + 1];
    }
    return $default;
}

function smtp_send($to, $toName, $subject, $body, $from, $fromName) {
    $HOST = '<smtp-host>'; $PORT = 587;
    $c = @stream_socket_client("tcp://$HOST:$PORT", $e, $es, 10);
    if (!$c) return ['ok' => false, 'resp' => "CONNECT FAIL: $es", 'qid' => '-'];
    stream_set_timeout($c, 15);
    $rd = function ($c) {
        $o = '';
        while (($l = fgets($c, 1024)) !== false) { $o .= $l; if (isset($l[3]) && $l[3] === ' ') break; }
        return $o;
    };
    $cmd = function ($c, $l) use ($rd) { fwrite($c, $l . "\r\n"); return $rd($c); };
    $okf = function ($r, $p) { return strpos($r, $p) === 0; };

    $rd($c);
    if (!$okf($cmd($c, 'EHLO cs1302a.cityu.local'), '250')) { fclose($c); return ['ok' => false, 'resp' => 'EHLO fail', 'qid' => '-']; }
    if (!$okf($cmd($c, "MAIL FROM:<$from>"), '250')) { fclose($c); return ['ok' => false, 'resp' => 'MAIL fail', 'qid' => '-']; }
    if (!$okf($cmd($c, "RCPT TO:<$to>"), '250')) { fclose($c); return ['ok' => false, 'resp' => 'RCPT fail', 'qid' => '-']; }
    if (!$okf($cmd($c, 'DATA'), '354')) { fclose($c); return ['ok' => false, 'resp' => 'DATA fail', 'qid' => '-']; }

    $headers = [
        "From: $fromName <$from>",
        "To: $toName <$to>",
        'Subject: =?UTF-8?B?' . base64_encode($subject) . '?=',
        'Message-ID: <' . uniqid('hermes', true) . '@cs1302a.<domain>>',
        'Date: ' . date('r'),
        'MIME-Version: 1.0',
        'Content-Type: text/plain; charset=UTF-8',
        'Content-Transfer-Encoding: 8bit',
        '',
    ];
    fwrite($c, implode("\r\n", $headers) . $body . "\r\n.\r\n");
    $resp = $rd($c);
    $cmd($c, 'QUIT');
    fclose($c);
    $qid = '-';
    if (preg_match('/([0-9A-Za-z]{8,}) Message accepted/', $resp, $m)) $qid = $m[1];
    return ['ok' => $okf($resp, '250'), 'resp' => trim($resp), 'qid' => $qid];
}

// --- bootstrap DB (needed only for --roster) ---
global $DB;
define('CLI_SCRIPT', true);
define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php');
require_once('/var/www/html/public/lib/setup.php');

$from = argv_get('from', '<staff-email>');
$fromName = argv_get('from-name', 'CS1302A Teaching Team');
$subject = argv_get('subject');
$body = argv_get('body');
$bodyFile = argv_get('body-file');
$toList = argv_get('to');
$rosterSql = argv_get('roster');
$logFile = argv_get('log', '/tmp/send_' . date('Ymd_His') . '.log');

if (!$subject) { fwrite(STDERR, "missing --subject\n"); exit(1); }
if ($bodyFile) $body = file_get_contents($bodyFile);
if (!$body) { fwrite(STDERR, "missing --body / --body-file\n"); exit(1); }

$targets = []; // [email, name]
if ($toList) {
    foreach (explode(',', $toList) as $t) {
        $t = trim($t);
        if ($t) $targets[] = [$t, ''];
    }
} elseif ($rosterSql) {
    $rows = $DB->get_records_sql($rosterSql); // must select id, firstname, lastname, email
    foreach ($rows as $r) $targets[] = [$r->email, trim($r->lastname . ' ' . $r->firstname)];
} else {
    fwrite(STDERR, "need --to or --roster\n");
    exit(1);
}

$log = fopen($logFile, 'w');
$ok = 0; $failed = [];
$i = 0;
foreach ($targets as $t) {
    list($email, $name) = $t;
    $r = smtp_send($email, $name ?: $email, $subject, $body, $from, $fromName);
    if (!$r['ok']) { usleep(1500000); $r = smtp_send($email, $name ?: $email, $subject, $body, $from, $fromName); }
    $i++;
    printf("%2d/%d %s %-40s %s\n", $i, count($targets), $r['ok'] ? 'OK ' : 'FAIL', $email, $r['qid']);
    fwrite($log, $i . "\t" . ($r['ok'] ? 'OK' : 'FAIL') . "\t$email\t" . $r['qid'] . "\n");
    if ($r['ok']) $ok++; else $failed[] = $email;
    if ($i < count($targets)) usleep(1000000); // 1s pacing
}
fclose($log);
echo "RESULT: $ok/" . count($targets) . " accepted, " . count($failed) . " failed\n";
if ($failed) {
    echo "FAILED: " . implode(', ', $failed) . "\n";
    echo "log: $logFile\n";
    exit(2);
}
echo "log: $logFile\n";
