<?php
define('CLI_SCRIPT', TRUE);
require_once('/var/www/html/public/config.php');
require_once($CFG->libdir . '/tcpdf/tcpdf.php');
global $DB;

$quizid = 142; // iRAT1 in cs2310_25a

// Fetch questions (Moodle 5.x join: quiz_slots -> question_references(area='slot') -> qbank_entries -> q_versions -> question)
$sql = "SELECT qs.slot,
               q.id AS questionid, q.name, q.qtype, q.questiontext, q.questiontextformat, q.defaultmark, qbe.id AS entryid
          FROM mdl_quiz_slots qs
          JOIN mdl_question_references qr
            ON qr.itemid = qs.id AND qr.component='mod_quiz' AND qr.questionarea='slot'
          JOIN mdl_question_bank_entries qbe ON qbe.id = qr.questionbankentryid
          JOIN mdl_question_versions qv
            ON qv.questionbankentryid = qbe.id
           AND qv.version = (SELECT MAX(version) FROM mdl_question_versions v2 WHERE v2.questionbankentryid = qbe.id)
          JOIN mdl_question q ON q.id = qv.questionid
         WHERE qs.quizid = ?
      ORDER BY qs.slot";
$questions = $DB->get_records_sql($sql, array($quizid));

$quiz = $DB->get_record('quiz', array('id' => $quizid), 'id, name, course');
$course = $DB->get_record('course', array('id' => $quiz->course), 'id, fullname, shortname');

// Render stored text (HTML/Markdown/MOODLE) to clean HTML via Moodle.
require_once($CFG->libdir . '/weblib.php');
function irat_format($raw, $format) {
    return format_text($raw, $format, ['noclean' => true, 'filter' => false]);
}
// Plain-text version (for code contexts / working boxes): markdown-render THEN strip
function irat_text($raw, $format) {
    $h = irat_format($raw, $format);
    $h = preg_replace('/<br\s*\/?>/i', "\n", $h);
    $h = preg_replace('/<\/p>/i', "\n\n", $h);
    $h = strip_tags($h);
    $h = html_entity_decode($h, ENT_QUOTES | ENT_HTML5);
    $h = preg_replace('/\n{3,}/', "\n\n", $h);
    return trim($h);
}

function irat_codebox($pdf, $code, $title='') {
    if ($title !== '') {
        $pdf->SetFont('helvetica', 'B', 9);
        $pdf->SetTextColor(60,60,60);
        $pdf->Cell(0, 5, $title, 0, 1, 'L');
    }
    $pdf->SetFont('courier', '', 9);
    $pdf->SetFillColor(245, 245, 245);
    $pdf->SetDrawColor(180, 180, 180);
    // Single MultiCell = proper wrapping + full-height bordered box (no clipping)
    $pdf->MultiCell(180, 4.8, $code, 1, 'L', true, 1);
    $pdf->Ln(2);
}

function irat_drag_tiles($pdf, $items) {
    $pdf->SetFont('helvetica', '', 10);
    $pdf->SetFillColor(240, 245, 255);
    $pdf->SetDrawColor(120, 150, 200);
    $left = 18; $right = 192; $h = 7;
    $x = $left; $y = $pdf->GetY();
    $pdf->SetXY($x, $y);
    foreach ($items as $it) {
        $tw = $pdf->GetStringWidth($it) + 10;
        if ($x + $tw > $right) { $x = $left; $y += $h + 2; $pdf->SetXY($x, $y); }
        $pdf->Cell($tw, $h, $it, 1, 0, 'C', true);
        $x += $tw + 3;
        $pdf->SetX($x);
    }
    $pdf->SetY($y + $h + 4);
}

class IRAT_PDF extends TCPDF {
    public function Footer() {
        $this->SetY(-12);
        $this->SetFont('helvetica', 'I', 8);
        $this->SetTextColor(120);
        $this->Cell(0, 8, 'iRAT1  |  Page ' . $this->getAliasNumPage() . '/' . $this->getAliasNbPages(), 0, 0, 'C');
    }
}

$pdf = new IRAT_PDF('P', 'mm', 'A4', true, 'UTF-8', false);
$pdf->SetCreator('Hermes Agent');
$pdf->SetTitle('iRAT1 - CS2310');
$pdf->setPrintHeader(false);
$pdf->SetMargins(18, 16, 18);
$pdf->SetAutoPageBreak(true, 16);
$pdf->AddPage();

$pdf->SetFillColor(31, 73, 125);
$pdf->SetTextColor(255);
$pdf->SetFont('helvetica', 'B', 16);
$pdf->Cell(0, 11, '  iRAT 1  -  Individual Readiness Assurance Test', 0, 1, 'L', true);
$pdf->SetTextColor(60);
$pdf->SetFont('helvetica', '', 10);
$pdf->Ln(2);
$pdf->Cell(0, 6, $course->fullname . '  (' . $course->shortname . ')', 0, 1, 'L');
$pdf->Cell(0, 6, 'Quiz: ' . $quiz->name . '   |   Questions: ' . count($questions), 0, 1, 'L');
$pdf->Ln(3);
$pdf->SetDrawColor(180);
$pdf->Line(18, $pdf->GetY(), 192, $pdf->GetY());
$pdf->Ln(4);

$qnum = 1;
foreach ($questions as $q) {
    $pdf->SetFont('helvetica', 'B', 11);
    $pdf->SetTextColor(20);
    $label = $qnum . '.  ' . irat_text($q->name, 0) . '   [' . strtoupper($q->qtype) . ', ' . number_format($q->defaultmark, 0) . ' mark]';
    $pdf->MultiCell(0, 6, $label, 0, 'L');
    $pdf->Ln(0.5);
    $pdf->SetFont('helvetica', '', 10);
    $pdf->SetTextColor(40);
    $pdf->writeHTML(irat_format($q->questiontext, $q->questiontextformat), true, false, true, false, 'L');
    $pdf->Ln(1);

    if ($q->qtype === 'multichoice') {
        $o = $DB->get_record('qtype_multichoice_options', array('questionid' => $q->questionid), 'single');
        $single = $o ? (int)$o->single : 1;
        $pdf->SetFont('helvetica', 'I', 9);
        $pdf->SetTextColor(90);
        $pdf->MultiCell(0, 5, '(Select ' . ($single ? 'ONE' : 'ALL that apply') . ' correct answer.)', 0, 'L');
        $answers = $DB->get_records('question_answers', array('question' => $q->questionid), 'id', 'id, answer');
        $letters = range('A', 'Z');
        $i = 0;
        foreach ($answers as $a) {
            $pdf->SetFont('helvetica', '', 9.5);
            $pdf->SetTextColor(40);
            $pdf->Cell(6, 5, $letters[$i] . ')', 0, 0);
            $pdf->writeHTML(irat_format($a->answer, $a->answerformat), true, false, true, false, 'L');
            $i++;
        }
    } elseif ($q->qtype === 'ordering') {
        $pdf->SetFont('helvetica', 'I', 9); $pdf->SetTextColor(90);
        $pdf->MultiCell(0, 5, '(Arrange the items in the correct order.)', 0, 'L');
        $ans = $DB->get_records('question_answers', array('question' => $q->questionid), 'fraction', 'id, answer, answerformat');
        $i = 1;
        foreach ($ans as $a) {
            $pdf->SetFont('helvetica', '', 9.5); $pdf->SetTextColor(40);
            $pdf->Cell(8, 5, '(' . $i . ')', 0, 0);
            $pdf->writeHTML(irat_format($a->answer, $a->answerformat), true, false, true, false, 'L');
            $i++;
        }
    } elseif ($q->qtype === 'ddwtos') {
        $ans = $DB->get_records('question_answers', array('question' => $q->questionid), 'id', 'id, answer, answerformat');
        $opts = array();
        foreach ($ans as $a) { $opts[] = irat_text($a->answer, $a->answerformat); }
        $pdf->SetFont('helvetica', 'B', 9); $pdf->SetTextColor(60);
        $pdf->Cell(0, 5, 'Drag the correct term into each blank:', 0, 1, 'L');
        irat_drag_tiles($pdf, $opts);
    } elseif ($q->qtype === 'coderunner') {
        $opt = $DB->get_record('question_coderunner_options', array('questionid' => $q->questionid), 'answerpreload, answer');
        if ($opt && !empty($opt->answerpreload)) {
            irat_codebox($pdf, $opt->answerpreload, 'Answer box (pre-filled - fix the bugs):');
        }
        $tests = $DB->get_records('question_coderunner_tests', array('questionid' => $q->questionid), 'id', 'id, testcode, stdin, expected, useasexample, display');
        foreach ($tests as $t) {
            if ($t->useasexample && $t->display === 'SHOW') {
                $code = '';
                if (trim($t->testcode) !== '') { $code .= "run: " . $t->testcode . "\n"; }
                if (trim($t->stdin) !== '') { $code .= "stdin:\n" . $t->stdin . "\n"; }
                $code .= "-> expected output:\n" . $t->expected;
                irat_codebox($pdf, $code, 'Example test (provided):');
            }
        }
    }

    $pdf->Ln(1);
    $y0 = $pdf->GetY();
    $pdf->Rect(18, $y0, 174, 14, 'D');
    $pdf->SetXY(20, $y0 + 2);
    $pdf->SetFont('helvetica', 'I', 8);
    $pdf->SetTextColor(160);
    $pdf->Cell(0, 4, 'Answer / working:', 0, 0);
    $pdf->SetY($y0 + 14);
    $pdf->Ln(4);
    $qnum++;
}

$out = '/var/www/moodledata/.hermes/cron/output/irat1_cs2310.pdf';
$pdf->Output($out, 'F');
echo "PDF created: $out (" . filesize($out) . " bytes)\n";
