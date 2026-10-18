<?php
// Batch ESMTP sender for the pod relay (<smtp-host>:587, no auth).
// KNOWN-GOOD — proven in production (13/13 delivered, 2026-09-28).
//
// SETUP: edit $recipients, $subject, bodyFor(), $logf.
// BEFORE RUNNING: ALWAYS `php -l batch_send.php` — mangled escapes/tabs in
// a log-writer line cause a SILENT exit 255 (no SMTP I/O, no log file).
// The log file is opened BEFORE any socket I/O: its absence proves the
// script never ran (answer to "did you send it?": no).

$HOST='<smtp-host>'; $PORT=587;
$from='<staff-email>'; $fromName='<Instructor-Name>';
$subject='SUBJECT HERE';
$logf='/tmp/batch_send_log.txt';

// [uid, first_name, lab_section, email] — uid is for your own audit trail.
$recipients = [
  [123, 'First', 'T02', '<student-email>'],
];

function bodyFor($first, $lab) {
  return "Dear $first,\n\n"
   . "Body line one.\n"
   . "Body line two ($lab section).\n\n"
   . "Regards,\n"
   . "<Instructor-Name>\n";
}

function readReply($c) {
  $o='';
  while (($l=fgets($c,1024))!==false) {
    $o.=$l;
    if (isset($l[3]) && $l[3]===' ') break;
  }
  return $o;
}
function cmd($c,$l){ fwrite($c,$l."\r\n"); return readReply($c); }
function ok($r,$p){ return strpos($r,$p)===0; }

$subjectB64 = '=?UTF-8?B?'.base64_encode($subject).'?=';
$lf = fopen($logf, 'w');
fwrite($lf, "# batch send - " . date('Y-m-d H:i:s') . " UTC\n");
fwrite($lf, "subject: $subject\n\n");
fflush($lf);

$sent=0; $failed=0;
foreach ($recipients as $i => $r) {
  [$uid,$first,$lab,$to] = $r;
  $body = bodyFor($first,$lab);
  // dot-stuffing
  $stuffed = preg_replace('/^\./m', '..', $body);
  $toName = 'Student';
  $headers = [
    "From: $fromName <$from>",
    "To: $toName <$to>",
    "Subject: $subjectB64",
    'Message-ID: <'.uniqid('<coursecode>',true).'@<coursecode>.<domain>>',
    'Date: '.date('r'),
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=UTF-8',
    'Content-Transfer-Encoding: 8bit',
    '',
  ];
  $payload = implode("\r\n",$headers) . $stuffed . "\r\n.\r\n";

  $status='FAIL'; $qid=''; $tryn=1;
  for ($attempts=0; $attempts<2; $attempts++) {
    try {
      $c = @stream_socket_client("tcp://$HOST:$PORT", $e, $es, 10);
      if (!$c) { throw new Exception("CONNECT FAIL: $es"); }
      stream_set_timeout($c,15);
      readReply($c);
      if (!ok(cmd($c,'EHLO <coursecode>.cityu.local'),'250')) throw new Exception('EHLO fail');
      if (!ok(cmd($c,"MAIL FROM:<$from>"),'250'))   throw new Exception('MAIL fail');
      if (!ok(cmd($c,"RCPT TO:<$to>"),'250'))       throw new Exception('RCPT fail (likely 550/unknown addr)');
      if (!ok(cmd($c,'DATA'),'354'))                 throw new Exception('DATA fail');
      fwrite($c,$payload);
      $resp=readReply($c);
      cmd($c,'QUIT');
      fclose($c);
      if (preg_match('/^250 2\.0\.0 ([0-9A-Za-z]+)/m', $resp, $m)) {
        $status='OK'; $qid=$m[1]; $tryn=$attempts+1; break;
      }
      throw new Exception('NON-250: '.trim(substr($resp,0,200)));
    } catch (Exception $ex) {
      if (isset($c)) { @fclose($c); }
      if ($attempts==0) { usleep(1500000); }
      else { $status='FAIL'; }
    }
  }
  if ($status==='OK') $sent++; else $failed++;
  // NOTE: this line is the one that got mangled in 2026-09-28 — re-lint after edits.
  fwrite($lf, ($i+1)."\t".$status."\t".$first."\t".$to."\t".$qid."\ttry".$tryn."\n");
  fflush($lf);
  fwrite(STDOUT, ($i+1).". $first ($to) -> $status ".($qid? "qid=$qid":"")."\n");
  usleep(1000000);
}
fclose($lf);
echo "\n$sent sent, $failed failed. Log: $logf\n";
