---
name: moodle_quiz_audit
description: Audits a Moodle quiz for suspicious student behavior (fast completion, high scores, non-campus IPs) by fetching Moodle report pages via HTTP session injection. No database access required.
parameters:
  type: object
  properties:
    cmid:
      type: integer
      description: The Course Module ID of the Moodle quiz to audit.
    fast_mins:
      type: number
      description: Suspicious completion time threshold in minutes (optional). Students who finish faster than this AND score above fast_score are flagged.
    fast_score:
      type: number
      description: Suspicious score percentage threshold, default 80.0 (optional).
    moodle_userid:
      type: string
      description: Moodle user ID to load the session file for (optional). If omitted, the script auto-detects the latest session file.
    session_file:
      type: string
      description: Explicit path to a session JSON file (optional). Overrides moodle_userid.
  required:
    - cmid
---

# Skill: Moodle Quiz Audit (HTTP Session-Injection Mode)

## Description
This tool audits a Moodle quiz for suspicious student behavior by fetching the quiz overview report and access log report pages via HTTP. It authenticates using the user's Moodle session cookie (injected automatically — no password needed). It flags:

- **Fast completion + high score**: Students who finish the quiz unusually fast but still score high.
- **Non-campus IP addresses**: Students who connected from external networks (not campus Wi-Fi, CS lab, or internal hosts).

## Architecture
- **No database access** — data is fetched from Moodle's built-in report pages (HTML).
- **No Chrome/CDP** — pure HTTP via `requests` + `BeautifulSoup`.
- **Session injection** — the `local_hermesagent` PHP plugin writes the user's session cookie to `$HERMES_HOME/run/msession_<userid>.json` on every API call. The Python script reads this file and injects the cookie into a `requests.Session()`.
- **30-minute TTL** — stale session files are rejected for security.

## When to use this skill
Trigger this skill whenever the user asks you to "audit", "check", "inspect", or "analyze" a Moodle quiz, course module, or exam data for cheating or suspicious behavior.

## Prerequisites
- The user must have an active Moodle session (logged in via the Moodle chat).
- The user must have permission to view quiz reports and access logs (teacher/admin role).
- `requests` and `beautifulsoup4` must be installed (`pip3 install requests beautifulsoup4`).

## Execution Instructions
The absolute path to the core script is: `~/.hermes/skills/moodle_quiz_audit/moodle_quiz_audit.py`

**Step 1:** Construct the bash command based on the parameters extracted.
```
python3 ~/.hermes/skills/moodle_quiz_audit/moodle_quiz_audit.py --cmid {{cmid}}
```
- If `fast_mins` is provided, append: `--fast-mins {{fast_mins}}`
- If `fast_score` is provided, append: `--fast-score {{fast_score}}`
- If `moodle_userid` is known, append: `--moodle-userid {{moodle_userid}}`
- If `session_file` is known, append: `--session-file {{session_file}}`

**Step 2:** Run the constructed command in your bash terminal.

## Post-Execution Summary
After the terminal command finishes executing, read the standard output (`stdout`) returned by the script.
Synthesize the terminal output into a clear, professional, and concise summary for the user. Pay special attention to highlighting any logs marked with `[!!! SUSPICIOUS]` or `*** FLAGGED ***`.

## Troubleshooting
- **"Session file not found"**: The user needs to send a message in the Moodle chat first so the PHP plugin writes the session file.
- **"Session file is stale"**: The session file is older than 30 minutes. Ask the user to send a fresh message in the Moodle chat and retry.
- **"Session expired (redirected to login)"**: The Moodle session cookie has expired. Ask the user to log in again and retry.
- **"No attempts found"**: The quiz may have no submissions yet, or the cmid may be incorrect.
