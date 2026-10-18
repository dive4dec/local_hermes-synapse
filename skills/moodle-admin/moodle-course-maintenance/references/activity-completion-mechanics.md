# Activity Completion Mechanics (Moodle 5.x, dive.cs.cityu.edu.hk)

Verified 2026-08-28 from code (`completion/classes/form/form_trait.php`,
`lib/completionlib.php`, `mod/quiz/lib.php`, `mod/quiz/classes/completion/custom_completion.php`)
+ live DB. Reference config: **Mock Midterm (25B), cs1302a_26a (course 3), cm 217** —
`completion=2`, `completiongradeitemnumber=0`, `completionpassgrade=1`, grade item gradepass=6/20.

## UI → DB mapping (single-grade-item activities, i.e. quiz)

| UI element | Column | Meaning |
|---|---|---|
| Activity completion: Automatic | `course_modules.completion = 2` | (0 = disabled, 1 = manual) |
| ☑ "Receiving a grade" | `course_modules.completiongradeitemnumber = 0` | NULL = not enabled. Manager code (`completion/classes/manager.php`): `completiongradeitemnumber = !empty($data['completionusegrade']) ? 0 : null` |
| ○ "Receiving a passing grade" (sub-option, shown only when the above is checked) | `course_modules.completionpassgrade = 1` | 0 = complete on any grade |
| The pass mark | `grade_items.gradepass` | e.g. 30 of 100, 6 of 20. NOT a completion field — part of the grade item definition |

Evaluation path: `completionlib::get_core_completion_state()` →
`get_grade_completion()` → `internal_get_grade_state($item, $grade, $returnpassfail)`:
`$score >= $item->gradepass` → PASS; `gradepass` empty/0 → any recorded grade completes.

Quiz custom rules: `mdl_quiz.completionattemptsexhausted` / `completionminattempts` only activate
when `completionattemptsexhausted = 1` (then cm customdata gets
`customcompletionrules.completionpassorattemptsexhausted`); all Mock quizzes have it 0.

## Consistency audit — Mock exams/midterms (state at 2026-08-28)

Standard per user: **Mock Exams** pass 30/100; **Mock Midterms** pass 6/20; all should be
auto-completed via Receiving a grade + Receiving a passing grade.

- **cs1302a_26a (3):** Mock Exams cm 111–116, 218 — flags missing, gradepass already 30.
  Mock Midterms cm 133 (gradepass 6, flags missing), 134–138 (gradepass **0 → 6** + flags).
  cm 217 (25B midterm) = correct reference.
- **cs1302_26a (7):** all Mock Exams cm 637–643 and Mock Midterms cm 624–630 — flags missing;
  midterm gradepass 0→6 on cm 625–629 (25A/25B already 6).
- **Anomaly:** Mock Exam (25B) in course 7 (cm 637) has quiz max grade 0 (gi 228).
- **Legacy "Mock Exam/Midterm 2020–2025" have NO grade items** → cannot support pass-grade
  completion at all.
- **Duplicate CMs in course 3** (cloning leftovers): 25B midterm cm 153 (completion=1) & 217 (completion=2);
  25B exam cm 154 (completion=0) & 218 (completion=2); 23A midterm cm 102 (completion=0) & 135 (completion=2).
  Always list cm + `cm.visible` before bulk edits to scope to the live CM.
- Availability rules: checked 2026-08-28 — NO availability conditions in courses 3/7 reference these Mock cmids.

**Status (2026-08-28, RESOLVED):** Course 3 (cs1302a_26a) — all 13 rows APPLIED and verified
through the real completion engine (see "Verify with the real engine" below); pre-change backup
at `/tmp/mock_completion_backup_20260828_134450.json`. Course 7 (cs1302_26a) — **NOT applied**:
user chose to delete the whole course instead (delete still pending — it has 3 active
enrolments, 6 quiz attempts, 110 CMs; soft vs hard not yet chosen). Duplicates + legacy
2020–2025 mocks were left alone per user. Re-check live state before any course-7 or duplicate
work in a later session.

## Apply workflow (after user confirmation)

1. Back up the affected rows (SELECT * for the cmids + grade item ids → /tmp file).
2. Direct SQL: `UPDATE mdl_course_modules SET completiongradeitemnumber=0, completionpassgrade=1 WHERE id IN (...)`;
   `UPDATE mdl_grade_items SET gradepass=6.00000 WHERE id IN (...)`.
3. `cd /var/www/html/public && moosh -n cache-clear` (+ `core_coursemodinfo` purge — completion
   state is served through the cm info cache).
4. **Verify in the UI**: open each quiz's Activity completion form (checkbox + sub-option rendered)
   and one grade report for a test user (a failing-score student should show the pass rule incomplete).
   DB-only verification is not acceptable to the user.

## Verify with the real engine (what "verified in the UI" means here)

Run the same classes the UI uses, in a CLI bootstrap — this is what satisfies the
"verify, don't just check the DB" bar without a browser:

```php
$course = get_course($cid);                              // get_course(), NOT course_get_course()
$modinfo = core_course\modinfo::instance($course->id, 1); // 2-arg signature in this version
$completioninfo = new completion_info($course);           // plain class, lib/completionlib.php
$cminfo = $modinfo->get_cm($cmid);                        // method is get_cm, NOT get_cm_info
$details = (new core_completion\cm_completion_details($completioninfo, $cminfo, $userid))
            ->get_details();
// array_keys($details) = the rules the UI lists -> expect 'completionusegrade' + 'completionpassgrade'
// $details['completionpassgrade']->status: 2=PASS 3=FAIL 0=INCOMPLETE (entries are objects)
```
Resolve the item exactly as the engine does: `grade_item::fetch([...,'itemnumber'=>0])`
(needs `require_once($CFG->libdir.'/gradelib.php')`). Expected state per student:
`score = finalgrade ?? rawgrade; expected = score===null ? INCOMPLETE
: (score >= gradepass ? COMPLETE_PASS : COMPLETE_FAIL)` — **NULL score is INCOMPLETE, not
FAIL** (treating NULL as 0 produces false mismatches; these mocks had only placeholder
grade_grades rows, raw/final NULL, for the two LTI test users). Also confirm the student-facing
quiz page message: `mod/quiz/view.php` prints "Grade to pass: X out of Y" whenever
`gradepass != 0`.

## Pitfalls

- **CM id ≠ quiz id, differs per course** — echo the activity name inside the applying script.
- Duplicate CMs for the same quiz instance (course 3): scope by visible CM id, never by quiz id alone.
- Legacy mocks without grade items: if `completiongradeitemnumber` is set with no grade item,
  the form's "Receiving a grade" may display checked but evaluation can never complete.
- `gradepass` is part of the grade item definition — changing it affects the grade report (P/F
  indicators), not just completion.
- Standalone `completion=2` with zero criteria = nothing ever auto-completes; that's the "invalid
  setting" symptom the user reported.
