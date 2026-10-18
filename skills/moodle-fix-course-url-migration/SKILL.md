---
name: moodle-fix-course-url-migration
description: "Fix hardcoded course URLs in Moodle after changing the WWWROOT or course route. Converts full URLs to relative URLs so they survive future route changes."
---

# Fix Hardcoded Course URLs After Route Migration

When a Moodle course route (WWWROOT path) changes, hardcoded full URLs in page content, labels, and other text fields break. This skill finds and fixes them.

## Trigger

- User changes course route/WWWROOT and links are broken
- User mentions old URLs still in the database after migration
- "links not migrated", "old URLs", "route change", "broken links after move"

## Prerequisites

Ask the user for:
1. **Old URL prefix** — e.g. `https://socratic.cs.cityu.edu.hk/cs1302eq-26a`
2. **New URL prefix** — e.g. `https://dive.cs.cityu.edu.hk/cs1302a-eq`

## Steps

### 1. Find all affected records

Query `mdl_page` (intro + content columns) and `mdl_label` (intro column) for the old URL pattern:

```php
<?php
$mysqli = new mysqli('mariadb', 'moodleuser', base64_decode('PASS_FROM_CONFIG'), 'moodle');
// Pages
$mysqli->query("
    SELECT id, name, 'intro' as col FROM mdl_page WHERE intro LIKE '%OLD_PREFIX%'
    UNION ALL
    SELECT id, name, 'content' FROM mdl_page WHERE content LIKE '%OLD_PREFIX%'
");
// Labels
$mysqli->query("
    SELECT id, 'intro' as col FROM mdl_label WHERE intro LIKE '%OLD_PREFIX%'
");
?>
```

Read DB password from `/var/www/html/config.php` — it's base64-encoded.

### 2. Convert to relative URLs (preferred)

Relative URLs survive future route changes. Use `../` to go up one level from the current module's URL.

**CRITICAL: Always include the `mod/` segment.** Moodle module URLs are at `BASE/mod/TYP/view.php`. From a sibling module in the same directory, the relative path is `../mod/TYP/view.php` (not `../TYP/view.php` — that drops `mod/` and breaks the link).

| Source URL | Correct relative | Wrong (broken) |
|---|---|---|
| `.../mod/page/view.php` → `.../mod/page/view.php` | `view.php?id=N` (same dir) | `page/view.php?id=N` |
| `.../mod/label/view.php` → `.../mod/resource/view.php` | `../mod/resource/view.php?id=N` | `../resource/view.php?id=N` |
| `.../mod/page/view.php` → `.../mod/resource/view.php` | `../mod/resource/view.php?id=N` | `../resource/view.php?id=N` |

```php
$oldBase = 'https://NEW_PREFIX/mod/page/view.php';
$newRel  = '../mod/page/view.php';  // or 'view.php' if linking within same module type

$oldResource = 'https://NEW_PREFIX/mod/resource/view.php';
$newRelResource = '../mod/resource/view.php';
```

$newIntro    = str_replace($oldBase, $newRel, $intro);
$newContent  = str_replace($oldBase, $newRel, $content);
```

If converting to relative URLs isn't feasible (e.g., links point to external courses), do a simple string replacement of the old prefix with the new prefix.

### 3. Update via PHP mysqli

Write a PHP script that iterates affected rows and applies the replacement. Use prepared statements for updates.

### 4. Purge caches

```bash
cd /var/www/html/public && moosh -n cache-clear
```

### 5. Verify

Confirm 0 records still contain the old URL prefix, and list the converted records to show they now use relative URLs.

```sql
SELECT COUNT(*) FROM mdl_page
WHERE intro LIKE '%OLD_PREFIX%' OR content LIKE '%OLD_PREFIX%'

SELECT COUNT(*) FROM mdl_label
WHERE intro LIKE '%OLD_PREFIX%'
```

### Key tables to check

| Table | Columns | Notes |
|---|---|---|
| `mdl_page` | `intro`, `content` | Page activity content |
| `mdl_label` | `intro` | Label text |
| `mdl_book` | `content` (in `mdl_book_chapters`) | Book chapters |
| `mdl_question` | `questiontext`, `generalfeedback` | Question bank — OPTMentor/optlite links |
| `mdl_url` | `url` | URL activity — typically external |

## Fixing question bank links

Questions may link to `ccha23.github.io/OPTM/` or `ccha23.github.io/optlite/` which need updating. Find and fix them:

```php
$result = $mysqli->query("
    SELECT q.id, q.questiontext, q.generalfeedback
    FROM mdl_question q
    WHERE q.questiontext LIKE '%%ccha23%%'
       OR q.generalfeedback LIKE '%%ccha23%%'
");
while ($row = $result->fetch_assoc()) {
    $newText = str_replace('https://ccha23.github.io/OPTM/', 'https://dive.cs.cityu.edu.hk/OPT_Mentor/', $row['questiontext']);
    $newText = str_replace('https://ccha23.github.io/optlite/', 'https://dive.cs.cityu.edu.hk/OPT_Mentor/', $newText);
    $newFeedback = str_replace('https://ccha23.github.io/OPTM/', 'https://dive.cs.cityu.edu.hk/OPT_Mentor/', $row['generalfeedback']);
    $newFeedback = str_replace('https://ccha23.github.io/optlite/', 'https://dive.cs.cityu.edu.hk/OPT_Mentor/', $newFeedback);
    $stmt = $mysqli->prepare("UPDATE mdl_question SET questiontext=?, generalfeedback=? WHERE id=?");
    $stmt->bind_param('ssi', $newText, $newFeedback, $row['id']);
    $stmt->execute();
}
```

Questions live in categories that may span multiple courses. To find which course a category belongs to:

```php
// From question ID to course
$qv = $mysqli->query("SELECT questionbankentryid FROM mdl_question_versions WHERE questionid = $qid");
$qbe = $mysqli->query("SELECT questioncategoryid FROM mdl_question_bank_entries WHERE id = {$qvRow['questionbankentryid']}");
$qc = $mysqli->query("SELECT contextid FROM mdl_question_categories WHERE id = {$qbeRow['questioncategoryid']}");
$ctx = $mysqli->query("SELECT contextlevel, instanceid FROM mdl_context WHERE id = {$qcRow['contextid']}");
// If contextlevel=70, instanceid is the course ID
```

### Pitfalls

- **Always include `mod/` in relative URLs** — `../mod/resource/view.php` is correct; `../resource/view.php` is broken. Moodle module URLs always have `mod/` in the path.
- **`view.php` for same-module links** — When linking from one page to another page, both live in `mod/page/`, so just `view.php?id=N` (no `../` needed).
- **Question bank links** — `mdl_question.questiontext` and `generalfeedback` also store links. `ccha23.github.io/OPTM/` and `ccha23.github.io/optlite/` are common old links. The initial 100-row query cap hides the full count — don't rely on `LIMIT 100` results.
- **Shared question categories** — Questions may live in a context tree that spans multiple courses (e.g., a shared E-Quiz category). Tracing `question_id → question_versions → question_bank_entries → question_categories → context → course` reveals the actual ownership.
- **Base64 password** — DB password in config.php is base64-encoded
- **mdl_label uses `intro`, NOT `content`** — easy to miss
- **Cache purge required** — always run `moosh -n cache-clear` after DB changes
- **Always ask the user for old/new prefixes** — never guess or hardcode them
- **Relative URLs are the robust fix** — they survive future route changes