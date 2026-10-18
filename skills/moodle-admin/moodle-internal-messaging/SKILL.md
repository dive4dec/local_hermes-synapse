---
name: moodle-internal-messaging
description: "Deliver a message to a user via Moodle's INTERNAL messaging (inbox + popup notification), not email. Verified on <moodle-host> (Moodle 5.x): the message store is mdl_notifications (NOT mdl_message), popups go to mdl_message_popup_notifications, and the send is done by building a \\core\\message\\message event and calling message_send(). Use when asked to 'message/notify the student', 'send via Moodle inbox', when email is unavailable or the user prefers a popup, or to send a grade/integrity notification without email."
---

# Moodle Internal Messaging (inbox + popup), Moodle 5.x / <moodle-host>

Deliver a message into a user's Moodle inbox and trigger a popup notification, from a CLI PHP script. This is the reliable non-email channel on this pod: **email cannot be dispatched from local `mail()`/`sendmail`** (dead 127.0.0.1) — if the user actually wants real email, use the open campus relay via `pod-smtp-email-send` (see below); for anything "message them / notify them" or when email is off the table, use internal messaging.

## Triggers

- "message / notify / send the student a note", "deliver via Moodle inbox"
- "email them" when the real SMTP relay is unavailable or the user declines email
- A serious grade / integrity notification where the owner wants Moodle delivery (popup on their next login)
- "Send it not via email, via internal messaging"

## Send mechanism (verified working 2026-09-24)

Build a `\core\message\message` event object and call `message_send()`. This works headless (no `$PAGE` needed, though a `$PAGE` global is harmless):

```php
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php');
require_once('/var/www/html/public/lib/setup.php');
require_once('/var/www/html/public/message/lib.php');
global $DB, $PAGE;

$USERFROM = <sender uid>;   // account whose NAME shows in the "from" header (see pitfall 1)
$USERTO   = <recipient uid>;
$COURSEID = 3;              // 1 also accepted; the course is only cosmetic here

$subject = 'URGENT - ...';
$html = "<p>Dear ...</p>\n<p>...</p>";
$text = html_to_text($html);

$ev = new \core\message\message();
$ev->courseid            = $COURSEID;
$ev->component           = 'moodle';
$ev->name                = 'instantmessage';
$ev->userfrom            = $USERFROM;
$ev->userto              = $USERTO;
$ev->subject             = $subject;
$ev->fullmessagehtml     = $html;
$ev->fullmessage         = $text;
$ev->fullmessageformat   = FORMAT_HTML;
$ev->smallmessage        = $subject;
$ev->timecreated         = time();
$ev->notification        = 1;               // 1 => also create a popup notification
$ev->customdata          = [
    'placeholders' => ['contextname' => 'CS1302A Introduction to Computer Programming'],
];
$rid = message_send($ev);                   // returns the mdl_notifications.id (int)
echo "sent notification id=$rid\n";
```

Notes:
- `\core\message\message` is the event class (namespace `\core\message`, class `message`). **`core_message::async()` does NOT exist on this build** (class not found) — do not use it.
- `message_post_message()` in `message/lib.php` also works but expects a fully loaded `$userto` user object (`->lang`, `->id`) and a `$PAGE`; the manual event above is simpler and runs headless.
- `notification = 1` is what creates the popup (in addition to the inbox row).
- **Do NOT** use `user_picture->get_url($PAGE)` for `customdata['notificationiconurl']` in CLI — with a null `$PAGE` it can misfire. The message sends fine without the icon key; drop it (as above).

## Where the data lands (verified via `SHOW COLUMNS`)

- **`mdl_notifications`** is the message store — one row per message, `message_send()` returns this row's `id`. Columns: `id, useridfrom, useridto, subject, fullmessage, fullmessageformat, fullmessagehtml, smallmessage, component, eventtype, contexturl, contexturlname, timeread, timecreated, customdata`. `timeread = NULL` = **unread**.
- **`mdl_message`** exists with similar columns but **stays EMPTY** in this fork — do not read/write it for verification; the store is `mdl_notifications`.
- **`mdl_message_popup_notifications`** (columns: `id, notificationid`) — one row with `notificationid = mdl_notifications.id` is created automatically; this is what makes the popup appear on the recipient's next login.

## Verification (read-only, via the `moodle_db` MCP tool)

```sql
-- the delivered message (avoid `timecreated` in the text: MCP keyword filter rejects "CREATE")
SELECT id, useridfrom, useridto, subject, component, eventtype, timeread,
       LEFT(fullmessagehtml, 200) AS body
FROM mdl_notifications WHERE id = <returned id>;
-- the popup trigger
SELECT * FROM mdl_message_popup_notifications WHERE notificationid = <returned id>;
```
Expected: one `mdl_notifications` row with `timeread IS NULL` and the right `useridfrom`/`useridto`/`subject`; one popup row referencing it. `moosh -n cache-clear` is not required for messaging (no cache), but the recipient only sees it when they next load Moodle.

## Pitfalls

1. **Verify the bound account BEFORE every send — the agent's "current" Moodle user is NOT fixed.** The moodle-bridge plugin resolves it from `$HERMES_HOME/run/identity/<HERMES_SESSION_KEY>.identity.json` (per session), falling back to `$HERMES_HOME/.moodle_identity`, which is **last-writer-wins**: any teacher who chats with the agent through a Moodle LTI chat overwrites it, so a session with no per-session file (e.g. the Matrix DM) silently acts as the last LTI teacher. 2026-09-24 incident: a serious grade message went out "from Chao Zhao (495)" when the room owner is <Instructor-Name> (494) — the student saw a from-name that contradicted the signature. Always: (a) call `moodle_get_my_courses` and confirm the returned name is the owner of this room before any attribution-sensitive action; (b) if it's wrong, write the per-session + legacy identity files and re-verify (recipe in `references/sender-identity-binding.md`); (c) set `userfrom` to the owner's uid; (d) if a message already went out as the wrong user, re-attribute it in place (`mdl_notifications.useridfrom` + regenerate `customdata.notificationiconurl` — same reference file).
2. **`mdl_message` ≠ the store.** Verifying against `mdl_message` returns 0 rows and looks like the send failed. The real row is in `mdl_notifications` (and the popup in `mdl_message_popup_notifications`).
3. **No `core_message::async()`** on this build — "Class core_message not found". Use the manual `\core\message\message` event + `message_send()`.
4. **Email processor being enabled doesn't mean email delivers.** With the local transport dead, the email processor is a silent no-op while the inbox + popup rows still land. If the owner wants guaranteed delivery, either use internal messaging (this skill) or the campus relay (`pod-smtp-email-send`).
5. **MCP verification gotcha:** `timecreated` is rejected by the keyword filter ("CREATE") — drop it from the SELECT/ORDER BY (use `ORDER BY id` or `eventtype`), per `moodle-mcp-db-query` pitfall 1.

## Content: serious grade / integrity notifications

The most common use is a weighty note to a student about a grade consequence (e.g. a zero for absence). The owner has strong, specific preferences about tone and claims — read `references/grade-integrity-notification-tone.md` BEFORE drafting, and verify every factual claim against the DB first.

## Related skills

- `pod-smtp-email-send` — the only working REAL email path on this pod (open campus relay `<smtp-host>:587`, raw ESMTP, no auth). If the user wants an actual email, use that — do not conclude "no mail transport" from local `sendmail`/`127.0.0.1:25` being dead.
- `moodle-mcp-db-query` — read-only DB verification, keyword-filter gotchas.
- `moodle-gradebook` → `references/quiz-manual-grade-override.md` — the per-question manual zeroing that these notifications typically follow up.
