---
name: moodle_quiz_audit
description: "Audits a Moodle quiz for suspicious student behavior (fast completion, high scores, non-campus IPs) by fetching Moodle report pages via HTTP session injection. No database access required."
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
      description: Moodle user ID of the requesting user (required). The agent must obtain this from the chat context — do NOT let the user type an arbitrary userid.
  required:
    - cmid
    - moodle_userid
---

# Skill: Moodle Quiz Audit (HTTP Session-Injection Mode)

## Description
This tool audits a Moodle quiz for suspicious student behavior by fetching the quiz overview report and access log report pages via HTTP. It authenticates using the user's Moodle session cookie (injected automatically — no password needed). It flags:

- **Fast completion + high score**: Students who finish the quiz unusually fast but still score high.
- **Non-campus IP addresses**: Students who connected from external networks.

## Architecture
- **No database access** — data is fetched from Moodle's built-in report pages (HTML).
- **No Chrome/CDP** — pure HTTP via `requests` + `BeautifulSoup`.
- **Session injection** — the `local_hermesagent` PHP plugin writes the user's session cookie to `$HERMES_HOME/run/msession_<userid>.json` on every API call. The Python script reads this file and injects the cookie into a `requests.Session()`.
- **30-minute TTL** — stale session files are rejected for security.
- **Per-request login guard** — if the session expires mid-audit, the tool detects the redirect to the login page and reports an error instead of silently parsing a login form.

## When to use this skill
Trigger this skill whenever the user asks you to "audit", "check", "inspect", or "analyze" a Moodle quiz, course module, or exam data for cheating or suspicious behavior.

## Prerequisites

### Python dependencies
Run the dependency installer once (uses the Hermes venv, not system Python):
```bash
sh $HERMES_HOME/skills/moodle_quiz_audit/install_deps.sh
```

### Campus IP ranges (MOODLE_AUDIT_CAMPUS_IPS)
The skill classifies IP addresses as campus vs. external using the `MOODLE_AUDIT_CAMPUS_IPS` environment variable. This should be set in the Hermes `.env` file (editable from the plugin Settings page → `.env` editor).

Format: comma-separated CIDR notation, e.g.:
```
MOODLE_AUDIT_CAMPUS_IPS=10.0.0.0/8,144.214.0.0/16,172.16.0.0/12
```

**If `MOODLE_AUDIT_CAMPUS_IPS` is not set**, the skill falls back to standard private ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16). This may not match your campus — external IPs will be over-reported.

**If the env var is not set and the user asks about IP auditing**, ask the user:
> "I need your campus IP ranges to classify student connections. What CIDR ranges
> should be considered 'campus'? (e.g., 10.0.0.0/8 for internal hosts, 144.214.0.0/16
> for VPN, etc.) I'll save them to the Hermes .env file."

Then add the user's answer to `~/.hermes/.env`:
```bash
echo 'MOODLE_AUDIT_CAMPUS_IPS=<user-provided-cidrs>' >> ~/.hermes/.env
```
The bridge loads `.env` on next restart, so ask the user to restart the bridge from the Settings page (or do it via `hermes-bridge-control.sh restart`).

### TLS verification
TLS verification is **on by default**. If your Moodle uses a self-signed certificate and the skill fails with an SSL error, set in `.env`:
```
MOODLE_AUDIT_INSECURE=1
```

## Execution Instructions
The absolute path to the core script is: `$HERMES_HOME/skills/moodle_quiz_audit/moodle_quiz_audit.py`

**Step 1:** Construct the bash command based on the parameters extracted. The `--moodle-userid` is **required** — obtain it from the chat context (the user's Moodle ID). Never let the user supply an arbitrary userid.
```
$HERMES_HOME/venv/bin/python3 $HERMES_HOME/skills/moodle_quiz_audit/moodle_quiz_audit.py --cmid {{cmid}} --moodle-userid {{moodle_userid}}
```
- If `fast_mins` is provided, append: `--fast-mins {{fast_mins}}`
- If `fast_score` is provided, append: `--fast-score {{fast_score}}`

**Step 2:** Run the constructed command in your bash terminal.

## Post-Execution Summary
After the terminal command finishes executing, read the standard output (`stdout`) returned by the script.
Synthesize the terminal output into a clear, professional, and concise summary for the user. Pay special attention to highlighting any logs marked with `[!!! SUSPICIOUS]` or `*** FLAGGED ***`.

If the output includes `[WARN] No IP data collected — IP audit incomplete`, warn the user that the "no off-campus IPs" result is **not reliable** and the log report may need to be checked manually.

## Troubleshooting
- **"Session file not found"**: The user needs to send a message in the Moodle chat first so the PHP plugin writes the session file.
- **"Session file is stale"**: The session file is older than 30 minutes. Ask the user to send a fresh message in the Moodle chat and retry.
- **"Session expired (redirected to login)"**: The Moodle session cookie has expired. Ask the user to log in again and retry.
- **"Session expired mid-audit"**: The cookie expired while the audit was running. Re-open the Moodle chat to refresh the session, then retry.
- **"No attempts found"**: The quiz may have no submissions yet, or the cmid may be incorrect.
- **SSL error / certificate verification failed**: Set `MOODLE_AUDIT_INSECURE=1` in `~/.hermes/.env` and restart the bridge.
