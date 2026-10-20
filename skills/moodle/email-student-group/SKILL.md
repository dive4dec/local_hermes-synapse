---
name: email-student-group
description: Email one or many students (e.g. a whole Moodle group / lab section) from the Moodle box. Resolves the group roster's email addresses from the DB, drafts the message, requires explicit user confirmation, then sends per-recipient over raw ESMTP (no PHPMailer). Use when asked to "email the students", "email group T02", "send a quiz reminder to everyone who hasn't finished", or "email students who failed X".
---

# Email a student / group of students

Send genuine outbound email (lands in the recipient's inbox — NOT a Moodle
notification). Two halves: **resolve the recipient list from the DB**, then
**send over raw ESMTP**.

## ⚠️ Step 0 — verify YOUR mail path first (deployment-specific!)
The send method below (raw ESMTP over a campus relay) is what works on the
source deployment, but it is NOT universal. Before first use, determine what
your build actually supports, in this order:

1. `ls <moodle_root>/vendor/` — if present, PHPMailer may work (the normal path).
2. `ls <moodle_root>/lib/classes/user_mailing.php <moodle_root>/lib/classes/smtp.php <moodle_root>/lib/classes/mail.php` — if all present, Moodle-native mail (`core_user_mailing::send_mail`) may work.
3. Check configured relay: `SELECT name, value FROM mdl_config WHERE name LIKE 'smtp%'` (columns are only `id, name, value`).
4. If neither exists (as on the source pod), the **raw ESMTP script is the only path** — find the campus relay host/port (ask the instructor or check `smtphosts`), and test with a send to the instructor's own address.

Record the verified facts (host, port, auth required?, acceptable From address)
in this skill so the next session doesn't re-derive them.

## Resolving the recipient list

### A Moodle group (e.g. "T02", "group03")
```sql
SELECT u.id, u.firstname, u.lastname, u.email, u.emailstop
FROM {groups} g
JOIN {groups_members} gm ON gm.groupid = g.id
JOIN {user} u ON u.id = gm.userid
WHERE g.courseid = <courseid> AND g.name = '<groupname>'
ORDER BY u.lastname, u.firstname
```
- Groups are per-course (`g.courseid`); name them exactly (list `SELECT id,name FROM mdl_groups WHERE courseid=<cid>` to see the convention).
- `emailstop = 1` → user opted out of mail; **skip them and say so**.
- **Cross-check the count** against a second method (e.g. `SELECT COUNT(*) FROM mdl_groups_members WHERE groupid=<gid>`) before any bulk send. Never trust a single query for a roster you are about to blast.

### All enrolled students in a course
Walk enrolments: `mdl_enrol` rows for the course → `mdl_user_enrolments` (status 0) per enrol → `mdl_user`. (In some builds `$DB->get_records_sql` is unreliable — if you have one, prefer it; otherwise loop `get_records` per enrol, which is fine for a few hundred.)

### Quiz-conditioned roster
Join quiz attempts to users, e.g. "submitted and score < 50%" or "enrolled but never submitted" — see the `moodle-equiz-student-status` / `quiz-ai-misuse-audit` skills if present.

## Draft → CONFIRM → send (MANDATORY workflow)
1. Draft the email: From, To (show the **full roster with names + emails** for a group, or count + sample), Subject, body.
2. **Present it to the user and wait for explicit confirmation.** Group sends are irreversible; a typo'd roster or body cannot be recalled. Never skip this for bulk sends, even if the user seemed to pre-approve the content.
3. Send: **one private message per recipient** (individual `RCPT TO`). Do NOT BCC — recipients must not see each other, and Reply-To must work.
4. Pace ~1s between sends (`usleep(1_000_000)`); auto-retry once per recipient after ~1.5s on any non-250.
5. Log every result to `/tmp/<group>_send_log.txt` as `N<TAB>status<TAB>email<TAB>queueid`. Terminal timeout for N recipients: ~`N*2 + 60` s.
6. Report: `X sent, Y failed` + queue IDs + the caveat below.

## Sending — raw ESMTP (verified on source pod: open relay, no auth)

Script: `scripts/send_email.php` — `php send_email.php <to> "<subject>" [body | @/path/bodyfile] [from]`.
It prints the full SMTP transcript; success = `250 2.0.0 <queueid> Message accepted for delivery` after DATA.

Protocol (for ad-hoc / batch variants):
1. `stream_socket_client("tcp://<relay>:<port>", $err, $errstr, 10)`; `stream_set_timeout($conn, 15)`.
2. Read replies by looping `fgets` until a line whose **4th character is a space** (`250-…` = more lines, `250 …` = end).
3. Greeting (expect `220`) → `EHLO <hostname>` → `MAIL FROM:<from>` (250) → `RCPT TO:<to>` (250) → `DATA` (354) → headers + dot-stuffed body + `\r\n.\r\n` (250 2.0.0) → `QUIT`.
4. Headers: `From`, `To`, `Subject` (use `=?UTF-8?B?…?=` base64 form if non-ASCII), `Message-ID` (uniqid), `Date` (RFC 2822), `MIME-Version: 1.0`, `Content-Type: text/plain; charset=UTF-8`.
5. **Dot-stuffing:** any body line starting with `.` gets an extra `.` prefixed.

## Pitfalls (learned the hard way)
- **Preview the EXACT bytes of subject AND body before any batch send** (e.g. `for i in range(len(s)): print chr/ord` or `od`). Two real incidents: (1) a single-quoted PHP string containing `\u{2014}` sends the LITERAL text `\u{2014}` (PHP 8.3 only interprets `\u{...}` in double-quoted strings) — use `"\u{2014}"` or raw UTF-8 `"\xE2\x80\x94"`; (2) `"week of 21$EN27 September"` is parsed as the variable `$EN27` (PHP variable names eat following digits/letters) → the en dash silently vanished from three date ranges in a sent batch. Build dashed dates by concatenation: `"...21".$EN."27 September..."` or `sprintf`.
- No `sockets` ext → only `stream_socket_client`/`fsockopen` (the code above already uses these).
- Relay advertised no STARTTLS/AUTH → do NOT try to authenticate or TLS unless your relay actually advertises it (`EHLO` output tells you).
- **Keep From within the campus domain** (e.g. the admin mailbox). Arbitrary/external From addresses risk rejection or spam-flagging.
- **`250 Message accepted for delivery` = queued by the relay, NOT delivered to inbox.** Same-domain plain text usually lands in seconds; the recipient's spam filter is the one invisible variable. Tell the user the inbox check is the final confirmation; the queue ID helps trace a missing mail.
- A `550` on `RCPT TO` = unknown/bad address — exclude and report, don't retry.
- Moodle's own mail subsystem is STRIPPED on the source build (`user_mailing.php`, `smtp.php`, `mail.php` missing, no `vendor/`, local sendmail dead) — if that matches your build, do not waste time on Moodle-native sending.
- PHP bootstrap note: on the source pod `define('CLI_SCRIPT', true)` works in scripts; if your build fatals, try `TRUE`/`1`.

## Batch sender (pseudocode)
```php
foreach ($roster as $u) {
    if ($u->emailstop) { log('skip emailstop', $u); continue; }
    $attempts = 0;
    while ($attempts < 2) {
        $resp = sendOne($from, $u->email, $subject, $body); // returns transcript
        if (preg_match('/^250 2\.0\.0 ([0-9A-Za-z]+)/m', $resp, $m)) { log('ok', $u, $m[1]); break; }
        log('retry', $u, $resp); usleep(1500000); $attempts++;
    }
    usleep(1000000);
}
```
