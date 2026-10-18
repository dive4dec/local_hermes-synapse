---
name: campus-smtp-email
description: Send real emails from this Moodle box to students/users. Use when the user asks to email someone or a group (not a Moodle message/notification). Moodle's own mail subsystem is STRIPPED, so mail MUST be driven by talking to the open campus SMTP relay directly over a raw socket.
---

# Campus SMTP email send

Send genuine outbound email from the phpfpm pod to students or other users.

## When to use
- User asks to "email" a person or a group, or wants a message in their inbox.
- Do NOT use this for Moodle-internal notifications/quiz emails — those go through Moodle's (broken) mail path and won't work here.

## Critical facts (verified — do not re-derive)
- **Moodle's mail classes are STRIPPED from this build.** `lib/classes/user_mailing.php`, `smtp.php`, `mail.php` are all MISSING; no PHPMailer/Symfony. `core_user_mailing::send_mail()` and `moodle_send_mail()` will fatal. **Never rely on Moodle to send mail.**
- **Open campus relay:** `<smtp-host>:587` (Sendmail 8.15.1). **No AUTH, no STARTTLS advertised.** Plain TCP → EHLO → MAIL → RCPT → DATA.
- **PHP has NO `sockets` extension**, but `stream_socket_client` / `fsockopen` work fine.
- **Default sender:** `<staff-email>` (Admin User, uid 2).
- **"250 Message accepted for delivery" = queued, NOT proven delivered.** Same-domain plain-text usually lands in seconds; only the recipient's inbox confirms.

## Workflow
1. **Resolve the recipient(s).**
   - Single person: `SELECT id,firstname,lastname,email FROM mdl_user WHERE email='...'` (or by id/name).
   - A Moodle group (e.g. "T02" in <coursecode>):
     ```sql
     SELECT u.id,u.firstname,u.lastname,u.email
     FROM mdl_groups g
     JOIN mdl_groups_members gm ON gm.groupid=g.id
     JOIN mdl_user u ON u.id=gm.userid
     WHERE g.courseid=<courseid> AND g.name='<Group>'
     ORDER BY u.lastname,u.firstname
     ```
   - Check `emailstop=1` for anyone who opted out of mail.
2. **Draft the message and present From / To (count + roster if group) / Subject / body to the user and WAIT for explicit "confirm" before sending.** (Group blasts are irreversible.)
3. **Send** (single or batch script below).
4. **Report** per-recipient `250` + queue IDs, save a log, and state the queued-vs-delivered caveat.

## Single send — verified PHP (write to /tmp and run)
```php
<?php
$HOST='<smtp-host>'; $PORT=587;
$from='<staff-email>'; $fromName='<Instructor-Name>';
$to='<student-email>'; $toName='<Instructor-Name>';
$subject='Subject line'; $body="line1\n\nline2";

$c = @stream_socket_client("tcp://$HOST:$PORT", $e, $es, 10);
if(!$c){ fwrite(STDERR,"CONNECT FAIL: $es\n"); exit(1); }
stream_set_timeout($c,15);
$rd=function($c){ $o=''; while(($l=fgets($c,1024))!==false){ $o.=$l; if(isset($l[3])&&$l[3]===' ')break; } return $o; };
$cmd=function($c,$l)use($rd){ fwrite($c,$l."\r\n"); return $rd($c); };
$ok=function($r,$p){ return strpos($r,$p)===0; };

$rd($c);
if(!$ok($cmd($c,'EHLO <coursecode>.cityu.local'),'250')) exit("EHLO fail\n");
if(!$ok($cmd($c,"MAIL FROM:<$from>"),'250'))  exit("MAIL fail\n");
if(!$ok($cmd($c,"RCPT TO:<$to>"),'250'))       exit("RCPT fail\n");
if(!$ok($cmd($c,'DATA'),'354'))                 exit("DATA fail\n");
$headers=[
  "From: $fromName <$from>",
  "To: $toName <$to>",
  'Subject: =?UTF-8?B?'.base64_encode($subject).'?=',   // base64-safe for non-ASCII
  'Message-ID: <'.uniqid('hermes',true).'@<coursecode>.<domain>>',
  'Date: '.date('r'),
  'MIME-Version: 1.0',
  'Content-Type: text/plain; charset=UTF-8',
  'Content-Transfer-Encoding: 8bit',
  '',
];
fwrite($c, implode("\r\n",$headers).$body."\r\n.\r\n");
$resp=$rd($c);
$cmd($c,'QUIT'); fclose($c);
echo $ok($resp,'250') ? "SENT OK\n$resp" : "FAILED\n$resp";
```
Run: `cd <datadir>/.hermes && timeout 25 php -d display_errors=1 /tmp/send.php`

## Batch send (group)
- **One private message per recipient** (set each `RCPT TO` individually). Do NOT use a BCC list — recipients must not see each other, and Reply-To must work.
- **Pace ~1s between sends** (`usleep(1000000)`), and **auto-retry once** per recipient after 1.5s on any non-250.
- Log every result to a file (e.g. `/tmp/<group>_send_log.txt`): `N<TAB>status<TAB>email<TAB>queueid`.
- For N recipients give the terminal a `timeout` of ~`N*2 + 60` seconds.
- The send function above can be reused; loop the roster, call it per user, parse the queue ID with `/([0-9A-Za-z]{8,}) Message accepted/`.

## Pitfalls
- No `sockets` ext → only `stream_socket_client`/`fsockopen` (the code above already uses these).
- Server announces no STARTTLS/AUTH → do NOT try to encrypt or authenticate; just talk plain SMTP.
- Non-ASCII in the subject → use the `=?UTF-8?B?...?=` header form (shown above); body is plain UTF-8 text/plain.
- "accepted for delivery" is not proof of inbox delivery; say so. To confirm, ask the recipient or resend the specific one (queue ID helps).
- For bulk/group sends, ALWAYS get explicit user confirmation on From/To/Subject/body first.

## Verification
- Per recipient: `250 2.0.0 <queueid> Message accepted for delivery`.
- Final line: `<N> sent, 0 failed`. Keep the log file for tracing/resending.
