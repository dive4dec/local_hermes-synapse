# Natural / SUM grade aggregation (GRADE_AGGREGATE_SUM = 13)

How the course total is actually computed when the grade category uses **Natural**
(aggregation constant **13** = `GRADE_AGGREGATE_SUM` on this site — see
`/var/www/html/public/lib/grade/constants.php`). Read `lib/grade/grade_category.php`
(`aggregate_values_and_adjust_bounds`, case `GRADE_AGGREGATE_SUM`) if you need to be
precise. This matters because the "Weight" column in the UI does NOT map 1:1 to how the
total is built.

## Key mechanics (verified against source, 2026-08-27)

- **Per-item weight.** For an item with `aggregationcoef2 > 0` and `weightoverride = 0`,
  the effective weight = `aggregationcoef2 / SUM(all coef2>0 items)`. For items with
  `weightoverride = 1`, the effective weight is the **absolute** `aggregationcoef2`
  fraction (the auto-weights of the remaining items are then scaled to fill the rest).
  So a "50% / 20% / 20% / 5% / 5%" plan entered with a few `weightoverride=1` anchors and
  the rest left at their `aggregationcoef2` values **is** honoured — the UI weight column
  is real, just not the sole mechanism.
- **Category (course) `grademax` = SUM of child grademaxes** for the items with
  `coef2 > 0` (non-extra-credit). This is `auto_update_max()`. Hence a course whose
  counted items max out at 100+20+5+80×9+20×9 shows a course-item `grademax` of
  **1025**, not 100. The displayed total is that **raw point sum** (e.g. `820`), NOT a
  percentage.
- The hidden "Mock … (25B)" retake items carry their own `coef2` (e.g. 0.35714 on Mock
  Exam) — investigate whether they inflate the weight sum / max before "fixing" anything.

## Making the total display as a percentage (without touching grades or weights)

This is the answer to "normalize the total to a percentage, but don't change the
individual activity grades or the weightings":

- Set the **course item's** `display` column to **`GRADE_DISPLAY_TYPE_PERCENTAGE` = 2**
  (constant in `lib/grade/constants.php`: `…_PERCENTAGE = 2`, `…_REAL = 1`, `…_DEFAULT = 0`).
  Only the *display type* of the top-level course column changes; no `rawgrade`,
  `finalgrade`, `aggregationcoef2`, or item `grademax` is modified. Students then see
  `80%` instead of `820 / 1025`.
- **Verify in the UI / via a controlled test before declaring it done** (see the test
  recipe below). I read the source and constants but did NOT complete a live recalc this
  session — do not present this as empirically confirmed until you have.

## Recalc API (Moodle 5.x on this site)

- `grade_regrade_user()` **does not exist** here. The correct entry point:
  ```php
  require_once($CFG->libdir . '/gradelib.php');   // NOTE: lib/gradelib.php, NOT lib/grade/gradelib.php
  $course_item = grade_item::fetch_course_item($courseid);
  $course_item->regrade_final_grades($userid /* or null for whole course */);
  ```
- `grade_item` is **not** autoloaded in a raw `define('CLI_SCRIPT',TRUE)` bootstrap until
  you `require_once` `lib/gradelib.php` (that file pulls the grade classes in).
- The per-user fast path `grade_regrade_final_grades($cid, $uid, $updated_item)` requires
  a non-null `$updated_item`; for a standalone test just call `regrade_final_grades($uid)`
  on the fetched course item directly.
- `grade_item` has **no `set_name()`** method.

## Controlled empirical test recipe (test the total without touching real students)

Course 3's only enrolled "students" are LTI test users (e.g. Adam/Bob LTITEST,
userids ~496/497). Use one to prove the formula:

1. **Back up** all of the test user's course rows first:
   `SELECT gg.* FROM mdl_grade_grades gg JOIN mdl_grade_items gi ON gi.id=gg.itemid WHERE gi.courseid=3 AND gg.userid=:u` → save to a JSON file (all 23 `mdl_grade_grades` columns).
2. Write known finals to a few items (Exam 80/100, etc.), run `regrade_final_grades($uid)`, read back the course item (`itemid=39`) `rawgrade/finalgrade/rawgrademax`, and read each item's stored `aggregationweight` to see the effective weights.
3. **Restore verbatim**: delete the user's course-3 rows and re-INSERT the exact backup rows, then recalc once.
4. Confirm the course item matches the pre-test state.

## Pitfalls

- `mdl_grade_grades` has **no `courseid` column** — always join `mdl_grade_items gi ON gi.id=gg.itemid` to scope by course.
- "!!! Error reading from database !!!" from `$DB->get_records_sql()` in this environment is a **SQL/column error**, not a method failure — usually a wrong column name (`mdl_quiz.timegradelimit`, `mdl_grade_grades.courseid`, `mdl_groups.visible`). `DESCRIBE` the table before guessing.
- Don't "rescale" item `grademax` or weights to make the total /100 — use the **display type** instead; changing grademaxes/weights changes every student's final grade.
