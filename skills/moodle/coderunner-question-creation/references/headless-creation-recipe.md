# Headless creation recipe — categories + Code Runner questions (this build)

Status note (2026-10-22, updated): the **hand-authored XML import** (Path A, section 1) was run END-TO-END and verified — see **references/xml-import-recipe.md** for the full working run, template, and field contract. The export half of the original "export → modify → import" idea is **not viable on this fork** (exporter bugs: cattofile dummy-question crash, setQuestions needs row objects, bare-row export empties all option fields + testcases) — dump the live question's DB rows and author the XML by hand instead. The `$USER = <other-uid>` line below is also superseded: use **`<author-uid>`** (the bank-author account). Section 2 (save_question) and section 3 (stored shape) remain valid and were used for cross-checking.

## 0. CLI bootstrap (required — none of this autoloads)

```php
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('<webroot>/config.php');
require_once('<webroot>/lib/setup.php');
require_once('<webroot>/lib/questionlib.php');            // get_question, get_question_bank_entry
require_once('<webroot>/question/engine/bank.php');       // question_bank (global class)
require_once('<webroot>/question/format.php');            // qformat_default
require_once('<webroot>/question/format/xml/format.php'); // qformat_xml
global $DB, $USER, $COURSE;
$USER = $DB->get_record('user', ['id' => <author-uid>]);   // bank author (ref 3; NOT the LTI dup <other-uid>/494)
$COURSE = get_course(<cid>);
```

Pitfalls hit while assembling this:
- `question_contextlist` does NOT exist in this build → use `core_question\local\bank\question_edit_contexts($context)`.
- `SQL_MUST_EXIST` constant is undefined.
- `get_question()` lives in `lib/questionlib.php`, not in `lib/setup.php`.
- Set `$USER`/`$COURSE` manually in CLI scripts.

## 1. Path A (preferred): qformat_xml export → modify → import

Export the mimic-source (verified class/method names against source; not yet run):
```php
$contexts = new core_question\local\bank\question_edit_contexts(context_module::instance(<qbank-cmid>)); // qbank cm
$qformat = new qformat_xml();
$qformat->setCourse($COURSE);
$qformat->setContexts($contexts);
$qformat->set_display_progress(false);
$qformat->setQuestions([<mimic-qid>]);          // live Sem B question to mimic (ref 4072)
$qformat->setFilename('/tmp/cref.xml');
$qformat->setRealfilename('cref.xml');
$qformat->setMatchgrades(2);
$qformat->setStoponerror(true);
$qformat->exportprocess(false);
```

Import the modified XML (exact sequence from `question/bank/importquestions/import.php` L103–137):
```php
$qformat = new qformat_xml();
$qformat->setCategory($category);      // target category record
$qformat->setContexts($contexts);
$qformat->setCourse($COURSE);
$qformat->setFilename('/tmp/newq.xml');
$qformat->setRealfilename('newq.xml');
$qformat->setMatchgrades(2);
$qformat->setCatfromfile(true);        // read <category>top/…</category> from the XML
$qformat->setContextfromfile(false);
$qformat->setStoponerror(true);
$qformat->importpreprocess();
$qformat->importprocess();
$qformat->importpostprocess();
// then: optional questions_imported event; moosh -n cache-clear
```

Category auto-creation: with `catfromfile` on and `<category>top/<coursecode> Exam 26/27 Sem A</category>` in the XML, `create_category_path()` (question/format.php ~L600–682) walks/creates each level under the bank's `top` category (course `<cid>`: top-cat `<top-cat>`, ctx `<ctx-main>` (ref 179 / 609)) — insert with `sortorder=999`, `stamp=make_unique_id_code()`, requires `moodle/question:managecategory`, fires `question_category_created`. Existing categories are reused, not duplicated.

Each imported question then goes through the canonical insert (format.php L416–536): insert `question` → insert `question_bank_entries` (`questioncategoryid`, `idnumber`, `ownerid`, `nextversion=2`) → insert `question_versions` (`version=1`, `status='ready'`) → `save_question_options` → `question_created` event → commit. This is why a raw `mdl_question` insert alone produces an unusable question.

## 2. Path B: save_question form flow (mirrors question/bank/editquestion/question.php L109–304)

```php
$question = new stdClass();
$question->category = $catid; $question->qtype = 'coderunner'; $question->createdby = $USER->id;
$qtypeobj = question_bank::get_qtype('coderunner');
$form = new stdClass();
$form->category = "$catid,$ctxid";   // "id,contextid" — save_question explodes this
$form->name = '…'; $form->questiontext = '…'; $form->defaultmark = 1;
$form->coderunnertype = 'python3_<coursecode>_prototype';
$form->answerpreload = '# YOUR CODE HERE'; $form->answer = '…';
// parallel arrays, one element per test case:
$form->testcode = ['print_diamond(5)'];
$form->stdin = [''];
$form->expected = ["  *\n ***\n*****\n ***\n  *\n"];
$form->display = ['SHOW']; $form->useasexample = [1]; $form->mark = ['1.000'];
$question = $qtypeobj->save_question($question, $form);
question_bank::notify_question_edited($question->id);
```

For a NEW question, `save_question` (questiontypebase.php:366) ALWAYS creates a new question row + bank entry + version v1 — there is no separate `construct()` step in this build. `save_question_options` (coderunner questiontype.php:274) writes options + testcases, and `clean_question_form` nulls inherited fields (template etc.) when `customise` is off — so do NOT manually set `template`.

## 3. Exact stored shape of the mimic target (`print_diamond` v11, cat `<cat-semB>` (ref q4072 / 167))

`mdl_question` row keys: id, parent=0, name, questiontext, questiontextformat=4, generalfeedback='', generalfeedbackformat=4, defaultmark='1.0000000', penalty='0.0000000', qtype='coderunner', length=1, stamp, timecreated, timemodified, createdby, modifiedby. **No `idnumber`/`category`/`hidden`/`version` columns on `mdl_question` in this build** (idnumber lives on `question_bank_entries`; version/hide state in `question_versions`).

`question_coderunner_options` — non-trivial values only:
- coderunnertype='python3_<coursecode>_prototype', prototypetype=0, allornothing=0, showsource=0, precheck='2', hidecheck=0
- answerboxlines=18, answerboxcolumns=100, answerpreload='# YOUR CODE HERE', globalextra=''
- penaltyregime='10, 20, ...', answer=<model solution>, validateonsave=1
- template=NULL (inherited), templateparams='', templateparamslang='None', templateparamsevald='{}'
- hoisttemplateparams=1, extractcodefromjson=1, twigall=0, uiparameters=''
- attachments=0, attachmentsrequired=0, maxfilesize='10240', displayfeedback=1, giveupallowed=0

Test rows (3; note extra columns `testtype=0`, `hiderestiffail=0`; `mark` stored as string '1.000'):
- `print_diamond(5)` — stdin empty — expected `  *\n ***\n*****\n ***\n  *\n` (trailing \n) — SHOW, useasexample=1
- `print_diamond(9)` — stdin empty — 9-line diamond + trailing \n — SHOW
- `print_diamond(13)` — stdin empty — 13-line diamond + trailing \n — HIDE

**Style nuance:** current LIVE Sem B questions use `testcode` (a function call) + `expected` (WITH trailing newline) and empty `stdin`; older rows (e.g. an older question v1) used `stdin`→expected with a full program. Both work with the prototype harness. The model `answer` is a function definition; the tests call it.

## 4. Verification checklist (after any creation)
1. Rows: new question + entry + v1 'ready'; options row matches the shape above; N test rows with testtype/hiderestiffail set.
2. Functional: run the model answer through the question engine (the Check path) against ALL tests — expect full marks. If the Jobe engine is unavailable, say so; never fake the result.
3. Render: visible in bank UI `/question/edit.php?cat=<catid>,<ctx-main>&cmid=<qbank-cmid>`.
4. `cd <webroot> && moosh -n cache-clear`.
