---
name: pod-smtp-email-send
description: "Send outbound email from the Moodle pod (<moodle-host>) via the OPEN campus SMTP relay <smtp-host>:587 using raw ESMTP over stream_socket_client — no auth required. This is the ONLY working email path on this build: there is no PHPMailer (no vendor/) and the core Moodle mail classes (user_mailing/smtp/mail) are stripped. Use whenever the user asks to email a student/person, send a quiz reminder, or 'test SMTP / send an email'. Supersedes the (protected, PHPMailer-based) moodle-smtp-email skill for this build."
---

# Send Outbound Email from the Moodle Pod

The **only verified working** email path on this pod: drive the **open campus relay** directly with **raw ESMTP over `stream_socket_client`** — no credentials.

## Why the usual options do NOT exist here (verified 2026-09-15)

- No `vendor/` directory → **PHPMailer is NOT available**.
- Core mail classes are **stripped from this build**: `lib/classes/user_mailing.php`, `lib/classes/smtp.php`, `lib/classes/mail.php` are all missing → `core_user_mailing::send_mail`, `\core\smtp`, `moodle_send_mail` cannot be called.
- PHP `mail()` / `/usr/sbin/sendmail` is dead: it targets `127.0.0.1:25` → Connection refused. No Postfix/ssmtp/msmtp/swaks in the pod.
- The old `moodle-smtp-email` skill (manually authored, **protected** — do not try to edit it) recommends PHPMailer "within the Moodle framework". That is **wrong for this build**; this skill is the corrected, verified path. Flag the overlap so a curator can consolidate.

## Triggers

- "email <student/person> a message", "send them a test email", "can you email me"
- "send a reminder to students who haven't finished <quiz>"
- "test SMTP", "check mail configuration", "verify email delivery from Moodle"

## Verified relay facts (2026-09-15)

- Server: `<smtp-host>:587` → announces `mail.cs.<domain>` (Sendmail 8.15.1).
- **No AUTH, no STARTTLS advertised** — plain ESMTP: `EHLO` → `MAIL FROM` → `RCPT TO` → `DATA` → `QUIT`. User confirmed the relay needs no credentials.
- Pod egresses as `<pod-ip>` (`<moodle-host>`); the EHLO banner notes "(may be forged)" — the relay trusts campus source IPs.
- `mdl_config` rows `smtpuser`/`smtppass` are **empty**; `smtphosts=<smtp-host>:587`, `smtpauthtype=LOGIN` are vestigial — credentials are NOT needed.
- No PHP `sockets` extension, but `stream_socket_client` works.
- **Sender identity:** use `<staff-email>` (Admin User, uid 2) as the From address — a real same-domain campus mailbox. "<Instructor-Name>" the student (<coursecode>, uid 3) = `<student-email>`.
- Success = `250 2.0.0 <queueid> Message accepted for delivery` on the DATA end.

## Quick send (working)

```
php <skill>/scripts/send_email.php <to> "<subject>" [body | @/path/to/bodyfile] [from]
```
`from` defaults to `<staff-email>`. The script prints the full SMTP transcript; treat the `250 2.0.0 ... Message accepted for delivery` after DATA as success. Example:

```
php .../scripts/send_email.php <student-email> "hi" "hi"
```

## How the send works (for ad-hoc variants)

1. `stream_socket_client("tcp://<smtp-host>:587", $err, $errstr, 10)`; `stream_set_timeout($conn, 15)`.
2. Read a reply by looping `fgets` until a line whose **4th character is a space** (`250-…` = more lines, `250 …` = end of reply).
3. Send: greeting → `EHLO <coursecode>.cityu.local` → `MAIL FROM:<from>` (expect `250`) → `RCPT TO:<to>` (expect `250`) → `DATA` (expect `354`) → headers + body + `\r\n.\r\n` (expect `250 2.0.0`) → `QUIT`.
4. Headers: `From`, `To`, `Subject`, `Message-ID` (uniqid), `Date: date('r')`, `MIME-Version: 1.0`, `Content-Type: text/plain; charset=UTF-8`.
5. **Dot-stuffing:** any body line starting with `.` must be prefixed with an extra `.` before sending.

## Student-facing quiz email tone (user-set, 2026-10-05)
For quiz non-submission / missed-deadline emails to students: **firm — no sympathy for technical issues and NO mitigation offered regardless of reason** (students are responsible for submitting before the deadline). Content: (a) state plainly what is missing + the exact close time, (b) no submission will be accepted after the closing time, (c) emphasize the E-Quiz is open for a one-week window → important to attempt and submit early. The user explicitly rejected a softer draft ("If you encountered any issue … please let me know and I will look into it") on these grounds — don't re-offer it.

**Learning-concern / suspected-AI-misuse emails (different register, user-set 2026-10-06):** NOT firm-no-mitigation — supportive, zero accusation, no grade changes by email. Structure: (a) acknowledge the student's reported technical issue and briefly state in plain language what the system records actually show (no log details, no IDs); (b) state the observed pattern (high homework vs low in-class, incl. not being able to redo questions they "already solved"); (c) frame as a learning risk, not a judgment — AI is allowed but answers must show understanding; AI bug-free solutions skip the debugging/learning process; (d) the principle the user wants stated: **more help does not mean better learning — help can backfire**; use AI as a teacher, not a writer (explain why, quiz, point at bugs instead of rewriting); (e) invite to talk — Monday open hour or after the Wednesday 9am-12pm lecture (<coursecode>: lecture Wed 9am-12pm, open hour Monday).

## Pitfalls

- **Don't burn time on Moodle-native sending in this build** — no PHPMailer (no vendor/), no core mail classes, dead local sendmail. The old skill's PHPMailer recipe is dead on arrival here.
- **"Accepted for delivery" ≠ in inbox** — it means the relay queued it. Same-domain plain text usually lands in seconds, but the recipient's spam/junk filter is the one variable not visible from here. Tell the user that checking the inbox is the final confirmation.
- **Keep From within `<domain>`** (e.g. the admin mailbox) — arbitrary/external From addresses risk the relay rejecting or spam-flagging the message.
- **Batch sends** (quiz reminders): send per recipient with a small delay; the relay may rate-limit. Get addresses from `mdl_user.email` and confirm each `RCPT TO` returns `250 2.1.5 ... Recipient ok` (a `550` = unknown address).
- **Lint a freshly-generated batch script BEFORE running it.** When a PHP sender is written via an editor/patch tool, escape/tab/quote characters can get mangled (a log-writer line losing its closing quote or getting raw tabs injected into the string is a real, recurring incident). A parse error makes `php` exit silently with code 255 — no output, no SMTP connection, no log file. Always `php -l <file>` and re-read the exact bytes of any line containing `\t`, quotes, or escapes before executing.
- **Answering "have you sent the email?":** the batch script opens its log file at start, before any SMTP I/O — so the log file's ABSENCE proves the script never ran and nothing was sent (absence is proof of no-send; only the presence of the log + a 250 qid is proof of sent). Never claim a send based on intent; verify log file + queue IDs first, and re-run only after `php -l` is clean.
- **Config check** (read-only, via MCP): `SELECT name, value FROM mdl_config WHERE name LIKE 'smtp%'` → `smtphosts`, `smtpauthtype`, `smtpuser`, `smtppass`, `smtpsecure`. `mdl_config` has only `id, name, value` columns.

## Files

- `scripts/send_email.php` — working single-send sender. argv: `<to> <subject> [body | @bodyfile] [from]`.
- `templates/batch_send.php` — known-good BATCH sender (proven in production 2026-09-28, 13/13). Copy it, edit the `$recipients`/`$subject`/`bodyFor()` sections, `php -l` it, then run. Do not hand-type batch senders from scratch.
