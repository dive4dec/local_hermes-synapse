# Verified XML-import creation run (2026-10-22)

Created **category `<cat-new>` (ref 668) `<coursecode> Exam 26/27 Sem A`** (parent top=`<top-cat>`, ctx `<ctx-main>`, sortorder 999) + **question `<q-new>` (ref 12797) `count_vowels`** (entry ref 6586, v1 ready, cat `<cat-new>`) — zero corruption. Read-back DB rows were byte-identical in shape to the reference q4072.

## Bootstrap (works)

```php
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('<webroot>/config.php'); require_once('<webroot>/lib/setup.php');
require_once('<webroot>/question/format.php');
require_once('<webroot>/question/format/xml/format.php');
require_once('<webroot>/question/engine/bank.php');
require_once('<webroot>/lib/questionlib.php');
global $DB, $USER, $COURSE;
$USER = $DB->get_record('user', ['id' => <author-uid>]);   // bank author (ref 3; NOT <other-uid>/494, the LTI duplicate)
$COURSE = get_course(<cid>);
$context = context_module::instance(<qbank-cmid>);          // course <cid> qbank activity (ctx <ctx-main>)
$contexts = new core_question\local\bank\question_edit_contexts($context);
```

## Stage 1 — parse-only (NO DB writes; always run this first)

```php
$qformat = new qformat_xml();   // setters as in Stage 2
$lines = file('/tmp/newq.xml');
$questions = $qformat->readquestions($lines);   // false => parse error; else stdClass[]
// category obj: $qo->qtype='category', $qo->category = the path string
// question obj: $qo->name, ->coderunnertype, ->precheck, ->answerpreload, ->answer, ->testcases[] (testcode/stdin/expected/display/useasexample/mark)
// assert: count($questions)===2, errors===$qformat->importerrors===0, fields match intent
```

## Stage 2 — real import (mirrors question/bank/importquestions/import.php)

```php
$category = question_get_top_category($context->id, true);  // "current cat"; catfromfile switch line overrides it
$qformat->setCategory($category);
$qformat->setContexts($contexts);
$qformat->setCourse($COURSE);
$qformat->setFilename('/tmp/newq.xml'); $qformat->setRealfilename('newq.xml');
$qformat->setMatchgrades(2);
$qformat->setCatfromfile(true);          // <- the category line creates the new category
$qformat->setContextfromfile(false);
$qformat->setStoponerror(true);
$qformat->set_display_progress(false);
$qformat->importpreprocess(); $qformat->importprocess(); $qformat->importpostprocess();
// success: $qformat->category = the NEW category row (id + name); $qformat->questionids = created question ids
```

Take `MAX(id)` snapshots of `question_categories/question_bank_entries/question_versions/question/question_coderunner_options/question_coderunner_tests` before Stage 2 for rollback.

## Full worked XML (verbatim, produced the verified result)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<quiz>
  <question type="category">
    <category>
      <text><coursecode> Exam 26//27 Sem A</text>   <!-- literal / MUST be // (split_category_path cleans it back) -->
    </category>
  </question>
  <question type="coderunner">
    <name><text>count_vowels</text></name>
    <questiontext format="markdown"><text>Write a function `count_vowels(s)` that returns the number of vowels …</text></questiontext>
    <generalfeedback format="markdown"><text></text></generalfeedback>
    <defaultgrade>1.0000000</defaultgrade>
    <penalty>0.0000000</penalty>
    <hidden>0</hidden>
    <idnumber></idnumber>
    <!-- EVERY option field set explicitly — see wrong-defaults warning below -->
    <coderunnertype>python3_<coursecode>_prototype</coderunnertype>
    <prototypetype>0</prototypetype>
    <allornothing>0</allornothing>
    <penaltyregime>10, 20, ...</penaltyregime>
    <precheck>2</precheck>
    <hidecheck>0</hidecheck>
    <showsource>0</showsource>
    <answerboxlines>18</answerboxlines>
    <answerboxcolumns>100</answerboxcolumns>
    <answerpreload># YOUR CODE HERE</answerpreload>
    <globalextra></globalextra>
    <answer>def count_vowels(s):
    return sum(1 for c in s.lower() if c in "aeiou")</answer>
    <validateonsave>1</validateonsave>
    <templateparams></templateparams>
    <hoisttemplateparams>1</hoisttemplateparams>
    <extractcodefromjson>1</extractcodefromjson>
    <templateparamslang>None</templateparamslang>
    <templateparamsevalpertry>0</templateparamsevalpertry>
    <templateparamsevald>{}</templateparamsevald>
    <twigall>0</twigall>
    <uiparameters></uiparameters>
    <attachments>0</attachments>
    <attachmentsrequired>0</attachmentsrequired>
    <maxfilesize>10240</maxfilesize>
    <filenamesregex></filenamesregex>
    <filenamesexplain></filenamesexplain>
    <displayfeedback>1</displayfeedback>
    <giveupallowed>0</giveupallowed>
    <testcases>
      <testcase testtype="0" useasexample="1" hiderestiffail="0" mark="1.0000000">
        <testcode><text>assert count_vowels("hello") == 2</text></testcode>
        <stdin><text></text></stdin>
        <expected><text></text></expected>
        <extra><text></text></extra>
        <display><text>SHOW</text></display>
      </testcase>
      <testcase testtype="0" useasexample="0" hiderestiffail="0" mark="1.0000000">
        <testcode><text>assert count_vowels("AEIOU") == 5</text></testcode>
        <stdin><text></text></stdin>
        <expected><text></text></expected>
        <extra><text></text></extra>
        <display><text>SHOW</text></display>
      </testcase>
      <testcase testtype="0" useasexample="0" hiderestiffail="0" mark="1.0000000">
        <testcode><text>assert count_vowels("rhythm") == 0</text></testcode>
        <stdin><text></text></stdin>
        <expected><text></text></expected>
        <extra><text></text></extra>
        <display><text>HIDE</text></display>
      </testcase>
    </testcases>
  </question>
</quiz>
```

## Import field contract (coderunner questiontype.php import_from_xml)

- Each option field is read via `getpath($data, ['#', FIELD, 0, '#'], $default)` — i.e. XML shape is `<field><text>value</text></field>` (or bare text). A **missing/empty** field falls back to the import's `$newdefaults`, which do **NOT** match this course's convention: allornothing=1 (course: 0), precheck=0 (course: 2), answerboxlines=15 (course: 18), answerboxcolumns=90 (course: 100), useace=1 (harmless), templateparamslang=twig (course: None). => **always write every field explicitly.**
- `template`, `iscombinatortemplate`, `grader`, `sandbox`, `language`, `acelang`, `cputimelimitsecs`, `memlimitmb` etc. are NOT in `$newdefaults` (default `''` → stored empty/NULL) and are inheritable — leave them OUT of the XML entirely (they inherit from the prototype; the reference row has them NULL).
- Testcase XML needs all of: `<testcode><text>…</text></testcode>`, `<stdin>`, `<expected>`, `<extra>`, `<display>` (importer requires these nodes to exist; empty `<text></text>` is fine), attrs `testtype`, `useasexample`, `hiderestiffail`, `mark`.
- `answer` (model solution) may contain newlines verbatim inside the element (no `<text>` wrapper needed — `getpath` reads `['#'][0]['#']` which handles it; the working template above used bare text).

## Post-import verification (run after every creation)

1. Read back: `question_categories` (name/parent=`<top-cat>`/contextid=`<ctx-main>`/sortorder), `question_versions`+`question_bank_entries` (v1 ready, nextversion=2), `question` (name/qtype/defaultmark/format), `question_coderunner_options` (diff non-null values against reference), `question_coderunner_tests` (testcode/display/useasexample/mark).
2. Sanity-check the test expectations with real Python (venv) BEFORE importing — expected values must be verified, not guessed.
3. `cd <webroot> && moosh -n cache-clear`.
4. Definitive functional test = bank UI **Check** button (CLI `grade_response()` cannot — see SKILL.md pitfalls). If Check shows a failure, fix in place (appends v2; v1 stays as history).
