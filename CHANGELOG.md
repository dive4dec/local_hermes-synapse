# Changelog

All notable changes to `local_hermes-synapse` are documented here.
Format is based on [Keep a Changelog](https://keepachangelog.com/).

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
