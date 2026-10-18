<?php
/**
 * Clone a Code Runner prototype from one course to another.
 *
 * Usage: php clone-prototype.php SOURCE_QUESTION_ID TARGET_CONTEXTID TARGET_PARENT_CAT
 *
 * Example: php clone-prototype.php 4281 609 179
 *   - Copy prototype Q4281 to cs1302a_26a (contextid=609, top category=179)
 *
 * This script correctly handles the 4-table relationship:
 *   mdl_question_categories → mdl_question_bank_entries → mdl_question_versions → mdl_question
 * With separate auto-incremented IDs for question and entry (a common mistake is forcing them equal).
 */
define('CLI_SCRIPT', true);
require_once('/var/www/html/public/config.php');

$sourceQid = (int)($argv[1] ?? 0);
$targetContextid = (int)($argv[2] ?? 0);
$targetParentCat = (int)($argv[3] ?? 0);

if (!$sourceQid || !$targetContextid || !$targetParentCat) {
    echo "Usage: php clone-prototype.php SOURCE_QUESTION_ID TARGET_CONTEXTID TARGET_PARENT_CAT\n";
    exit(1);
}

// 1. Create the target category
$cat = new stdClass();
$cat->name = 'CR_PROTOTYPES';
$cat->contextid = $targetContextid;
$cat->parent = $targetParentCat;
$cat->info = '';
$cat->infoformat = 1;
$cat->stamp = 'manual-' . time();
$cat->sortorder = 999;
$cat->idnumber = null;
$catid = $DB->insert_record('question_categories', $cat);
echo "Created category id={$catid}\n";

// 2. Clone the question
$proto = $DB->get_record('question', ['id' => $sourceQid], '*');
$q = new stdClass();
foreach ($proto as $k => $v) {
    if ($k === 'id') continue;
    $q->$k = $v;
}
$q->parent = 0;
$q->stamp = 'manual-' . time() . 'a';
$q->timecreated = time();
$q->timemodified = time();
$qid = $DB->insert_record('question', $q);
echo "Created question id={$qid}\n";

// 3. Create question_bank_entries (separate ID!)
$entry = new stdClass();
$entry->questioncategoryid = $catid;
$entry->idnumber = null;
$entry->ownerid = 2;
$entry->nextversion = 2;
$entryid = $DB->insert_record('question_bank_entries', $entry);
echo "Created entry id={$entryid}\n";

// 4. Create question_versions
$ver = new stdClass();
$ver->questionbankentryid = $entryid;
$ver->version = 1;
$ver->questionid = $qid;
$ver->status = 'ready';
$DB->insert_record('question_versions', $ver);
echo "Created version\n";

// 5. Clone coderunner_options
$opt = $DB->get_record('question_coderunner_options', ['questionid' => $sourceQid], '*');
$c = new stdClass();
foreach ($opt as $k => $v) {
    if ($k === 'id') continue;
    $c->$k = $v;
}
$c->questionid = $qid;
$DB->insert_record('question_coderunner_options', $c);
echo "Created coderunner options\n";

echo "\nDone! Prototype: question={$qid}, entry={$entryid}, category={$catid}\n";
