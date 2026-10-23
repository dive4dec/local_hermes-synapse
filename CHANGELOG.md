/usr/bin/bash: _parse_usage: line 16: syntax error near unexpected token `('
/usr/bin/bash: _parse_usage: line 16: ` -?(\[)+([a-zA-Z0-9?]))'
/usr/bin/bash: error importing function definition for `_parse_usage'
/usr/bin/bash: _longopt: line 6: syntax error near unexpected token `('
/usr/bin/bash: _longopt: line 6: ` --!(no-*)dir*)'
/usr/bin/bash: error importing function definition for `_longopt'
# Changelog

All notable changes to `local_hermes-synapse` are documented here.
Format is based on [Keep a Changelog](https://keepachangelog.com/).

---

## [Unreleased]

### Added — coderunner-question-creation (2026-10-23)

**`skills/moodle/coderunner-question-creation/`** — create Code Runner
(python3) questions for mock exams / quizzes. Ported from the live course pod,
PII-scrubbed and generalised like the rest of the set:

- `SKILL.md` — two question "generations", three-table anatomy, versioning
  model (live = max `question_versions.version` per bank entry), headless
  creation paths (hand-authored XML import + `save_question`), bulk
  generator-verify-emit, and the build's modified-schema gotchas.
- `references/headless-creation-recipe.md` — CLI bootstrap `require`s,
  `save_question` alternative, canonical insert order, stored shape of a
  mimic-target question, verification checklist.
- `references/xml-import-recipe.md` — the verified two-stage import
  (parse-only → import) PHP sequence + full worked XML + field contract.
- `templates/bulk_question_generator.py` — generator-verify-emit skeleton
  (question data → real-Python verification of every answer/test → XML).
  Now env-driven: `MHS_CODE_RUNNER_PROTOTYPE` (default
  `python3_cs1302_prototype`) and `MHS_WEBROOT`.

Concretely course-specific values (category/context/question/CMID ids, the
prototype name, the bank-author uid) are expressed as `<token>`s with the
reference instance's value noted inline as `(ref N)` so the skill stays
actionable without baking in one course's data. New env var
`MHS_CODE_RUNNER_PROTOTYPE` registered in `_conventions/PORTABLE.md`.
The two dated case-study references (`mockexam-bank-25-26.md`,
`bulk-creation-run-2026-10-22.md`) were **not** ported (PII / course-locked
worked data).

### Added — Portable skill port (2026-10-18)

**59 skills** ported from a live Moodle pod, generalised to be **hermetic,
secret-free, and course-agnostic**. New skills / files:

- **`skills/mhs-setup/`** — meta-skill that bootstraps the whole set: detects
  the Moodle version, gates on **5.2+** (floor `2026042000`), derives `MHS_*`
  env vars from `config.php` / the DB (read-only `mhs_probe.php`), and persists
  them conflict-aware + idempotently (`mhs_env.sh`). Re-runnable after merging
  updated skills.
- **`skills/_conventions/PORTABLE.md`** — single source of truth for the `MHS_`
  env-var scheme, the read→default→ask→persist contract, the version gate, the
  token→env mapping, and the incremental-merge rules.

### Changed — generalisation + PII scrub

- **`MHS_` env-var scheme** introduced. Course/site-specific values now read
  from env vars (never hardcoded):
  - course codes `cs1302*` → `<coursecode>` / `<other-coursecode>` / `<course>`
  - numeric course ids → `<cid>` / `<other-coursecid>`
  - helpers group id → `<helpergid>`
  - `/var/www/html/public` → `<webroot>`, `/var/www/moodledata` → `<datadir>`
  - lab/campus/public IP ranges → `<lab-cidr>` / `<campus-cidr>` / `<private-ranges>`
- **PHP scripts** now carry an env bootstrap (`$WEBROOT`/`$DATA_DIR`/`$CID`/`$QUIZ`
  from `MHS_*` with standard defaults) so they remain executable while portable.
- **PII scrubbed** across all ported skills: real personal emails, student/instructor
  names, staff identities, and the operator hostname (`<moodle-host>`,
  `<smtp-host>`, `<staff-email>`, `<student-email>`, `<Instructor-Name>`,
  `<Staff-D>`, `<staff-github>`, `<student-domain>`, `<domain>`). Synthetic
  test-account identifiers (`LTITEST`, `@example.com`) retained (not PII).
- **Case-study reference files excluded** (individual-incident narratives
  containing real student PII).

### Removed

- **`moodle_quiz_audit` skill** deliberately **not ported** — it was already
  superseded by the in-repo `moodle_audit_quiz` **plugin tool** (see 0.2.2)
  because the skill had a concurrency bug. The 59 ported skills do not include it.

### Rollback

Each phase is one git commit on branch `portable-port`; rollback any phase with
`git revert <commit>`:
`09ae00f` (copy), `6460b8b` + `7361984` (PII), `d9b9b48` (generalise),
`5117f96` (mhs-setup). Baseline anchor: `3f0959d`.

## [0.2.2] — 2026-08-21

### Added

#### moodle-bridge plugin: `moodle_audit_quiz` tool (in-process DB audit)
New in-process plugin tool that replaces the old `moodle_quiz_audit` **skill**.
It runs entirely on the Moodle database (no HTML scraping, no child process, no
session cookie), so the per-session concurrency race that broke the skill (a
terminal child inherits a stale process-global `HERMES_SESSION_KEY` under
concurrency) is **structurally impossible** — the tool never spawns a process
and never reads a per-session env file.

- **Fast-completion check** (AI-misuse signal): flags attempts where
  `timefinish - timestart < fast_mins` AND `grade_pct >= fast_score`.
  Defaults `fast_mins=10`, `fast_score=80`.
- **Off-campus IP check**: pulls each attempt's IP(s) from `logstore_standard_log`
  (`attempt_viewed`/`attempt_updated`/`attempt_submitted`, joined on
  `objectid = quiz_attempts.id`), then flags attempts with `campus_ips` set if
  **any** observed IP is outside all listed CIDRs. `campus_ips` is an optional
  param/env (CIDR list) — **not hard-coded**; when unset the tool just lists
  the IPs and flags nothing (the admin judges on campus vs off-campus).
- **Authorisation**: restricted to staff (manager/teacher role at the course's
  or site context). Students are denied. Role matching is naming-robust
  (handles standard `editing teacher` and this site's `editingteacher`).
- Returns structured JSON (attempts, flags, SEB access-blocks, a logstore
  retention-window note).

### Removed

#### moodle_quiz_audit skill
Deleted (repo + deployed NFS). Its HTML-scraping approach was over-engineered
(the same data is queryable in the DB) and its child-process path was
unreliable under concurrent admin sessions. Superseded by the
`moodle_audit_quiz` plugin tool above.

### Notes
- **Plugin version bump 1.0.1 → 1.1.0** (`plugins/moodle-bridge/plugin.yaml`): the
  version field is display-only (the hermes installer never compares it), so this
  is purely so the dashboard can distinguish pre/post-audit-tool deployments.
- **Log retention**: attempt IPs live only as long as the logstore retains rows
  (currently a ~70-day window). Fast-completion data lives in `quiz_attempts`
  (kept indefinitely). IP audits should be run soon after a quiz.

---

## [0.2.1] — 2026-07-29

### Fixed

#### moodle_quiz_audit skill
- **"Skill 'moodle' not found" error**: The `skills/moodle/` directory had no
  `SKILL.md` at top level (only nested sub-skills like `moodle-admin/` inside).
  The ACP saw `moodle` as a directory, tried to load it as a skill, and failed.
  Fix: flattened the nested structure — all sub-skills are now top-level
  directories (`moodle-admin/`, `moodle-course-queries/`, etc.).
- **Unnecessary approval prompt**: SKILL.md told the agent to check `.env` for
  `MOODLE_AUDIT_CAMPUS_IPS`, but the "If NOT set → write to `.env`" instruction
  came before "If already set → proceed". The agent sometimes tried to write to
  `.env` even when the var was already set, triggering the Hermes terminal
  safety guard. Fix: reordered — "If already set → proceed, do NOT write to
  `.env`" comes first.
- **Simplified session handling**: removed `--moodle-userid` parameter entirely.
  The bridge is single-threaded, so the PHP plugin writes a single `msession.json`
  file (fixed path) that always belongs to the current user. No userid lookup
  needed.

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
