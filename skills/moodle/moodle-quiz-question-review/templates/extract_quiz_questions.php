<?php
/**
 * Extract a quiz's full question data to JSON for the review pipeline.
 * (Templates: /tmp/mock_midterms_data.json + /tmp/mock_cr_extra.json)
 *
 * Moodle 5.2 notes baked in (see references/moodle52-schemas.md):
 *  - quiz -> slots -> questions via mdl_question_references (itemid = slot id)
 *  - coderunner options/tests keyed by questionid; SOME questions have NO
 *    coderunner_options row (lazy/cloned) -> store null, don't error
 *  - MCQ/match/ordering CHOICES live in mdl_question_answers (column `question`)
 *  - qtype_match subquestions: mdl_qtype_match_subquestions.questiontext = the
 *    item, .answertext = the correct-answer reference (string)
 *  - ordering correct order: mdl_question_answers.fraction = position (1..N)
 *
 * Usage: edit $quizdefs below, then
 *   cd /var/www/moodledata/.hermes && timeout 120 php -d display_errors=1 /tmp/extract_quiz_questions.php
 */
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php'); require_once('/var/www/html/public/lib/setup.php');
global $DB;

// ===== EDIT ME: quizid => label (course 3 = cs1302a_26a on this box) =====
$quizdefs = [
    47 => 'Midterm', 48 => 'Midterm (makeup)',
    49 => 'Mock Midterm (25A)', 50 => 'Mock Midterm (24A)', 51 => 'Mock Midterm (23A)',
    52 => 'Mock Midterm (22A)', 53 => 'Mock Midterm (21A)', 54 => 'Mock Midterm (20A)',
    75 => 'Mock Midterm (25B)',
];

$out = [];
foreach ($quizdefs as $qid => $qname) {
    $slots = $DB->get_records_sql("
        SELECT s.id AS slotid, s.slot, s.maxmark, s.page,
               qv.questionid, q.name, q.qtype, q.questiontext, q.questiontextformat, q.generalfeedback
        FROM {quiz_slots} s
        JOIN {question_references} qr ON qr.itemid = s.id AND qr.component='mod_quiz'
        JOIN {question_versions} qv ON qv.questionbankentryid = qr.questionbankentryid
        JOIN {question} q ON q.id = qv.questionid
        WHERE s.quizid = $qid
        ORDER BY s.slot");
    foreach ($slots as $s) {
        $row = [
            'slot' => (int)$s->slot, 'maxmark' => (float)$s->maxmark, 'page' => (int)$s->page,
            'qid' => (int)$s->questionid, 'name' => $s->name, 'qtype' => $s->qtype,
            'questiontext' => $s->questiontext, 'generalfeedback' => $s->generalfeedback,
            'tests' => [], 'coderunner' => null, 'answers' => [], 'hints' => [],
        ];
        // choices/keys for MCQ / match / ordering (5.2: all in question_answers)
        foreach ($DB->get_records('question_answers', ['question' => $s->questionid], 'id ASC') as $a) {
            $row['answers'][] = ['id' => (int)$a->id, 'answer' => $a->answer,
                                 'fraction' => (float)$a->fraction, 'feedback' => $a->feedback];
        }
        if ($s->qtype === 'coderunner') {
            $cr = $DB->get_record('question_coderunner_options', ['questionid' => $s->questionid]);
            if ($cr) {
                $row['coderunner'] = [
                    'language' => $cr->language, 'answer' => $cr->answer,
                    'answerpreload' => $cr->answerpreload, 'globalextra' => $cr->globalextra,
                    'precheck' => (int)$cr->precheck,
                    // execution-shape flags (see templates/run_model_answers.py):
                    'iscombinatortemplate' => (int)$cr->iscombinatortemplate,
                    'extractcodefromjson' => (int)$cr->extractcodefromjson,
                    'twigall' => (int)$cr->twigall,
                    'templateparams' => $cr->templateparams,
                    'templateparamslang' => $cr->templateparamslang,
                    'template' => $cr->template,
                    'combinatortemplate' => $cr->combinatortemplate,
                    'uiplugin' => $cr->uiplugin,
                ];
                foreach ($DB->get_records('question_coderunner_tests', ['questionid' => $s->questionid], 'id ASC') as $t) {
                    $row['tests'][] = ['testtype' => (int)$t->testtype, 'display' => $t->display,
                        'mark' => (float)$t->mark, 'useasexample' => (int)$t->useasexample,
                        'testcode' => $t->testcode, 'stdin' => $t->stdin, 'expected' => $t->expected];
                }
            } // else: no options row (lazy/cloned question) — leave null
        }
        foreach ($DB->get_records('question_hints', ['questionid' => $s->questionid], 'hint ASC') as $h) {
            $row['hints'][] = $h->hint;
        }
        $out[] = $row;
    }
}
file_put_contents('/tmp/mock_midterms_data.json', json_encode(
    ['quizdefs' => $quizdefs, 'questions' => $out],
    JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));

// bank-entry lists for the leakage detector (detect_structure.py §4)
$bank = [];
foreach ($quizdefs as $qid => $qname) {
    $e = $DB->get_records_sql("SELECT qr.questionbankentryid
        FROM {quiz_slots} s JOIN {question_references} qr
          ON qr.itemid = s.id AND qr.component='mod_quiz'
        WHERE s.quizid = $qid AND s.maxmark > 0");
    $bank[$qid] = array_map('intval', array_column($e, 'questionbankentryid'));
}
file_put_contents('/tmp/bank_entries.json', json_encode($bank));

echo 'extracted ' . count($out) . " slots; distinct questions: "
     . count(array_unique(array_column($out, 'qid'))) . "\n";
echo 'bank entries written to /tmp/bank_entries.json\n';
