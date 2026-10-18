<?php
// Portable params (see skills/_conventions/PORTABLE.md). Override via env; defaults match a standard layout.
$WEBROOT  = getenv('MHS_WEBROOT')  ?: '/var/www/html/public';
$DATA_DIR = getenv('MHS_DATA_DIR') ?: '/var/www/moodledata';

// extract_quiz.php — Step 0 + Step 1 of the moodle-quiz-question-review skill.
//
// Usage:  php extract_quiz.php <quizid> <outtag>
//   e.g.  php extract_quiz.php 59 eq2     -> writes /tmp/eq2_data.json
//
// What it does:
//   1. Resolves every slot to its DEPLOYED question version (pinned if
//      question_references.version is set, else MAX(version) for the entry) —
//      the "§0" step that prevents the #1 false-bug (auditing a retired
//      version). Row count MUST equal the number of quiz_slots (1:1); if it
//      doesn't, the version filter is wrong.
//   2. Extracts full question data to <outtag>_data.json: question text,
//      coderunner options (answer/preload/globalextra/code/extractcodefromjson/
//      iscombinatortemplate/twigall/templateparamslang/templateparamsevald),
//      every test (display/mark/testtype/testcode/stdin/expected), and for
//      MCQ the mdl_question_answers rows (answer/fraction/feedback).
//   3. Runs a hidden-Unicode scan (ZWSP/NBSP/ZWNJ/ZWJ) over all deployed
//      text/options/answers/tests.
//
// Feed the resulting JSON to templates/run_model_answers.py and
// templates/verify_mcq_keys.py.
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require($WEBROOT.'/config.php'); require_once($WEBROOT.'/lib/setup.php');
global $DB;
$qid = (int)$argv[1]; $tag = $argv[2];

// §0: resolve each slot to its DEPLOYED version (pinned or follow-latest MAX).
$map = $DB->get_recordset_sql("SELECT s.slot, s.maxmark, s.page, qv.version AS dver, qv.questionid, q.name, q.qtype
    FROM {quiz_slots} s
    JOIN {question_references} qr ON qr.itemid=s.id AND qr.component='mod_quiz'
    JOIN {question_versions} qv ON qv.questionbankentryid=qr.questionbankentryid
      AND qv.version = COALESCE(qr.version, (SELECT MAX(version) FROM {question_versions} WHERE questionbankentryid=qr.questionbankentryid))
    JOIN {question} q ON q.id=qv.questionid
    WHERE s.quizid=$qid ORDER BY s.slot, s.page, qv.questionid");
$slotmap=[]; $qids=[];
foreach($map as $r){
    $slotmap[]=['slot'=>(int)$r->slot,'page'=>(int)$r->page,'mark'=>(float)$r->maxmark,'dver'=>(int)$r->dver,'qid'=>(int)$r->questionid,'name'=>$r->name,'qtype'=>$r->qtype];
    $qids[(int)$r->questionid]=(int)$r->questionid;
}
$map->close();
echo "quiz $qid ($tag): slot rows: ".count($slotmap)."  unique deployed questions: ".count($qids)."\n";
foreach($slotmap as $sm) printf("  slot %2d page %d mark %5.1f  v%d  qid %d  %s  [%s]\n", $sm['slot'],$sm['page'],$sm['mark'],$sm['dver'],$sm['qid'],substr($sm['name'],0,40),$sm['qtype']);

$out=[];
foreach($qids as $qdv){
    $s=$DB->get_record_sql("SELECT q.id, q.name, q.qtype, q.questiontext, q.generalfeedback FROM {question} q WHERE q.id=$qdv");
    $row=['qid'=>$s->id,'name'=>$s->name,'qtype'=>$s->qtype,'questiontext'=>$s->questiontext,'generalfeedback'=>$s->generalfeedback];
    if($s->qtype==='multichoice'){
        $ans=$DB->get_records('question_answers',['question'=>$s->id],'id ASC');
        $opts=[]; $nfull=0;
        foreach($ans as $a){ $opts[]=['answer'=>$a->answer,'fraction'=>(float)$a->fraction,'feedback'=>$a->feedback]; if((float)$a->fraction>=0.9999)$nfull++; }
        $row['options']=$opts; $row['n_options']=count($opts); $row['n_full']=$nfull;
    } elseif($s->qtype==='coderunner'){
        $cr=$DB->get_record('question_coderunner_options',['questionid'=>$s->id]);
        if($cr) $row['coderunner']=['answer'=>$cr->answer,'answerpreload'=>$cr->answerpreload,'globalextra'=>$cr->globalextra,'code'=>$cr->code,
            'extractcodefromjson'=>$cr->extractcodefromjson,'iscombinatortemplate'=>$cr->iscombinatortemplate,
            'twigall'=>$cr->twigall,'templateparamslang'=>$cr->templateparamslang,'templateparamsevald'=>$cr->templateparamsevald];
        else $row['MISSING_cr']=true;
        $row['tests']=[];
        foreach($DB->get_records('question_coderunner_tests',['questionid'=>$s->id],'id ASC') as $t)
            $row['tests'][]=['display'=>$t->display,'mark'=>(float)$t->mark,'testtype'=>$t->testtype,'testcode'=>$t->testcode,'stdin'=>$t->stdin,'expected'=>$t->expected];
    } elseif(in_array($s->qtype,['essay','description'])){
        $row['note']='manual type (no auto-check)';
    }
    $out[]=$row;
}
file_put_contents("/tmp/{$tag}_data.json", json_encode(['quizid'=>$qid,'slotmap'=>$slotmap,'questions'=>$out], JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_PRETTY_PRINT));

// Hidden-Unicode scan over deployed text/options/answers/tests.
$ZWSP="\xE2\x80\x8B"; $NBSP="\xC2\xA0"; $ZWNJ="\xE2\x80\x8C"; $ZWJ="\xE2\x80\x8D";
echo "--- hidden char scan (deployed text/options/answer/tests) ---\n"; $found=false;
foreach($out as $r){
    $blob=$r['questiontext']."\n".$r['generalfeedback'];
    if($r['qtype']==='multichoice'&&isset($r['options'])){ foreach($r['options'] as $o) $blob.="\n".$o['answer']."\n".$o['feedback']; }
    if($r['qtype']==='coderunner'){ if(isset($r['coderunner'])) $blob.="\n".$r['coderunner']['answer']."\n".($r['coderunner']['globalextra']??''); foreach($r['tests'] as $t) $blob.="\n".$t['testcode']."\n".$t['stdin']."\n".$t['expected']; }
    foreach(['ZWSP'=>$ZWSP,'NBSP'=>$NBSP,'ZWNJ'=>$ZWNJ,'ZWJ'=>$ZWJ] as $n=>$c){ $cnt=substr_count($blob,$c); if($cnt){printf("  qid %d (%s): %s x%d\n",$r['qid'],$r['name'],$n,$cnt);$found=true;} }
}
if(!$found) echo "  none found\n";
echo "wrote /tmp/{$tag}_data.json\n";
