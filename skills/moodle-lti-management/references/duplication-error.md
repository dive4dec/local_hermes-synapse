# LTI Activity Duplication Error — Investigation

**Session:** 2026-08-12
**Symptom:** Duplicating an LTI activity reports `dmlreadexception Error reading from database`. The duplicate IS created but retains the original name (no ` (Copy)` suffix). Other Moodle deployments do not exhibit this error.

## Root cause

The `mdl_lti` table is **missing the `coursemodule` column** that the LTI plugin code references.

### Evidence

1. `mdl_lti` columns (actual): `id, course, name, intro, introformat, timecreated, timemodified, typeid, toolurl, securetoolurl, instructorchoicesendname, instructorchoicesendemailaddr, instructorchoiceallowroster, instructorchoiceallowsetting, instructorcustomparameters, instructorchoiceacceptgrades, grade, launchcontainer, resourcekey, password, debuglaunch, showtitlelaunch, showdescriptionlaunch, servicesalt, icon, secureicon`

2. **`coursemodule` is absent** from both `install.xml` and `upgrade.php` — it was never added by any upgrade step.

3. Code at `mod/lti/lib.php:126` and `:178` references `$lti->coursemodule`:
```php
\core_completion\api::update_completion_date_event($lti->coursemodule, 'lti', $lti->id, $completiontimeexpected);
```

4. Direct query confirms the error:
```
Debug: Unknown column 'coursemodule' in 'SELECT'
SELECT coursemodule FROM mdl_lti WHERE id = ?
```

### Failure path during duplication

1. `cmactions::duplicate()` backs up and restores the LTI activity — succeeds, new record created
2. Post-processing calls `rename()` to add ` (Copy)` suffix
3. `rename()` calls `grade_update_mod_grades()` which triggers `lti_update_instance()`
4. `lti_update_instance()` calls `update_completion_date_event($lti->coursemodule, ...)`
5. This reads the `coursemodule` column from the LTI record → **`dmlreadexception`** because column doesn't exist
6. Exception bubbles up; rename never completes; duplicate keeps original name

### Why other deployments are fine

Other deployments likely had the `coursemodule` column added manually or through a different LTI plugin version. This is a **schema drift** bug in the LTI plugin where code references a column the official schema never created.

### Fix

```sql
ALTER TABLE mdl_lti ADD COLUMN coursemodule INT(10) DEFAULT NULL;
UPDATE mdl_lti lti
JOIN course_modules cm ON cm.instance = lti.id AND cm.module = (SELECT id FROM mdl_modules WHERE name = 'lti')
SET lti.coursemodule = cm.id;
```

## Debugging lesson

When a `dmlreadexception` occurs during duplication but the record IS created:
1. Check if the error references a missing column (the SQL in the debug info)
2. Compare actual table columns vs. what the code expects
3. Focus on **data/schema issues**, not Moodle core bugs — same codebase works on other deployments
