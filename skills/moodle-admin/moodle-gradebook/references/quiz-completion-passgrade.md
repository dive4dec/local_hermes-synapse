# Quiz completion "Receiving a passing grade" — recipe & verification

Worked 2026-08-28 on cs1302a_26a (course 3): 13 Mock Exam/Midterm quizzes that had
"Receiving a grade" but were missing the "Receiving a passing grade" sub-option (and, for the
midterms, the pass mark itself). User spec: Mock Exams pass at 30/100, Mock Midterms pass at 6/20.

## Storage model (4 settings, 2 tables — see SKILL.md for the summary)

| UI control | Column | Value |
|---|---|---|
| Tracking = automatic | `course_modules.completion` | `2` |
| Receiving a grade | `course_modules.completiongradeitemnumber` | `0` (NULL = off) |
| ↳ Receiving a passing grade | `course_modules.completionpassgrade` | `1` (tinyint flag) |
| Pass mark (X out of Y) | `grade_items.gradepass` | 30 / 6 (decimal) |

- The form field `completionusegrade` is NOT a stored column — `completion/classes/manager.php`
  translates it to `completiongradeitemnumber` on save.
- Pass evaluation: `lib/completionlib.php :: internal_get_grade_state()` —
  `score = finalgrade ?? rawgrade`; `score >= gradepass` → `COMPLETION_COMPLETE_PASS` (2),
  below → `COMPLETE_FAIL` (3) (hidden item → 4); **no grade at all → `INCOMPLETE` (0)**.
- `mod/quiz/view.php` renders "Grade to pass: X out of Y" when `gradepass != 0`
  (via `grade_floats_different($gradeitem->gradepass, 0)`).
- Find the item: `grade_items WHERE courseid=.. AND itemtype='mod' AND itemmodule='quiz'
  AND iteminstance=<quizid> AND itemnumber=0`.
- A correct reference row (course 3, Mock Midterm 25B, cm 217): completion=2,
  completiongradeitemnumber=0, completionpassgrade=1, item gradepass=6/20.

## Bulk apply (backup → update → readback → cache)

```php
define('CLI_SCRIPT', true);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/check.php';
require_once('/var/www/html/config.php');

$cmids = [/* ... */];          // course_modules ids
$giids = [/* ... */];          // grade_items ids (verify each row's iteminstance first!)
// 1) backup both row sets to JSON before touching anything
// 2) $DB->execute("UPDATE {course_modules} SET completiongradeitemnumber=0, completionpassgrade=1 WHERE id IN (...)");
// 3) $DB->execute("UPDATE {grade_items} SET gradepass=6.00000 WHERE id IN (...)");
// 4) read back and assert; then:
```
`cd /var/www/html/public && moosh -n cache-clear`

**Pitfall hit:** `$DB->execute()` returns **boolean true on success, NOT a rowcount** —
`if ($n !== 13)` falsely reports "1 row updated" when 13 rows actually changed. Verify by
re-reading the rows (or `information_schema`), never by the execute() return value.

**Safety:** before updating a grade_item by id, assert `iteminstance` matches the intended
quiz and `courseid` matches — a wrong id list silently rewrites other items.

## Verify with the REAL engine (not DB-only)

Users get frustrated by "verified in DB" claims — run the same class the UI uses:

```php
$course = get_course(3);
$modinfo = core_course\modinfo::instance($course->id, 1);     // 2-arg signature in this version
$completioninfo = new completion_info($course);               // plain class from lib/completionlib.php
$cminfo = $modinfo->get_cm($cmid);                            // method is get_cm, not get_cm_info
$details = (new core_completion\cm_completion_details($completioninfo, $cminfo, $userid))->get_details();
```
- `array_keys($details)` = the completion rules the UI lists: expect `completionusegrade`
  AND `completionpassgrade` after the fix.
- Per student: `$details['completionpassgrade']->status` → 2=PASS, 3=FAIL, 0=INCOMPLETE.
- Resolve the item exactly as the engine does:
  `grade_item::fetch(['courseid'=>3,'itemtype'=>'mod','itemmodule'=>'quiz','iteminstance'=>$quizid,'itemnumber'=>0])`.
- Bootstrap notes for CLI scripts: `completion_info` needs no import (it's in
  lib/completionlib.php loaded by config); `grade_item` needs
  `require_once($CFG->libdir.'/gradelib.php')`; `course_get_course()` does not exist —
  use `get_course()`; chain ternaries need explicit parentheses (PHP 8 fatal otherwise).

## Expectation logic for behavior checks

`score = finalgrade ?? rawgrade; expected = score===null ? INCOMPLETE
: (score >= gradepass ? COMPLETE_PASS : COMPLETE_FAIL)`. Treating NULL as 0 (expecting FAIL
for no-grade) produces false mismatches — NULL means "no grade recorded" = INCOMPLETE.

## Data observations from this run (cs1302a_26a, course 3)

- Every mock quiz's `grade_grades` rows exist for the 2 LTITEST accounts (users 496/497)
  but with NULL raw/final — placeholder rows from enrolment, not real scores.
- Duplicate CMs exist for some quizzes (e.g. quiz 75 has cm 153 AND cm 217; quiz 51/52/54
  have hidden duplicates 102/104/107). Completion is per-CM, so duplicates each need the fix —
  the user chose to leave duplicates alone.
- Legacy "Mock Exam/Midterm (2020–2025)" quizzes have NO grade item rows at all → cannot
  support pass-grade completion without a gradebook fix first.
