---
name: moodle-pdf-generation
description: "Generate PDF documents from Moodle quiz data (student question sheets, instructor answer keys) using HTML preview → dompdf conversion. Platform-independent pure PHP."
---

# Moodle PDF Generation (HTML preview → dompdf)

Class-level skill for producing PDF deliverables from Moodle (quiz question sheets, grade rosters, question-bank printouts). The **recommended path is: build a self-contained HTML preview page → convert to PDF with dompdf** (pure-PHP, real CSS engine, no browser/root needed). Moodle's bundled **TCPDF** is a fallback only — its hand-layout model overlaps markdown-rendered objects with manual elements and clips code boxes.

## Triggers

- User asks to "download as PDF", "print quiz", "export questions as PDF", "give me a PDF of..."
- User wants a printable/paper version of Moodle content (quiz, iRAT/tRAT, exam, grade list)
- User says the PDF "looks better when I print from the HTML" / "use the browser to preview"

## Prerequisites (one-time)

Run the dependency installer once:
```bash
sh $HERMES_HOME/skills/moodle-pdf-generation/scripts/install_deps.sh
```
This downloads dompdf v3.1.5 (pure PHP, includes vendor/) to `$HERMES_HOME/lib/dompdf/`. No composer, no platform-specific binaries — works on any PHP 8.x with `dom`/`gd`/`mbstring` extensions.

## Primary workflow — HTML preview → dompdf (recommended)

dompdf has a real box model, so it respects the HTML's `@media print` stylesheet and does NOT overlap markdown objects with manual elements (the defect that plagues raw TCPDF). It runs in pure PHP — no browser, no root.

1. Generate the self-contained preview HTML (see "HTML preview" section + `references/html-preview-template.md`). It must be fully self-contained: inline `<style>`, no external fonts/images, a `@media print` block, and the per-question payload rendered (options, ordering items, ddwtos `[[n]]` blanks + tiles, coderunner prefill + example test).
2. Convert to PDF: `php scripts/convert_html_to_pdf.php <input.html> <output.pdf>`
   - dompdf is loaded from `$HERMES_HOME/lib/dompdf/vendor/autoload.php` (installed by `install_deps.sh`)
   - The converter sets `defaultMediaType='print'` so print CSS applies, and `isHtml5ParserEnabled=true`.
3. Output to `/var/www/moodledata/.hermes/cron/output/<name>.pdf`, deliver via `MEDIA:`.

**Why this beats TCPDF:** TCPDF mixes `writeHTML()` (markdown) with manual `Cell()`/`MultiCell()`/`Rect()` positioning; after a `writeHTML` block it reports the wrong Y, so the next hand-placed element lands on top of the markdown output ("overlaps with non-markdown elements"). The user explicitly confirmed the HTML→print route "looks better."

**dompdf caveat:** limited `flexbox` support. The question header row (number / name / mark) uses `display:flex` → may stack/align oddly. If fidelity matters, build that header as a `<table>` instead of flex. Everything else (paragraphs, code blocks, lists, tables) renders faithfully.

## Fallback workflow — raw TCPDF (only if dompdf unavailable)

Use Moodle's bundled `lib/tcpdf/tcpdf.php` when you cannot install dompdf (no network). Mind the overlap/clip pitfalls below.

## Environment reality

- `wkhtmltopdf`, `chromium`, `google-chrome`, `weasyprint`, `pandoc`, `libreoffice` → typically **MISSING** on Moodle pods.
- Python PDF libs (`reportlab`, `fpdf`, `weasyprint`) → **NOT installed** in the Hermes venv.
- Moodle's **TCPDF** is bundled at `/var/www/html/public/lib/tcpdf/tcpdf.php`.
- **dompdf** is installed by `install_deps.sh` to `$HERMES_HOME/lib/dompdf/`.
- Output location: write PDFs to `/var/www/moodledata/.hermes/cron/output/` (writable, deliverable via `MEDIA:` path).

## Fetching a quiz's questions (Moodle 5.x+)

The MCP query tool flakes on multi-joins and `mdl_quiz_slots` no longer has a `questionid` column. Fetch in PHP via this join, ordered by slot:

```php
$sql = "SELECT DISTINCT qv.questionid AS qid, q.qtype, q.name, q.questiontext, q.questiontextformat, q.defaultmark
        FROM mdl_quiz_slots s
        JOIN mdl_question_references qr
          ON qr.itemid = s.id AND qr.component='mod_quiz' AND qr.questionarea='slot'
        JOIN mdl_question_bank_entries qbe ON qbe.id = qr.questionbankentryid
        JOIN mdl_question_versions qv ON qv.questionbankentryid = qbe.id
        JOIN mdl_question q ON q.id = qv.questionid
        WHERE s.quizid = :quizid
          AND qv.version = (SELECT MAX(v2.version) FROM mdl_question_versions v2
                            WHERE v2.questionbankentryid = qbe.id)
        ORDER BY s.slot";
$rows = $DB->get_records_sql($sql, ['quizid' => $quizid]);
```

Use **raw table names** (`mdl_...`) — `get_records_sql()` does NOT do `{...}` brace substitution (unlike `get_records()`), and selecting a non-existent column (e.g. `qbe.questionid`, which does not exist) throws "Unknown column".

## ⚠️ Stored text formats — ALWAYS run through `format_text()` (Markdown trap)

Quiz question stems AND answers are frequently stored in **Markdown format** (Moodle `format = 4`), e.g. an answer `` `#include <headerfile>` `` is inline-code markdown. If you `strip_tags()` and naively swap `<code>`→backticks, the **literal markdown leaks into the output** (user sees `` `#include <headerfile>` `` with backticks). This is the single most common rendering defect in these exports.

**Fix:** render every stored field through Moodle's `format_text()`, which converts HTML/Markdown/MOODLE → clean HTML per the field's own `format`:

```php
require_once($CFG->libdir . '/weblib.php');   // defines format_text()

// $raw = the stored text; $format = the field's *format column* (questiontextformat / answerformat)
function irat_format($raw, $format) {
    return format_text($raw, $format, ['noclean' => true, 'filter' => false]);
}
```

- **PDF:** feed the formatted HTML to dompdf (renders `<code>` as monospace, headings, lists). For multichoice/ordering answers, print the letter prefix then the formatted answer.
- **HTML preview:** embed `format_text()` output directly (it's already HTML).
- **CodeRunner `answerpreload` / test code:** these are *actual code*, NOT markdown — pass the raw value, do NOT send through `format_text()` (it would mangle `<`, `>`, `&`). Escape with `htmlspecialchars()`.
- **DDWTOS `[[1]]` blanks:** after `format_text()`, replace `[[n]]` with a blank line / blank span. In the PDF use plain text `_____`; in HTML use `<span class="blank"></span>`.
- **Always SELECT the format column** in your query: `q.questiontextformat` and `a.answerformat` (alias `format` from `question_answers`).

## Rendering question-type details (the part students actually need)

A stem-only PDF is useless for practice. Pull and render the per-type payload:

- **multichoice / ordering / ddwtos** → options live in `mdl_question_answers` (`question` = qid).
  - multichoice: list each as `A) … B) …` (letters from `range('A','Z')`).
  - ordering: list items; the `fraction` column is the correct order index (1,2,3…) — for a student sheet just list them with "arrange into the correct order".
  - ddwtos: the stem contains literal `[[1]]`, `[[2]]` blanks — convert them to blank lines (`_____`) in the cleaned text so students see where to write. **Render the draggable terms from `mdl_question_answers` as bordered TILES**, NOT a comma-separated "Available terms:" line — students need to see the actual pieces to drag.
- **coderunner** → two tables:
  - `mdl_question_coderunner_options` (`questionid`) → `answerpreload` is the **pre-filled answer box** (render in a monospace grey code box), `answer` is the model solution.
  - `mdl_question_coderunner_tests` (`questionid`) → the **example test** is the row with `useasexample = 1` AND `display = 'SHOW'`. Render `testcode` (the run selector), `stdin`, and `expected` output so students see the sample run.

## Solutions / answer-key variant (with answers + hidden tests)

A "solutions" deliverable is the same generator with answer rendering switched on — produce a second HTML file (then dompdf it), or add a `$with_solutions` flag to the shared generator. The data logic per type:

- **multichoice**: correct option(s) = `(float)$a->fraction > 0`. Tick them green; show the weight as `number_format((float)$a->fraction * 100, 0) . '%'` (**integer percentage** — user does NOT want decimals here). **Multi answer questions** store several `fraction > 0` rows (e.g. two at `0.5` each) — tick ALL of them. Distractors (`fraction == 0`) get no tick.
  - **Rounding (FINAL state, 2026-07-14):** PERCENTAGES = **integer** (`number_format(x*100, 0)`). TEST-CASE `Mark` column = **3 decimals** (`number_format((float)$t->mark, 3)` → `1.000`). QUESTION HEADER `defaultmark` = **raw DB value** (`{$r->defaultmark} mark` → `1.0000000`) — do NOT reformat it.
- **ordering**: correct order = `get_records('question_answers', [...], 'fraction ASC')`. In iRAT1 the fractions are `1.0, 2.0, 3.0…` so ascending = the solution sequence. Render as a green ordered list labelled "Correct order".
- **ddwtos**: the question stores ALL candidate terms in `question_answers` in `id` order (including distractors). List all terms (id order) in a solution block and let the stem show which blanks to fill.
- **coderunner**:
  - **Reference solution** = `mdl_question_coderunner_options.answer` (real code — do NOT `format_text` it). Render in a green `pre.code.solution` box.
  - **ALL test cases** = every row of `mdl_question_coderunner_tests` for the question (not just the example). Flag visibility per row: `display = 'SHOW'` → "Shown" (green), `display != 'SHOW'` → "HIDDEN" (red); `useasexample = 1` appends "(example)". Render a table: `# / Visibility / Test code / Stdin / Expected output / Mark`, with **Mark = `number_format((float)$t->mark, 3)`** (3 decimals).

Add an **"INSTRUCTOR COPY — CONTAINS ANSWERS & HIDDEN TESTS"** banner on the cover so it isn't confused with the student sheet.

Full working generator: `references/solutions-template.md`.

## Pitfalls

- **CLI_SCRIPT define:** `define('CLI_SCRIPT', true)` lowercase fails with "CLI_SCRIPT define must be TRUE not true". Use `TRUE`/`1`.
- **$_SERVER['REQUEST_URI'] / SCRIPT_NAME must be set in CLI scripts.** Set `$_SERVER['REQUEST_URI']='/edb/'; $_SERVER['SCRIPT_NAME']='/edb/admin/cli/foo.php';` BEFORE `require_once(config.php)`.
- **Function name collision:** Moodle's `weblib.php` defines a global `clean_text()`. Defining `function clean_text()` = fatal "Cannot redeclare". Name yours `irat_clean_text()`.
- **Silent exit 255** = suppressed fatal. Rerun: `/usr/local/bin/php -d display_errors=1 -d error_reporting=E_ALL script.php`.
- **`format_text()` for Markdown fields:** quiz stems/answers are often stored as Markdown (`format=4`). Sending raw text through `strip_tags` + a backtick swap leaks literal markdown. Run every field through `format_text($raw, $formatcol)` before rendering. CodeRunner code fields are real code — do NOT format_text them.
- **⚠️ Heredoc PHP trap:** Inside a `<<<HTML ... HTML;` heredoc, PHP does NOT execute `<?php ... ?>` blocks or `. expression .` concatenations — they are written **literally** into the output file. **Fix:** compute any dynamic value into a plain variable BEFORE the heredoc, then interpolate `{$var}` inside it.
- **Never hardcode the course/subtitle name on the cover — look it up from the DB.** Resolve via the quiz: `$qrec = $DB->get_record('quiz', ['id' => $quizid], 'course'); $course = $DB->get_record('course', ['id' => $qrec->course], 'fullname');` then print `{$course->fullname}`.
- **Question-title omission (student paper):** The student version must NOT show the internal Moodle question `q.name` — show only `Question N` + mark. The SOLUTIONS/instructor version MAY keep `q.name` as a reference.
- **Cover mark rounding:** the question header `defaultmark` from the DB is a full float (e.g. `1.0000000`). Render it as the **raw value** `{$r->defaultmark} mark` — do NOT reformat. Test-case `Mark` column stays 3 dp (`1.000`).
- **⚠️ LaTeX math in PDFs:** Moodle stores math as `\( ... \)` (inline) and `$$ ... $$` (display) delimiters. The MathJax filter wraps these in a `<span>` but relies on **browser-side JavaScript** to render — dompdf cannot run JS, so the math shows as raw `\( ... \)` text. The `fmt()` function in the templates applies `latex_to_html()` which converts LaTeX delimiters to **Unicode characters** (≤, ≥, π, ⋯, ×, →, ∑, etc.) server-side. This handles the common symbols in CS quiz questions. For complex LaTeX (matrices, multi-line equations), a browser-based pipeline (wkhtmltopdf + MathJax) would be needed.
- **`format_text()` HTML-escapes LaTeX:** with `filter => false`, `format_text()` turns `\(` into `&#92;(` and `*` into `&#42;`. The `latex_to_html()` function decodes these entities **before** matching LaTeX delimiters.

## References

- `references/quiz-pdf-example.md` — full working iRAT1 TCPDF PDF generator (fallback)
- `references/html-preview-template.md` — full working HTML-preview generator (primary deliverable; dompdf source)
- `references/solutions-template.md` — full working SOLUTIONS (answer-key) generator: ticks correct multichoice/ordering/ddwtos, CodeRunner reference solution + ALL test cases incl. hidden
- `scripts/convert_html_to_pdf.php` — dompdf converter: `php convert_html_to_pdf.php <in.html> <out.pdf>`
- `scripts/install_deps.sh` — one-time dompdf v3.1.5 installer (pure PHP, platform-independent)
