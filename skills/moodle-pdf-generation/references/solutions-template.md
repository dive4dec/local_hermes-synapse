# Solutions (answer-key) quiz-sheet generator

Full working PHP CLI generator that produces a self-contained HTML **solutions**
sheet from a Moodle quiz, then converts it to PDF via dompdf. Copy and modify; set
`$quizid` to the target quiz. This is the **instructor** variant: it shows the
correct answers and ALL CodeRunner test cases (including hidden). It MAY keep the
internal `q.name` in the header (unlike the student paper, which omits it).

## Rounding (FINAL state, 2026-07-14 — user reversed an earlier 2-dp attempt)
- PERCENTAGES next to correct answers = **integer**: `number_format((float)$a->fraction * 100, 0) . '%'` (e.g. `50%`, `100%`).
- TEST-CASE `Mark` column = **3 decimals**: `number_format((float)$t->mark, 3)` (e.g. `1.000`).
- QUESTION HEADER `defaultmark` = **raw DB value** `{$r->defaultmark} mark` (e.g. `1.0000000`). Do NOT reformat it — a 2-dp attempt inside the heredoc produced a fatal "marks not working" bug (see SKILL.md Pitfalls: ⚠️ Heredoc PHP trap).

## Prereqs
- Run from a dir that can `require_once('/var/www/html/public/config.php')` (web root is `/var/www/html/public`).
- `format_text()` needs `$CFG->libdir . '/weblib.php'`.
- Convert with dompdf: `php /tmp/pdfgen/convert_solutions.php` (one-time `composer require dompdf/dompdf` in its dir).

## Generator (`gen_solutions.php`)

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
function fmt($raw, $format) { return latex_to_html(format_text($raw, $format, ['noclean' => true, 'filter' => false])); }

/**
 * Convert LaTeX math delimiters to HTML/Unicode for dompdf (which cannot
 * run JavaScript/MathJax).  Handles:
 *   \( ... \)  (inline math)
 *   $$ ... $$  (display math, centered)
 *
 * NOTE: format_text() with filter=false HTML-escapes backslashes to &#92;
 * and asterisks to &#42;.  We decode those entities BEFORE matching LaTeX
 * delimiters, otherwise \( becomes &#92;( and won't match.
 *
 * CSS MUST use font-family: "DejaVu Sans" — dompdf bundles this TTF and
 * it supports Unicode math glyphs (π, ≤, ≥, ⋯, etc.).  Helvetica fallback
 * shows ? for these characters.
 */
function latex_to_html($html) {
    // 1. Decode HTML entities that mask LaTeX delimiters
    $html = str_replace(['&#92;', '&#42;'], ['\\', '*'], $html);

    // 2. Convert display math: $$ ... $$
    $html = preg_replace_callback('/\$\$(.*?)\$\$/s', function($m) {
        return '<div style="text-align:center;margin:6px 0">' . latex_to_unicode($m[1]) . '</div>';
    }, $html);

    // 3. Convert inline math: \( ... \)
    $html = preg_replace_callback('/\\\\\((.*?)\\\\\)/s', function($m) {
        return '<span style="font-style:italic">' . latex_to_unicode($m[1]) . '</span>';
    }, $html);

    return $html;
}

/**
 * Convert common LaTeX commands to Unicode characters.
 * Handles symbols typically found in CS/math quiz questions.
 */
function latex_to_unicode($latex) {
    $latex = trim($latex);
    $replacements = [
        '/\\\\frac\{([^{}]+)\}\{([^{}]+)\}/' => '$1/$2',
        '/\\\\left\(/' => '(',
        '/\\\\right\)/' => ')',
        '/\\\\left\|/' => '|',
        '/\\\\right\|/' => '|',
        '/\\\\cdots/' => '⋯',
        '/\\\\ldots/' => '…',
        '/\\\\vdots/' => '⋮',
        '/\\\\dots/' => '…',
        '/\\\\leq/' => '≤',
        '/\\\\geq/' => '≥',
        '/\\\\neq/' => '≠',
        '/\\\\approx/' => '≈',
        '/\\\\equiv/' => '≡',
        '/\\\\pi/' => 'π',
        '/\\\\alpha/' => 'α',
        '/\\\\beta/' => 'β',
        '/\\\\gamma/' => 'γ',
        '/\\\\delta/' => 'δ',
        '/\\\\theta/' => 'θ',
        '/\\\\lambda/' => 'λ',
        '/\\\\mu/' => 'μ',
        '/\\\\sigma/' => 'σ',
        '/\\\\omega/' => 'ω',
        '/\\\\Sigma/' => 'Σ',
        '/\\\\Delta/' => 'Δ',
        '/\\\\Omega/' => 'Ω',
        '/\\\\rightarrow/' => '→',
        '/\\\\leftarrow/' => '←',
        '/\\\\Rightarrow/' => '⇒',
        '/\\\\Leftarrow/' => '⇐',
        '/\\\\mapsto/' => '↦',
        '/\\\\in/' => '∈',
        '/\\\\notin/' => '∉',
        '/\\\\subset/' => '⊂',
        '/\\\\subseteq/' => '⊆',
        '/\\\\supset/' => '⊃',
        '/\\\\cup/' => '∪',
        '/\\\\cap/' => '∩',
        '/\\\\emptyset/' => '∅',
        '/\\\\infty/' => '∞',
        '/\\\\times/' => '×',
        '/\\\\div/' => '÷',
        '/\\\\pm/' => '±',
        '/\\\\mp/' => '∓',
        '/\\\\cdot/' => '·',
        '/\\\\sum/' => '∑',
        '/\\\\prod/' => '∏',
        '/\\\\int/' => '∫',
        '/\\\\sqrt\{([^{}]+)\}/' => '√($1)',
    ];
    foreach ($replacements as $pattern => $replacement) {
        $latex = preg_replace($pattern, $replacement, $latex);
    }
    // Strip remaining backslash-letter sequences (e.g. \foo → foo)
    $latex = preg_replace('/\\\\([a-zA-Z]+)/', '$1', $latex);
    // Clean up escaped asterisks and backslashes
    $latex = str_replace(['\\*', '\\\\'], ['*', '\\'], $latex);
    return $latex;
}

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
            $correct = ((float)$a->fraction > 0);
            $cls = $correct ? 'opt correct' : 'opt';
            $tick = $correct ? '<span class="tick">&#10004;</span>' : '';
            $pct = ((float)$a->fraction != 0) ? ' <span class="frac">(' . number_format((float)$a->fraction * 100, 0) . '%)</span>' : '';
            $body .= '<div class="' . $cls . '"><span class="lbl">' . $letter[$i] . '.</span> ' . fmt($a->answer, $a->answerformat) . $tick . $pct . "</div>\n";
            $i++;
        }
    } else if ($r->qtype === 'ordering') {
        $ans = $DB->get_records('question_answers', ['question' => $r->qid], 'fraction ASC');
        $body .= '<p class="cr-label">Correct order:</p>' . "\n" . '<ol class="orderlist solution">' . "\n";
        foreach ($ans as $a) { $body .= '  <li>' . fmt($a->answer, $a->answerformat) . "</li>\n"; }
        $body .= "</ol>\n";
    } else if ($r->qtype === 'ddwtos') {
        $ans = $DB->get_records('question_answers', ['question' => $r->qid], 'id');
        $terms = [];
        foreach ($ans as $a) { $terms[] = fmt($a->answer, $a->answerformat); }
        $body .= '<p class="cr-label">Terms (id order; stem shows the blanks):</p>' . "\n" . '<ol class="orderlist solution">' . "\n";
        foreach ($terms as $t) { $body .= '  <li>' . $t . "</li>\n"; }
        $body .= "</ol>\n";
    } else if ($r->qtype === 'coderunner') {
        $opt = $DB->get_record('question_coderunner_options', ['questionid' => $r->qid]);
        if ($opt && !empty($opt->answerpreload)) {
            $body .= "<p class=\"cr-label\">Answer box (pre-filled — fix the bugs):</p>\n";
            $body .= '<pre class="code">' . esc($opt->answerpreload) . "</pre>\n";
        }
        if ($opt && trim((string)$opt->answer) !== '') { // reference solution — REAL code, do NOT format_text
            $body .= "<p class=\"cr-label sol\">Reference solution:</p>\n" . '<pre class="code solution">' . esc($opt->answer) . "</pre>\n";
        }
        $tests = $DB->get_records('question_coderunner_tests', ['questionid' => $r->qid], 'id');
        if ($tests) {
            $body .= "<p class=\"cr-label sol\">Test cases (" . count($tests) . " total — including hidden):</p>\n";
            $body .= '<table class="tests"><thead><tr><th>#</th><th>Visibility</th><th>Test code</th><th>Stdin</th><th>Expected output</th><th>Mark</th></tr></thead><tbody>' . "\n";
            $ti = 0;
            foreach ($tests as $t) {
                $ti++;
                $vis = ($t->display === 'SHOW') ? 'Shown' : 'HIDDEN';
                if ($t->useasexample) { $vis .= ' (example)'; }
                $viscls = ($t->display === 'SHOW') ? 'vshow' : 'vhide';
                $body .= '<tr class="' . $viscls . '"><td>' . $ti . '</td><td>' . esc($vis) . '</td>'
                    . '<td><pre>' . esc(trim((string)$t->testcode)) . '</pre></td>'
                    . '<td><pre>' . esc(trim((string)$t->stdin)) . '</pre></td>'
                    . '<td><pre>' . esc(rtrim((string)$t->expected)) . '</pre></td>'
                    . '<td>' . number_format((float)$t->mark, 3) . '</td></tr>' . "\n";
            }
            $body .= "</tbody></table>\n";
        }
    }
    // Compute dynamic values BEFORE the heredoc (avoids the heredoc PHP trap).
    $stem_html = preg_replace('/\[\[\d+\]\]/', '<span class="blank"></span>', fmt($r->questiontext, $r->questiontextformat));
    $name_html = fmt($r->name, 0);
    $qhtml .= <<<HTML
  <section class="que {$r->qtype}">
    <div class="qheader">
      <span class="qnum">Question {$n}</span>
      <span class="qname">{$name_html}</span>
      <span class="qmark">{$r->defaultmark} mark</span>
    </div>
    <div class="qstem">{$stem_html}</div>
    <div class="qcontent">
{$body}    </div>
  </section>

HTML;
}
$total = count($rows);
$html = <<<HTML
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CS2310_25a iRAT 1 — SOLUTIONS</title>
<style>
  @page { size: A4; margin: 16mm 14mm; }
  * { box-sizing: border-box; }
  body { font-family: "DejaVu Sans", sans-serif; color:#1a1a1a; margin:0; }
  .toolbar { position: sticky; top:0; background:#fff; border-bottom:1px solid #ddd; padding:8px 14px; z-index:99; }
  .toolbar button { font-size:14px; padding:8px 16px; background:#0a58ca; color:#fff; border:0; border-radius:4px; cursor:pointer; }
  .cover { text-align:center; padding:40px 0 20px; }
  .cover h1 { font-size:30px; margin:0 0 6px; }
  .cover .sub { font-size:15px; color:#444; }
  .cover .meta { font-size:13px; color:#666; margin-top:10px; }
  .cover .banner { display:inline-block; margin-top:14px; padding:6px 16px; background:#c0392b; color:#fff; font-weight:700; border-radius:4px; letter-spacing:1px; }
  .que { border:1px solid #d9d9d9; border-radius:6px; padding:12px 14px 14px; margin:14px 0; page-break-inside: avoid; }
  .qheader { display:flex; align-items:baseline; gap:10px; border-bottom:2px solid #0a58ca; padding-bottom:6px; margin-bottom:8px; }
  .qnum { font-weight:700; font-size:15px; color:#0a58ca; }
  .qname { font-weight:600; font-size:13px; color:#333; flex:1; }
  .qmark { font-size:12px; color:#777; }
  .qstem { font-size:13.5px; line-height:1.5; margin-bottom:8px; }
  .qstem > p:first-child, .qcontent p:first-child { margin-top:0; }
  .qstem > p:last-child, .qcontent p:last-child { margin-bottom:0; }
  .qstem p, .qcontent p { margin:0 0 6px; line-height:1.5; }
  .qstem code, .qcontent code { background:#eef1f4; padding:1px 4px; border-radius:3px; font-family:"DejaVu Sans Mono", monospace; font-size:0.92em; white-space:pre-wrap; word-break:break-word; }
  .qstem ul, .qstem ol, .qcontent ul, .qcontent ol { margin:4px 0 6px; padding-left:22px; }
  .qcontent { font-size:13px; }
  .opt { padding:4px 0; line-height:1.45; }
  .opt p { display:inline; margin:0; }
  .opt .lbl { font-weight:700; margin-right:6px; }
  .opt.correct { background:#e8f6ec; border-left:3px solid #2e9e4f; padding-left:8px; border-radius:3px; }
  .tick { color:#2e9e4f; font-weight:700; margin-left:6px; }
  .frac { color:#2e9e4f; font-size:11px; }
  .orderlist { margin:4px 0; padding-left:22px; }
  .orderlist li { padding:3px 0; }
  .orderlist li p { display:inline; margin:0; }
  .orderlist.solution li { background:#e8f6ec; border-radius:3px; padding:3px 6px; margin:2px 0; }
  .blank { display:inline-block; min-width:60px; border-bottom:1px solid #333; margin:0 2px; }
  pre.code { background:#f6f6f6; border:1px solid #e0e0e0; border-radius:4px; padding:10px; font-family:"DejaVu Sans Mono", monospace; font-size:12px; white-space:pre-wrap; word-break:break-word; line-height:1.4; margin:6px 0 10px; page-break-inside:avoid; }
  pre.code.solution { background:#f0fbf3; border-color:#a9d9b8; }
  .cr-label { font-weight:700; font-size:12px; color:#444; margin:10px 0 3px; }
  .cr-label.sol { color:#2e7d43; }
  table.tests { width:100%; border-collapse:collapse; font-size:10.5px; margin:4px 0 8px; }
  table.tests th, table.tests td { border:1px solid #ccc; padding:4px 6px; text-align:left; vertical-align:top; }
  table.tests th { background:#eef2f8; }
  table.tests pre { margin:0; font-family:"DejaVu Sans Mono", monospace; font-size:10px; white-space:pre-wrap; word-break:break-word; }
  table.tests tr.vhide { background:#fff5f5; }
  table.tests tr.vhide td:nth-child(2) { color:#c0392b; font-weight:700; }
  table.tests tr.vshow td:nth-child(2) { color:#2e7d43; font-weight:700; }
  @media print {
    .toolbar { display:none; }
    body { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
    .cover { page-break-after:always; }
    .que { page-break-inside:avoid; break-inside:avoid; margin:0 0 10px; }
    pre.code, table.tests { page-break-inside:auto; }
  }
</style>
</head>
<body>
  <div class="toolbar"><button onclick="window.print()">Print / Save as PDF</button></div>
  <div class="cover">
    <h1>iRAT 1 &mdash; Solutions</h1>
    <div class="sub">{$coursefull}</div>
    <div class="meta">Individual Readiness Assurance Test &bull; {$total} questions</div>
    <div class="banner">INSTRUCTOR COPY &mdash; CONTAINS ANSWERS &amp; HIDDEN TESTS</div>
  </div>
{$qhtml}
</body>
</html>
HTML;
$out = '/var/www/moodledata/.hermes/cron/output/irat1_cs2310_solutions.html';
file_put_contents($out, $html);
echo "HTML written: $out\nQuestions: $total\n";
```

## dompdf converter (run `composer require dompdf/dompdf` once in its dir)
```php
<?php
require_once('/tmp/pdfgen/vendor/autoload.php');
use Dompdf\Dompdf; use Dompdf\Options;
$in = $argv[1]; $out = $argv[2];
$html = file_get_contents($in);
$options = new Options();
$options->set('isRemoteEnabled', false);
$options->set('isHtml5ParserEnabled', true);
$options->set('defaultFont', 'DejaVu Sans');
$options->set('dpi', 96);
$options->set('defaultMediaType', 'print'); // applies @media print CSS
$dompdf = new Dompdf($options);
$dompdf->loadHtml($html, 'UTF-8');
$dompdf->setPaper('A4', 'portrait');
$dompdf->render();
file_put_contents($out, $dompdf->output());
```

## Verified gotchas (iRAT1, 2026-07-14)
- Q11 was **multi-answer**: two options each at `fraction=0.5` — both ticked. Code above handles this automatically.
- Q17 CodeRunner had **1 test, all SHOWN, 0 hidden** — the table still correctly says "including hidden" and would flag HIDDEN rows red if any existed.
- DDWTOS Q16 had 6 terms for 2 blanks; the serialized `options` blob would be needed for exact blank→term mapping (not done here).
- Run `head -c 8 file.pdf` and `grep -a -c "/Type /Page" file.pdf` to sanity-check the PDF.
