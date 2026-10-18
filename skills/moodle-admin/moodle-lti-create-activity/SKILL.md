---
name: moodle-lti-create-activity
description: Create Moodle LTI activities via PHP API with proper cache purging. Used when adding LTI notebook links to course sections.
---

# Create Moodle LTI Activity

Creates an LTI activity in Moodle's database using PHP API, matching the pattern for JupyterHub notebook links in CS1302 courses.

## Steps

1. **Find the notebook URL** from the corresponding Lecture label's `intro` HTML:
   - Labels contain Canvas LTI launch URLs with `custom_next` pointing to JupyterHub
   - Decode the `custom_next` parameter to extract `repo` and `urlpath`

2. **Create LTI record** with all required fields (missing fields cause silent insert failures):
```php
$lti = new stdClass();
$lti->course = 3;
$lti->name = 'Activity Name';
$lti->intro = '';
$lti->introformat = 4;
$lti->timecreated = time();
$lti->timemodified = time();
$lti->typeid = 2;
$lti->toolurl = '';
$lti->securetoolurl = '';
$lti->instructorchoicesendname = 1;
$lti->instructorchoicesendemailaddr = 1;
$lti->instructorchoiceallowroster = '';
$lti->instructorchoiceallowsetting = '';
$lti->instructorcustomparameters = 'next=../user-redirect/git-pull?repo=...&urlpath=...';
$lti->instructorchoiceacceptgrades = 0;
$lti->grade = 0;
$lti->launchcontainer = 1;
$lti->resourcekey = '';
$lti->password = '';
$lti->debuglaunch = 0;
$lti->showtitlelaunch = 0;
$lti->showdescriptionlaunch = 0;
$lti->servicesalt = '';
$lti->icon = '';
$lti->secureicon = '';
$ltiid = $DB->insert_record('lti', $lti);
```

3. **Create course_modules entry**:
```php
$cm = new stdClass();
$cm->course = 3;
$cm->module = 14; // lti
$cm->instance = $ltiid;
$cm->section = $section_id;
$cm->added = time();
$cm->score = 0;
$cm->indent = 1;
$cm->visible = 1;
$cm->visibleoncoursepage = 1;
$cm->visibleold = 1;
$cm->groupmode = 0;
$cm->groupingid = 0;
$cm->completion = 0;
$cm->completionview = 0;
$cm->showdescription = 1;
$cm->downloadcontent = 1;
$cm->lang = '';
$cm->enableaitools = 0;
$cm->enabledaiactions = '{"summarise_text":1,"explain_text":1,"generate_text":1}';
$cmid = $DB->insert_record('course_modules', $cm);
```

4. **Insert into section sequence** (after the Lecture label):
```php
$section = $DB->get_record('course_sections', ['id' => $section_id]);
$label_cmid = 157; // Lecture label cmid
$new_sequence = $label_cmid . ',' . $cmid . ',' . substr($section->sequence, strlen("$label_cmid,") + 0);
// Or simply: insert after known position
$new_sequence = '157,' . $cmid . ',' . substr($section->sequence, 4);
$section->sequence = $new_sequence;
$DB->update_record('course_sections', $section);
```

5. **Create context**:
```php
require_once($CFG->dirroot . '/lib/accesslib.php');
context_module::instance($cmid, true);
```

6. **Purge caches** (both required):
```php
cache_helper::purge_by_event('changesincourse');
cache::make('core', 'coursemodinfo')->purge();
```

## Pitfalls

- **Missing LTI fields**: The insert silently fails if required columns like `typeid`, `introformat`, `servicesalt` are missing. Copy all fields from an existing working LTI record.
- **Cache not visible**: Both `changesincourse` event and `coursemodinfo` cache must be purged, or the activity won't appear in the UI.
- **`section` field**: In `course_modules`, `section` is the `course_sections.id` (not the section number).
- **Script file approach**: Write PHP to a temp file and execute with `php`, not inline with `-r`, because shell quoting mangles Moodle variable references.
- **Clean up**: Always delete the temp PHP script after execution.