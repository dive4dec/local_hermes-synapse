# Verified column lists — gradebook + choicegroup (Moodle 5.x, dive.cs.cityu.edu.hk)

Probed 2026-08-27 via MCP `SHOW COLUMNS` (read-only). The PHP bootstrap's
`get_records`/`get_columns` fail with a bare "Error reading from database" on
wrong table OR column names, so this list is the source of truth.

## mdl_grade_items (note: PLURAL table; `get_records('grade_item')` fails)

```
id, courseid, categoryid, itemname, itemtype, itemmodule, iteminstance,
itemnumber, iteminfo (longtext), idnumber, calculation (longtext), gradetype,
grademax (decimal 10,5), grademin (decimal 10,5), scaleid, outcomeid,
gradepass (decimal 10,5), multfactor, plusfactor,
aggregationcoef (decimal 10,5), aggregationcoef2 (decimal 10,5),
sortorder, display, decimals, hidden, locked, locktime, needsupdate,
weightoverride, timecreated, timemodified
```

Key points:
- **Weight = `aggregationcoef2`** (fraction). There is NO `weight` column.
- `aggregationcoef` (singular) is used by other aggregation types; both exist.
- `hidden`: 0=visible, 1=hidden, >1=timestamp (hide-until: item becomes
  visible AFTER that time — E/CE-Quiz items here carry their quiz close times).

## mdl_grade_categories

- NO `sortorder`, NO `idnumber`, NO `letterbox` columns (Unknown column errors).
- Root category = `depth = 1 AND parent IS NULL`.
- `aggregation` is an int constant — version-specific; on this site
  `13 = GRADE_AGGREGATE_SUM` ("Natural") per `lib/grade/constants.php`.

## mdl_grade_settings

- Columns: `id, courseid, name, value`. Course 3 only has `minmaxtouse=1`.

## mdl_choicegroup / options

- `choicegroup` rows exist (id, name, intro, ...).
- `choicegroup_options` columns (verified `get_columns`): `id, choicegroupid,
  groupid, maxanswers, timemodified` — the option label shown to students is
  derived from the **group name** (`groups.name` via `groupid`), there is no
  `name` column. `mdl_choicegroup_answers` does NOT exist (answers live in
  `mdl_choice`-style storage; don't probe for it via MCP).
- Verifying a registration choicegroup: map each option's `groupid` →
  `groups.name`, check 100% coverage of expected group names, no duplicates,
  no missing — that's what makes student registration safe.
