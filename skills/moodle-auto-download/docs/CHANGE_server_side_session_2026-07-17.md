# CHANGE: Server-side session-inject mode (zero user action, multi-user)

**Date:** 2026-07-17
**Skill:** moodle-auto-download
**Author:** Hermes Agent

## Why
The original CDP rewrite attached to a *user's own* browser, which assumes the
user manually launches Chrome with `--remote-debugging-port`. In the Moodle
Hermes chat context that runs server-side for *many* users, this is infeasible:
- Browsers refuse to let a web page open a CDP port, so there is no way to
  auto-launch the user's local browser from the chat.
- Asking every user to run a terminal command is unacceptable.

But the user's live Moodle login already exists server-side: the Hermes chat
request passes through `require_login()` with the real session cookie in
`$_COOKIE[session_name()]`. The fix is to **mirror that session into a headless
browser the tool launches itself**, so the user never does anything.

## What changed

### PHP (local_hermesagent plugin)
- `lib.php`: added `local_hermesagent_write_user_session(?int $userid)`.
  Writes `$HERMES_HOME/run/msession_<userid>.json` (chmod 600) containing the
  MoodleSession cookie name/value, derived domain, path, secure flag, and a
  `written_at` timestamp (TTL enforcement lives in the Python tool).
- `api.php` (`api_stream_response`): call `local_hermesagent_write_user_session()`
  on every stream request, **before** `session_write_close()`, so the cookie
  handed to a tool is always current for that requesting user.

### Python tool
- `CDPSession.launch()`: classmethod that starts local headless Chromium
  (free port, `--headless=new`, `--no-sandbox`, `--ignore-certificate-errors`,
  temp user-data-dir) and returns a connected session. Tracks the child process
  so `close()` can terminate it and clean the profile dir.
- `CDPSession.set_cookie(...)`: `Network.setCookie` wrapper to inject the
  user's Moodle cookie into the launched browser.
- `MoodleQuizDownloader.__init__`: now takes `session` (parsed msession dict)
  or `debugger_address`. `session` => server-side mode (launch + inject);
  else attach mode (unchanged).
- `verify_logged_in`: mode-aware error message.
- CLI: added `--moodle-userid`, `--session-file`, `--session-ttl` (default
  1800s). `--debugger-address` no longer has a default; attach mode is opt-in.
  `_resolve_session()` loads + TTL-checks the msession file.

## Security posture
- No password, no username in the command line or agent context.
- Session secret lives in a per-user, mode-0600 file under `$HERMES_HOME/run`
  (not web-served).
- TTL rejects stale sessions; tool asks the user to re-send a chat message
  (which refreshes the file) when expired.
- The launched browser is the tool's own; it is always terminated after the run.

## Usage (server-side, default in the plugin)
```
python3 moodle_quiz_downloader_tool.py \
  --moodle-userid <id from $USER->id> \
  --moodle-url https://deep.cs.cityu.edu.hk/equiz \
  --course-identifier CS2310 \
  --high-quantity 5 --medium-quantity 5 --low-quantity 5 \
  --keywords iRAT1 --exact-quiz-name
```

## Verification
- `php -l` clean on lib.php and api.php.
- `python3 -m py_compile` clean.
- Mechanism E2E (container): `CDPSession.launch()` → `set_cookie()` → navigate
  real Moodle login page → `printToPDF` produced a valid `%PDF-` (13 KB) →
  `close()` killed the browser. Browser is Chrome/131.0.6778.108 (container).
- Real authenticated download awaiting a live msession file, which the plugin
  emits per user on each chat request.
