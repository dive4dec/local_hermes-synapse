# HTML Preview Template (student question-paper — browser print fallback)

Full working PHP CLI script that generates a self-contained, Moodle-styled HTML
preview of a quiz, suitable for the user to open in their own browser and print
to PDF (Ctrl+P → Save as PDF). This is the **question-paper / student** variant:
it renders the full question payload but **omits the internal question `q.name`**
title (shows only "Question N" + mark). Use this when the user says "preview it
and print to PDF" and no headless browser is available.

## Key invariants baked in (from 2026-07-14 fixes)
- **Every stored text field goes through `format_text($raw, $formatcol)`** so
  Moodle Markdown (`format=4`) renders as HTML, not literal backticks.
  CodeRunner `answerpreload` / test code is REAL code — escape with `htmlspecialchars`,
  do NOT `format_text` it.
- **Course name on the cover is looked up from `mdl_course.fullname`**, never hardcoded.
- **No `q.name` in the student header.**
- **CSS normalises Moodle's markdown `<p>` wrappers** so inline-code / code blocks
  don't overlap labels (`.opt p{display:inline}`, `.qstem p{margin:0 0 6px}`,
  `code`/`pre.code` get `white-space:pre-wrap; word-break:break-word`).

## Generator (verified 2026-07-14, iRAT1 / quiz id 142)

```php
<?php
define('CLI_SCRIPT', true);
$_SERVER['REQUEST_URI'] = '/edb/';
$_SERVER['SCRIPT_NAME'] = '/edb/admin/cli/foo.php';
require_once('/var/www/html/public/config.php');
global $CFG, $DB;
require_once($CFG->libdir . '/clilib.php');
require_once($CFG->libdir . '/weblib.php');

$quizid = 142; // cs2310_25a iRAT1 — set to target quiz

$sql = "SELECT DISTINCT qv.questionid AS qid, q.qtype, q.name, q.questiontext, q.questiontextformat, q.defaultmark
        FROM mdl_quiz_slots s
        JOIN mdl_question_references qr ON qr.itemid = s.id AND qr.component='mod_quiz' AND qr.questionarea='slot'
        JOIN mdl_question_bank_entries qbe ON qbe.id = qr.questionbankentryid
        JOIN mdl_question_versions qv ON qv.questionbankentryid = qbe.id
        JOIN mdl_question q ON q.id = qv.questionid
        WHERE s.quizid = $quizid AND qv.version = (SELECT MAX(v2.version) FROM mdl_question_versions v2 WHERE v2.questionbankentryid = qbe.id)
        ORDER BY s.slot";
$rows = $DB->get_records_sql($sql, []);

// Resolve course fullname from the quiz (never hardcode the subtitle).
$qrec = $DB->get_record('quiz', ['id' => $quizid], 'course');
$course = $DB->get_record('course', ['id' => $qrec->course], 'fullname, shortname');
$coursefull = $course->fullname;

function esc($s) { return htmlspecialchars($s, ENT_QUOTES | ENT_HTML5, 'UTF-8'); }
function fmt($raw, $format) { return format_text($raw, $format, ['noclean' => true, 'filter' => false]); }

$letter = range('A', 'Z');
$qhtml = '';
$n = 0;
foreach ($rows as $r) {
    $n++;
    $body = '';
    if ($r->qtype === 'multichoice') {
        $ans = $DB->get_records('question_answers', ['question' => $r->qid], 'id');
        $i = 0;
        foreach ($ans as $a) {
            $body .= '<div class="opt"><span class="lbl">' . $letter[$i] . '.</span> ' . fmt($a->answer, $a->answerformat) . "</div>\n";
            $i++;
        }
    } else if ($r->qtype === 'ordering') {
        $ans = $DB->get_records('question_answers', ['question' => $r->qid], 'fraction');
        $body .= '<ol class="orderlist">' . "\n";
        foreach ($ans as $a) { $body .= '  <li>' . fmt($a->answer, $a->answerformat) . "</li>\n"; }
        $body .= "</ol>\n<p class=\"hint\">Arrange the items above into the correct order.</p>\n";
    } else if ($r->qtype === 'ddwtos') {
        $ans = $DB->get_records('question_answers', ['question' => $r->qid], 'id');
        $opts = [];
        foreach ($ans as $a) { $opts[] = fmt($a->answer, $a->answerformat); }
        $body .= '<p class="hint">Drag the correct term into each blank below:</p>' . "\n";
        $body .= '<div class="tiles">' . "\n";
        foreach ($opts as $o) { $body .= '  <span class="tile">' . $o . "</span>\n"; }
        $body .= "</div>\n";
    } else if ($r->qtype === 'coderunner') {
        $opt = $DB->get_record('question_coderunner_options', ['questionid' => $r->qid]);
        if ($opt && !empty($opt->answerpreload)) {
            $body .= "<p class=\"cr-label\">Answer box (pre-filled — fix the bugs):</p>\n";
            $body .= '<pre class="code">' . esc($opt->answerpreload) . "</pre>\n";
        }
        $tests = $DB->get_records('question_coderunner_tests', ['questionid' => $r->qid], 'id');
        foreach ($tests as $t) {
            if ($t->useasexample && $t->display === 'SHOW') {
                $code = '';
                if (trim($t->testcode) !== '') { $code .= "run: " . $t->testcode . "\n"; }
                if (trim($t->stdin) !== '') { $code .= "stdin:\n" . $t->stdin . "\n"; }
                $code .= "-> expected output:\n" . $t->expected;
                $body .= "<p class=\"cr-label\">Example test (provided):</p>\n<pre class=\"code\">" . esc($code) . "</pre>\n";
            }
        }
    }
    // Compute dynamic values BEFORE the heredoc (avoids the heredoc PHP trap).
    $stem_html = preg_replace('/\\[\\[\\d+\\]\\]/', '<span class="blank"></span>', fmt($r->questiontext, $r->questiontextformat));
    $qhtml .= <<<HTML
  <section class="que {$r->qtype}">
    <div class="qheader">
      <span class="qnum">Question {$n}</span>
      <span class="qmark">{$r->defaultmark} mark</span>
    </div>
    <div class="qstem">{$stem_html}</div>
    <div class="qcontent">
{$body}    </div>
    <div class="workbox"><span>Your working / answer:</span></div>
  </section>

HTML;
}

$total = count($rows);
$html = <<<HTML
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CS2310_25a iRAT 1 — Preview</title>
<style>
  @page { size: A4; margin: 16mm 14mm; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color:#1a1a1a; margin:0; }
  .toolbar { position: sticky; top:0; background:#fff; border-bottom:1px solid #ddd; padding:8px 14px; z-index:99; }
  .toolbar button { font-size:14px; padding:8px 16px; background:#0a58ca; color:#fff; border:0; border-radius:4px; cursor:pointer; }
  .cover { text-align:center; padding:40px 0 20px; }
  .cover h1 { font-size:30px; margin:0 0 6px; }
  .cover .sub { font-size:15px; color:#444; }
  .cover .meta { font-size:13px; color:#666; margin-top:10px; }
  .que { border:1px solid #d9d9d9; border-radius:6px; padding:12px 14px 14px; margin:14px 0; page-break-inside: avoid; }
  .qheader { display:flex; align-items:baseline; gap:10px; border-bottom:2px solid #0a58ca; padding-bottom:6px; margin-bottom:8px; }
  .qnum { font-weight:700; font-size:15px; color:#0a58ca; }
  .qmark { font-size:12px; color:#777; }
  .qstem { font-size:13.5px; line-height:1.5; margin-bottom:8px; }
  .qstem > p:first-child, .qcontent p:first-child { margin-top:0; }
  .qstem > p:last-child, .qcontent p:last-child { margin-bottom:0; }
  .qstem p, .qcontent p { margin:0 0 6px; line-height:1.5; }
  .qstem code, .qcontent code { background:#eef1f4; padding:1px 4px; border-radius:3px; font-family:"Courier New",monospace; font-size:0.92em; white-space:pre-wrap; word-break:break-word; }
  .qstem ul, .qstem ol, .qcontent ul, .qcontent ol { margin:4px 0 6px; padding-left:22px; }
  .qstem li, .qcontent li { margin:2px 0; }
  .qcontent { font-size:13px; }
  .opt { padding:4px 0; line-height:1.45; }
  .opt p { display:inline; margin:0; }
  .opt .lbl { font-weight:700; margin-right:6px; }
  .orderlist { margin:4px 0; }
  .orderlist li { padding:4px 0; }
  .orderlist li p { display:inline; margin:0; }
  .hint { font-style:italic; color:#666; font-size:12px; margin:6px 0; }
  .tiles { margin:6px 0 4px; line-height:2.1; }
  .tile { display:inline-block; border:1px solid #7896c8; background:#f0f5ff; color:#16335c; border-radius:4px; padding:4px 10px; margin:3px 4px 3px 0; font-size:12.5px; white-space:nowrap; }
  .tile p { display:inline; margin:0; }
  .blank { display:inline-block; min-width:60px; border-bottom:1px solid #333; margin:0 2px; }
  pre.code { background:#f6f6f6; border:1px solid #e0e0e0; border-radius:4px; padding:10px; font-family:"Courier New",monospace; font-size:12px; white-space:pre-wrap; word-break:break-word; line-height:1.4; margin:6px 0 10px; page-break-inside:avoid; }
  .cr-label { font-weight:700; font-size:12px; color:#444; margin:10px 0 3px; }
  .workbox { margin-top:12px; border:1px dashed #bbb; border-radius:4px; height:54px; padding:6px 10px; color:#888; font-size:12px; page-break-inside:avoid; }
  @media print {
    .toolbar { display:none; }
    body { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
    .cover { page-break-after:always; }
    .que { page-break-inside:avoid; break-inside:avoid; margin:0 0 10px; }
    pre.code, .workbox, .tiles { page-break-inside:avoid; break-inside:avoid; }
  }
</style>
</head>
<body>
  <div class="toolbar"><button onclick="window.print()">Print / Save as PDF</button></div>
  <div class="cover">
    <h1>iRAT 1</h1>
    <div class="sub">{$coursefull}</div>
    <div class="meta">Individual Readiness Assurance Test &bull; {$total} questions</div>
  </div>
{$qhtml}
</body>
</html>
HTML;

$out = '/var/www/moodledata/.hermes/cron/output/irat1_cs2310_preview.html';
file_put_contents($out, $html);
echo "HTML written: $out\nQuestions: $total\n";
```

## Notes
- The toolbar is hidden under `@media print`, so the printed/saved PDF shows only the cover + questions.
- Verify the output: grep the HTML for `Answer box`, `Example test`, `class="tile"`, `#include <headerfile>` (rendered, NO backticks), and `class="blank"` (DDWTOS).
- Convert server-side with dompdf: `php /tmp/pdfgen/convert.php` (see `scripts/convert_html_to_pdf.php`).
