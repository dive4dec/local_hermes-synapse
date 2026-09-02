---
name: moodle-auto-download
description: "Downloads student attempts from Moodle quizzes based on score rankings (server-side zero-action mode — injects the requesting user's live Moodle session into a headless browser, no manual browser step, no credentials)"
---

# Skill: Moodle Quiz Attempts Auto-Downloader

## Description

Scans a specified Moodle course for all quizzes matching keyword filters. For
each matched quiz, it filters and downloads a configured number of student
attempts as PDF files, sampled by score ranking (high, medium, low quantities,
excluding zero scores).

**As of 2026-07-17 this tool runs in CDP attach mode.** As of **2026-07-17 (later
same day)** it ALSO supports a **server-side zero-action mode** that is the
default inside the local_hermesagent Moodle plugin and needs NO manual browser
step from the user.

The tool never takes a username/password. There are two ways it gets an
authenticated session:

1. **Server-side session-inject mode (default in the plugin, preferred).** The
   `local_hermesagent` plugin writes a per-user session file
   (`$HERMES_HOME/run/msession.json`) on every chat request, containing
   the user's live MoodleSession cookie. The tool launches its OWN headless
   Chromium, injects that cookie via CDP `Network.setCookie`, and browses AS that
   user. The user does nothing — no password, no browser launch. Multi-user safe:
   each run uses the requesting user's own session file.
2. **Attach mode (manual / debugging).** Connect over CDP to a browser the user
   has already opened and logged into. Kept for local testing; never needed in
   the plugin.

Both modes are version-proof (no chromedriver) and credential-free (no secrets
on the command line or in the agent context). The session file is mode 0600 and
enforced with a TTL.

This is fully implemented by the pre-built tool `moodle_quiz_downloader_tool.py`
— **the agent must run that tool, never recreate it.** (The old Selenium version
is preserved as `moodle_quiz_downloader_tool.py.selenium.bak`.)

## Triggers

- User asks to "download attempts", "moodle auto download", "download quiz attempts", "moodle quiz", "exam", or similar.

## Setup (one-time, only if the tool will not run)

    cd $HERMES_HOME/skills/moodle-auto-download/scripts
    sudo ./install_deps.sh

Dependencies: `requests` and `websocket-client` only. No Selenium, no
chromedriver, no database access.

## How the agent uses this skill (CRITICAL)

1. **Do NOT write, generate, or modify any script.** The whole workflow already
   exists as a single executable:
   `$HERMES_HOME/skills/moodle-auto-download/moodle_quiz_downloader_tool.py`, and
   its default behavior is to scan **all** quizzes in the course.
2. **In the Moodle Hermes chat, use server-side mode** — the tool automatically
   reads the requesting user's identity from `$HERMES_HOME/.moodle_identity`
   (written by the ACP bridge on each request). Do NOT pass any user id as a CLI
   argument. The tool launches its own headless browser; no browser prerequisite.
3. **Gather the required inputs** (see below) and **run the tool via terminal**.
   The agent's job is only to collect inputs, invoke the tool, and report output.

Example invocation the agent should produce (zero user action):

    python3 $HERMES_HOME/skills/moodle-auto-download/moodle_quiz_downloader_tool.py \
        --moodle-url "<MOODLE_URL>" \
        --course-identifier "<COURSE_ID or COURSE_NAME>" \
        --high-quantity <HIGH_QUANTITY> \
        --medium-quantity <MEDIUM_QUANTITY> \
        --low-quantity <LOW_QUANTITY>

Attach-mode invocation (only for local manual testing, where you have a browser
open with `--remote-debugging-port=9222` and logged into Moodle):

    python3 $HERMES_HOME/skills/moodle-auto-download/moodle_quiz_downloader_tool.py \
        --debugger-address "127.0.0.1:9222" \
        --moodle-url "<MOODLE_URL>" \
        --course-identifier "<COURSE_ID or COURSE_NAME>" \
        --high-quantity <HIGH_QUANTITY> --medium-quantity <MEDIUM_QUANTITY> \
        --low-quantity <LOW_QUANTITY>

Optional extras the agent may pass if the user asks:
- `--output-dir /var/www/moodledata/.hermes/cron/output/` — where PDFs are saved (this is the default)
- `--no-download` — only print the selected sample, do not render PDFs
- `--keywords "iRAT1"` — restrict to quizzes whose name contains the keyword(s).
- `--exact-quiz-name` — match quiz names **exactly** (case-insensitive) instead
  of as a substring. **Use this whenever a quiz name is a prefix of another**,
  e.g. to target `iRAT1` without also catching `iRAT10`. Requires `--keywords` to
  list the exact quiz name(s).
- `--session-file <path>` — explicit msession JSON path (bypasses auto-resolution).
- `--session-ttl <seconds>` — max session-file age (default 1800).

**IMPORTANT — quiz names without "Test"/"Quiz":** Many quizzes are named things
like "Midterm", "Exam", "Assignment", or a plain topic, and some are prefixes of
other quizzes (e.g. `iRAT1` vs `iRAT10`). The tool's default is to scan **all**
quizzes in the course. When the user names a specific quiz, prefer
`--keywords "<exact name>" --exact-quiz-name`. **Never edit or fork the script**
to change matching behavior — use these flags. The script must remain untouched.

## Server-side session: how auth works (no password, no manual browser)

- `local_hermesagent` writes `$HERMES_HOME/run/msession.json` (mode 0600)
  on every chat request, containing the user's MoodleSession cookie name/value,
  derived domain/path/secure, and `written_at`.
- The tool reads the user's identity from `$HERMES_HOME/.moodle_identity`
  (written by the ACP bridge), resolves the session file path, launches a
  headless Chromium, injects the cookie, and browses as the user.
- If the file is missing or older than `--session-ttl` (default 1800s), the tool
  fails with a clear message asking the user to send a fresh chat message first
  (that refreshes the session file).

## User Inputs Required

* `MOODLE_URL`: The base URL of the Moodle site.
* `COURSE_IDENTIFIER`: The target course ID (e.g. `2`) or the exact Course Name.
* `HIGH_QUANTITY`: Number of top-scoring attempts to download.
* `MEDIUM_QUANTITY`: Number of median-scoring attempts to download (closest to the 50th percentile).
* `LOW_QUANTITY`: Number of bottom-scoring attempts to download (excluding 0 scores).

(User identity is automatic — the tool reads it from the bridge's `.moodle_identity` file. No USERNAME/PASSWORD — authentication is injected from the user's live session.)

## What the tool does (for the agent's awareness — do not reimplement)

1. **Session**: server-side mode launches its own headless Chromium and injects
   the user's MoodleSession cookie via `Network.setCookie`; attach mode connects
   to `--debugger-address` and reuses the existing session. `verify_logged_in()`
   checks `/my/` and fails clearly if not authenticated.
2. **Course resolution**: if `COURSE_IDENTIFIER` is numeric it builds
   `course/view.php?id=...`; otherwise it searches by name and picks the match.
3. **Quiz scan**: collects `mod/quiz/view.php` links via JS and keeps those
   whose name matches `--keywords` (substring, or exact with `--exact-quiz-name`).
4. **Stratified sampling**: for each quiz it opens the overview report
   (`mod/quiz/report.php?...&mode=overview&attempts=all_with`), pages through ALL
   attempts, opens each attempt's own review page to read the authoritative grade,
   sorts by grade descending, drops zero scores, then selects:
   - **High** — top `HIGH_QUANTITY` attempts,
   - **Low** — bottom `LOW_QUANTITY` attempts (rank 1 = lowest),
   - **Medium** — `MEDIUM_QUANTITY` attempts centered on the median (start=(n-m)//2).
   Overlapping attempts are de-duplicated and tagged with their group + rank.
5. **PDF download**: for each selected attempt it opens the review page and
   renders it via `Page.printToPDF`, saved as
   `[Quiz_Name]_[Group]_Rank[Rank]_[User_ID].pdf` in the output directory.
6. **Cleanup**: in server-side mode the launched browser is terminated and its
   profile dir removed; in attach mode only its own tab is closed (the user's
   browser is never quit).

## Agent guardrails

- Never guess credentials or try to log in — server-side mode reuses the user's
  live session; attach mode relies on the user's browser. A login-page redirect =
  ask the user to re-send a chat message (refreshes the session file), not a fix.
- If `requests`/`websocket-client` are missing, install requirements first, then
  re-run — do not rewrite the script.
- If a quiz yields zero non-zero attempts, the tool simply skips it; report that
  to the user rather than retrying with different logic.
- **Moodle 5.x DB quirk**: `mdl_quiz` no longer has a `questioncount` column.
  Queries selecting it return empty results silently. Use `sumgrades` instead to
  check quiz totals. Always verify column existence with `DESCRIBE mdl_quiz`
  before assuming column names match older Moodle versions.

## Score reporting — CRITICAL

The tool parses grades from the Moodle review/overview pages. The values it
reports are **whatever Moodle renders** — which may be raw grades, percentages,
scaled grades, or aggregated values depending on Moodle configuration. They are
NOT guaranteed to match `mdl_quiz_attempts.sumgrades` (raw grades in the DB).

**When summarizing results to the user:**
1. **ALWAYS look up the quiz's max grade** (`mdl_quiz.grade`) before reporting scores.
2. If the tool-reported scores exceed the quiz max grade, explicitly note that the
   scores are **not raw grades** and clarify what they likely represent.
3. If the user needs accurate raw scores, query the database directly:
   `SELECT id, userid, sumgrades FROM mdl_quiz_attempts WHERE quiz = <quiz_id>
   AND state = 'finished' ORDER BY sumgrades DESC`
4. Never present tool-reported scores as "percentage" or "raw points" without
   verifying against the quiz's `grade` field first.
5. **DB query quirk**: the `mdl_quiz_attempts.grade` column is **redacted** by the
   MCP DB tool (returns empty rows when included in SELECT). Use `sumgrades`
   instead for raw scores. Also, `mdl_quiz.grade` may differ from the actual
   `sumgrades` max due to Moodle grade scaling — the percentage formula is
   `sumgrades / (max sumgrades) × 100`, NOT `sumgrades / mdl_quiz.grade × 100`.
