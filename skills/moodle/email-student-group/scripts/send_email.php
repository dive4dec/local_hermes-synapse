<?php
// Send an email via the campus SMTP relay (raw ESMTP, no auth on the source pod).
// ADAPT for your deployment: SMTP_HOST / SMTP_PORT / SMTP_FROM / EHLO_HOST env vars,
// or edit the constants below. From must be a real same-domain mailbox.
// Usage: php send_email.php <to> "<subject>" [body | @/path/to/bodyfile] [from]
//   from defaults to $defaultFrom below.
// Prints the full SMTP transcript. Success = "250 2.0.0 <queueid> Message accepted for delivery".
error_reporting(E_ALL);
ini_set('display_errors', '1');

// ===== ADAPT THESE for your campus =====
$host = getenv('SMTP_HOST') ?: 'smtp.cs.cityu.edu.hk';
$port = (int)(getenv('SMTP_PORT') ?: 587);
$defaultFrom = getenv('SMTP_FROM') ?: 'chung.chan@cityu.edu.hk';
$ehloName = getenv('EHLO_HOST') ?: 'your-campus.local';
$domainForMessageId = $ehloName;
// =======================================

$args = array_slice($argv, 1);
if (count($args) < 2) {
    fwrite(STDERR, "Usage: php " . basename($argv[0]) . " <to> \"<subject>\" [body | @file] [from]\n");
    exit(2);
}
$to      = $args[0];
$subject = $args[1];
$body    = isset($args[2]) ? $args[2] : '';
$from    = isset($args[3]) ? $args[3] : $defaultFrom;

if (strncmp($body, '@', 1) === 0) {
    $path = substr($body, 1);
    if (!is_readable($path)) { fwrite(STDERR, "Cannot read body file: $path\n"); exit(2); }
    $body = file_get_contents($path);
}

$err = 0; $errstr = '';
$conn = @stream_socket_client("tcp://$host:$port", $err, $errstr, 10);
if (!$conn) { fwrite(STDERR, "CONNECT FAIL: $err $errstr\n"); exit(1); }
stream_set_timeout($conn, 15);

// Read one full SMTP reply: keep reading lines until the 4th char is a space.
function rd($c) {
    $out = '';
    while (($line = fgets($c, 1024)) !== false) {
        $out .= $line;
        if (isset($line[3]) && $line[3] === ' ') break;
    }
    return $out;
}
function cmd($c, $l) {
    fwrite($c, $l . "\r\n");
    $resp = rd($c);
    echo "> $l\n" . $resp;
    return $resp;
}
function expect($resp, $code, $what) {
    if (strpos($resp, $code) !== 0) {
        fwrite(STDERR, "FAIL at $what (expected $code, got: " . trim($resp) . ")\n");
        exit(1);
    }
}

$greet = rd($conn);
echo "$greet";
if (strpos($greet, '220') !== 0) { fwrite(STDERR, "No 220 greeting\n"); exit(1); }

expect(cmd($conn, 'EHLO ' . $ehloName), '250', 'ehlo');
expect(cmd($conn, "MAIL FROM:<$from>"), '250', 'mail from');
expect(cmd($conn, "RCPT TO:<$to>"), '250', 'rcpt to');
expect(cmd($conn, 'DATA'), '354', 'data');

// Build body with dot-stuffing: lines starting with '.' get an extra '.'.
$lines = preg_split('/\r\n|\r|\n/', $body);
foreach ($lines as &$ln) { if (strncmp($ln, '.', 1) === 0) { $ln = '.' . $ln; } }
$sentBody = implode("\r\n", $lines);

$headers = [
    'From: ' . $from,
    'To: ' . $to,
    'Subject: ' . $subject,
    'Message-ID: <' . uniqid('hermes', true) . '@' . $domainForMessageId . '>',
    'Date: ' . gmdate('D, d M Y H:i:s ') . (new DateTime())->format('P'),
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=UTF-8',
    'Content-Transfer-Encoding: 8bit',
    '',
];
fwrite($conn, implode("\r\n", $headers) . $sentBody . "\r\n.\r\n");
$resp = rd($conn);
echo "DATA\n" . $resp;
if (strpos($resp, '250') !== 0) { fwrite(STDERR, "DATA rejected\n"); exit(1); }

cmd($conn, 'QUIT');
echo "\nSENT OK — accepted by relay (check the recipient's inbox to confirm delivery).\n";
fclose($conn);
