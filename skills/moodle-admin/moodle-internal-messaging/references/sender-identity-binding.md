# Sender identity binding — how the agent's "current" Moodle user is resolved, and how to fix drift

Incident (2026-09-24): an urgent grade message to a student in cs1302a_26a was delivered
"from Chao Zhao (uid 495)" instead of the room owner <Instructor-Name> (uid 494). User correction:
"Strange, this agent should be bound to the account <Instructor-Name>." The message had already
been sent, so it was re-attributed in place. This file captures the mechanism + both recipes.

## Mechanism (moodle-bridge plugin, `$HERMES_HOME/plugins/moodle-bridge/__init__.py`)

- The plugin resolves the "current" Moodle user per session, in order:
  1. **Per-session file:** `$HERMES_HOME/run/identity/<HERMES_SESSION_KEY>.identity.json` —
     JSON `{"username": "<lti username>", "userid": "<uid>"}`. The Matrix DM session key
     looks like `agent:main:matrix:dm:!<roomid>:matrix.org`.
  2. **Fallback:** `$HERMES_HOME/.moodle_identity` (same JSON) — **last-writer-wins**.
- The ACP bridge (`/var/www/html/public/local/hermesagent/classes/bridge/acp_bridge.py`,
  `_write_identity()`) rewrites BOTH files on every prompt coming from a Moodle LTI chat,
  stamped with that chat's LTI user. Consequence: the last teacher to chat with the agent
  via the Moodle UI owns the legacy file, and any session without a per-session file
  (the Matrix DM, unless the bridge has written one for its session key) resolves to that
  teacher — silently, with no error. `run/identity/` was EMPTY in this incident, so the
  fallback governed.
- `moodle_get_my_courses` returns whichever account is currently bound — the 1-call detector.

## Who is who (course 3, cs1302a_26a — verify against DB before relying)

- **<Instructor-Name> — uid 494**, LTI username `enrol_lti3362f10548e1f10d602bdbe336bed8b4dd080fef`.
  Owner of the Matrix room "EQuiz cs1302a-26a" — the expected bound account.
- **Chao Zhao — uid 495**, LTI username `enrol_lti34461258b45ef7082df58c61d76610bd0e62b159`
  (also editingteacher on course 3).
- Both hold editingteacher; the role does NOT identify the owner. Compare against the
  room owner, not against "the teacher I remember".

## Detection (do this before ANY attribution-sensitive action — send, upload, grade entry)

```
moodle_get_my_courses
  -> user.name != owner of this room  =>  identity drift; fix before acting
```

## Fix: correct a drifted identity (verified working 2026-09-24)

```python
# 1) per-session file: $HERMES_HOME/run/identity/<HERMES_SESSION_KEY>.identity.json
# 2) legacy file:      $HERMES_HOME/.moodle_identity
# both:
'{"username": "enrol_lti3362f10548e1f10d602bdbe336bed8b4dd080fef", "userid": "494"}\n'
```
Then re-run `moodle_get_my_courses` to confirm 494 before continuing.
Caveat: the next Moodle LTI chat prompt from ANY teacher overwrites the legacy file again —
the per-session file is the durable fix for a given session; the legacy file is best-effort.
If drift recurs, the owner may want the bridge to stop writing the legacy fallback, or a
cron to pin it after each LTI chat.

## Re-attribute an already-sent internal message (verified working 2026-09-24)

The message row (`mdl_notifications`) and its popup row (`mdl_message_popup_notifications`,
which only stores `notificationid`) already exist. Fix the sender in place — the popup row
needs no change:

```php
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php'); require_once('/var/www/html/public/lib/setup.php');
global $DB, $PAGE;
$NID = <mdl_notifications.id>; $NEWFROM = <owner uid>; $USERTO = <recipient uid>;
$DB->set_field('notifications', 'useridfrom', $NEWFROM, ['id' => $NID]);
$row = $DB->get_record('notifications', ['id' => $NID]);
$cd = json_decode($row->customdata ?: '{}', true);
$pic = new user_picture((object)['id' => $NEWFROM]);
$pic->size = 1; $pic->includetoken = $USERTO;
$cd['notificationiconurl'] = $pic->get_url($PAGE)->out(false);  // ran fine with $PAGE at its CLI default
$DB->set_field('notifications', 'customdata', json_encode($cd), ['id' => $NID]);
```
Verify: `SELECT id, useridfrom, subject FROM mdl_notifications WHERE id = <NID>;`
(`timecreated` is MCP-keyword-blocked — don't name it.) The recipient sees the corrected
from-name the next time they open the message; the popup badge itself carries no from-name.
