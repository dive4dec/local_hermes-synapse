# Changelog

All notable changes to `local_hermes-synapse` are documented here.
Format is based on [Keep a Changelog](https://keepachangelog.com/).

---

## [0.2.0] — 2026-07-29

### Added

#### moodle_quiz_audit skill
- **Audits Moodle quizzes for suspicious student behavior** — fast completion
  + high scores, non-campus IP addresses — by fetching Moodle's built-in
  quiz overview report and access log report pages via HTTP session
  injection. No database access, no Chrome/CDP.
- **Session injection**: reads `$HERMES_HOME/run/msession.json` (written by
  the `local_hermesagent` PHP plugin on each chat API call) and injects the
  user's Moodle session cookie into a `requests.Session()`. The bridge is
  single-threaded, so a single file is safe and always belongs to the
  current user. No `--moodle-userid` parameter needed.
- **Campus IP classification**: uses `MOODLE_AUDIT_CAMPUS_IPS` environment
  variable (comma-separated CIDR). If not set, the skill asks the user for
  their campus ranges and saves them to `.env`. Falls back to standard
  private ranges (10/8, 172.16/12, 192.168/16) if unset.
- **TLS verification on by default**; `MOODLE_AUDIT_INSECURE=1` disables it
  for self-signed certificates.
- **30-minute TTL** on session files; per-request login-redirect guard.
- **`install_deps.sh`** installs `requests` + `beautifulsoup4` into the
  Hermes venv (not system Python, which is PEP 668 locked).

### Fixed

#### moodle_quiz_audit — Moodle 5.x compatibility
- **Quiz report URL**: `/mod/quiz/report.php?id={cmid}&mode=overview`
  (was `/mod/quiz/report/index.php?cmid={}&report=overview` — 404 in 5.x).
- **Log report URL**: `chooselog=1&date=` (empty = all days, not `0` which
  means "today"). Without `chooselog=1` only the filter form renders.
- **Quiz name extraction**: from `<title>` tag (was `<h2>` which grabbed the
  Moodle message drawer heading "Messaging").
- **Max grade**: parsed from `Grade/X.Y` table header (was searching for a
  "Maximum grade" text label that doesn't exist in Moodle 5.x).
- **Column name matching**: flexible substring matching (`First name`,
  `Grade/`, `Started`, `Completed`) instead of exact strings.

#### moodle_quiz_audit — security & portability
- Removed committed `.pyc` files; added `.gitignore`.
- Replaced hardcoded CityU IP ranges with `MOODLE_AUDIT_CAMPUS_IPS` env var.
- Replaced `verify=False` with TLS verification on by default.
- `$HERMES_HOME` resolved from environment first, falls back to default.
- `_load_dotenv()`: standalone scripts read `~/.hermes/.env` at import time
  (the bridge only injects `.env` into the ACP process, not terminal
  subprocesses).
- Dependencies pinned with `>=` floors (not `==`) to avoid conflicts with
  hermes-agent's own dependency pins.

---

## [0.1.1] — 2026-07-16

### Fixed

#### DejaVu Sans fonts for Unicode math in dompdf
- **Greek/math Unicode characters (π, ≤, ⋯) rendered as `?` in PDFs** —
  the CSS `font-family` specified fonts that dompdf doesn't bundle
  (`-apple-system`, `"Segoe UI"`, `"Courier New"`), causing a silent
  fallback to Helvetica, which lacks Greek and math glyphs.
- Changed `font-family` to `"DejaVu Sans"` (body) and `"DejaVu Sans Mono"`
  (code blocks) — these TTFs are bundled with dompdf and embedded
  automatically. Verified: 4 DejaVu subfonts embedded, zero Helvetica.

#### MathJax SVG rendering attempted and reverted
- **MathJax SVG via Node.js `mathjax-full`** was tested as a replacement
  for Unicode approximation — server-side SVG rendering with `liteAdaptor`
  worked, but **dompdf cannot render MathJax SVG output** (`<defs>`,
  `<use>`, `xlink:href`, `transform="scale(1,-1)"` are unsupported).
  Equations did not appear in the PDF. Reverted to Unicode + DejaVu Sans
  approach (commit `9c7e145`).
- Documented as a pitfall in `SKILL.md`: dompdf cannot render MathJax SVG.

---

## [0.1.0] — 2026-07-15

### Added

#### moodle-pdf-generation skill
- **Skill for generating quiz solution PDFs** — provides the agent with
  step-by-step instructions for creating iRAT/gRAT solution PDFs using PHP
  scripts and the `moodle_upload_file` bridge tool.
- Covers the full workflow: PHP script generation → `write_file` →
  `moodle_upload_file` → download link in chat.
- Includes template variables for course ID, quiz name, and display name.

#### moodle-bridge plugin
- **`moodle_upload_file` tool** — uploads a local file to Moodle as a
  `mod_resource` instance, returning the course module ID (`cmid`) for
  download link generation.
- Reads Moodle user identity (username, email, user ID) from
  `~/.hermes/moodle-identity.json` — written by the Moodle plugin during
  bridge startup, not via `on_session_start` hook (which was unreliable).
- Uses `register_tool()` with `toolset="moodle"` parameter.
- File storage follows Moodle conventions:
  - `itemid = 0` (Moodle's `mod_resource/view.php` hardcodes `itemid=0`
    in `get_area_files()`)
  - `stored_filename` includes the source file's extension (e.g.
    `iRAT3 Solutions.pdf`) for correct MIME type detection
  - `displayoptions` uses PHP `serialize()` (not hand-crafted strings)
- **Resources hidden by default** (`visible=0`) — solutions are
  teacher-only until explicitly published. The agent can set
  `visible=true` when the user asks to make a resource visible to students.
- Validates user identity before accepting uploads — rejects requests
  from unregistered or guest users.

### Fixed

#### "File not found" in Moodle resource view — three bugs
- **Bug 1: Missing file extension** — the stored filename omitted the `.pdf`
  extension, so Moodle couldn't determine the MIME type. Fixed by deriving
  `stored_filename` from the source file's extension.
- **Bug 2: Wrong `itemid`** — files were stored with `itemid = $resource->id`
  (e.g. 18), but Moodle's `view.php` looks for `itemid = 0`. Fixed by
  hardcoding `'itemid' => 0`.
- **Bug 3: Corrupted `displayoptions`** — a hand-crafted serialized string
  had `s:10:` for the 7-character key `"display"`, causing `unserialize()`
  to silently return `false`. Fixed by using `serialize(array("display"
  => "inline"))`.

#### `register_tool()` missing `toolset` parameter
- `register_tool()` requires a `toolset` parameter (e.g. `toolset="moodle"`).
  Without it, the tool is registered but never discovered by the agent.

#### `on_session_start` hook unreliable
- Replaced `on_session_start` hook (which fired inconsistently) with
  file-based identity reading: the Moodle plugin writes
  `moodle-identity.json` during bridge startup, and the plugin reads it
  on demand.

### Fixed

#### LaTeX math rendering in PDFs
- **dompdf cannot run JavaScript**, so Moodle's MathJax filter (which wraps
  math in a `<span>` and relies on browser-side JS) doesn't work in PDF
  generation. Math delimiters `\( ... \)` and `$$ ... $$` showed as raw
  text.
- Added `latex_to_html()` + `latex_to_unicode()` server-side converters to
  both `solutions-template.md` and `html-preview-template.md`. Converts
  LaTeX delimiters to Unicode characters (≤, ≥, π, ⋯, ×, →, ∑, √, etc.)
  before passing HTML to dompdf.
- Key insight: `format_text()` with `filter => false` HTML-escapes
  backslashes to `&#92;` — must decode entities **before** matching LaTeX
  delimiters.
- Verified: iRAT 3 Q16 (Leibniz π formula) and Q17 (factorial, `1 ≤ n ≤ 20`)
  now render correctly. Zero raw LaTeX delimiters remain in output.
