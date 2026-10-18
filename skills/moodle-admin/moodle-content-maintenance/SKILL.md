---
name: moodle-content-maintenance
description: "Bulk fixes for Moodle content: URL migration after course route changes, delimiter migrations, hardcoded content corrections. Covers scanning, relative URL conversion, and cache purging."
---

# Moodle Content Maintenance

Class-level skill for bulk content operations in Moodle: migrating hardcoded URLs, fixing delimiters, and correcting content across pages, labels, and other activities.

## Triggers

- Course route changed (WWWROOT migration, subpath rename) and links are broken
- User asks to find or fix outdated URLs in course content
- Bulk content correction (delimiters, text replacements, link fixes)
- Copying rich-text content between courses (forum FAQ post from one course to its clone)
- "All the links are broken after I moved the course"

## URL Migration (course route changes)

When a Moodle course route changes (e.g. `socratic.example.com/oldpath` → `dive.example.com/newpath`), hardcoded full URLs in page/label content break.

### Step 1: Scan for affected records

**CRITICAL: Always ask the user for the old and new URL prefixes before scanning.** Never guess or hardcode them.

```sql
-- Pages
SELECT id, name FROM mdl_page
WHERE content LIKE '%example.com/oldpath%' OR intro LIKE '%example.com/oldpath%';

-- Labels (content lives in `intro` column, NOT `content`)
SELECT id FROM mdl_label
WHERE intro LIKE '%example.com/oldpath%';

-- Question bank (often overlooked)
SELECT id, name FROM mdl_question
WHERE questiontext LIKE '%example.com/oldpath%'
   OR generalfeedback LIKE '%example.com/oldpath%';

-- Check other tables if needed
SELECT id, name FROM mdl_resource WHERE intro LIKE '%example.com/oldpath%';
```

**Key fact:** `mdl_label` stores text in the `intro` column, NOT `content`. `mdl_page` stores in both `intro` and `content`.

### Step 2: Convert to relative URLs

Replace full URLs with relative URLs so they survive future route changes.

**CRITICAL: Always include `mod/` in the relative path.** Moodle module URLs are at `BASE/mod/TYPE/view.php`. A relative URL that drops `mod/` will break.

| Scenario | Correct | Wrong (broken) |
|---|---|---|
| Same module (page → page) | `view.php?id=N` | `../page/view.php?id=N` |
| Cross-module (label → resource) | `../mod/resource/view.php?id=N` | `../resource/view.php?id=N` |
| Cross-module (page → resource) | `../mod/resource/view.php?id=N` | `../resource/view.php?id=N` |
| Cross-module (label → page) | `../mod/page/view.php?id=N` | `../page/view.php?id=N` |

For **same-module** links (both source and target are in `mod/page/`), the relative path is just `view.php?id=N` — no `../` needed since they share the same directory.

For **cross-module** links, use `../mod/TYPE/view.php?id=N`.

```php
// PHP pattern for bulk replacement
$oldPageUrl = 'https://dive.example.com/old-path/mod/page/view.php';
$newPageRel = 'view.php';  // same module

$oldResourceUrl = 'https://dive.example.com/old-path/mod/resource/view.php';
$newResourceRel = '../mod/resource/view.php';  // cross-module
```

Write a PHP mysqli script and execute it.

### Step 3: Purge caches

```bash
cd <webroot> && moosh -n cache-clear
```

### Step 4: Verify

```sql
SELECT COUNT(*) FROM mdl_page WHERE content LIKE '%example.com/oldpath%' OR intro LIKE '%example.com/oldpath%';
SELECT COUNT(*) FROM mdl_label WHERE intro LIKE '%example.com/oldpath%';
```

Must return 0.

## Course-embedded paths (JupyterHub, LTI, external links)

When a course identifier is baked into external service URLs (JupyterHub paths, LTI launch URLs, GitHub repos, JupyterBook paths), relative-URL conversion doesn't apply. The full hostname + path needs updating.

### Step 1: Find affected labels

```sql
SELECT cm.id AS cmid, l.intro
FROM mdl_course_modules cm
JOIN mdl_label l ON l.id = cm.instance
WHERE cm.course = <courseid>
  AND l.intro LIKE '%<course>_25b%';  -- whatever old course slug
```

### Step 2: Replace embedded paths

Read the `intro` column, apply `str_replace()` for each old→new slug pair, write back via mysqli. Common replacements:
- Hub route: `<course>_25b` → `<coursecode>`
- JupyterBook: `<course>i25b` → `<coursecode>i26a`
- GitHub repo: `<course>_25b` → `<coursecode>`

URL-encoded content (`%3A`, `%2F`) is still text-searchable — `LIKE` matches inside encoded hrefs.

### Canvas LTI wrapper URLs with embedded course IDs

Jupyter notebook links are often wrapped through Canvas LTI:
`https://canvas.<domain>/courses/67308/external_tools/retrieve?display=borderless&url=...<course>_25b/hub/lti/launch...`. Both the **Canvas course ID** (`67308`) and the **JupyterHub course slug** (`<course>_25b`) must be replaced. Find them:

```sql
SELECT cm.id AS cmid, l.intro
FROM mdl_course_modules cm
JOIN mdl_label l ON l.id = cm.instance
WHERE cm.course = <courseid>
  AND l.intro LIKE '%<course>_25b%'
  AND l.intro LIKE '%ipynb%';
```

Apply all three `str_replace()` calls: old course slug, Canvas course ID, and JupyterBook slug.

### Step 3: Purge caches and verify

```bash
cd /var/www/html && php admin/cli/purge_caches.php
```

Re-run the scan — count must be 0.

## Copying rich-text content between courses (forum posts, labels, pages)

When copying a piece of rich-text content (e.g. a forum FAQ post) from one course to another, do NOT just `INSERT ... SELECT`. Verify the source renders cleanly first — you will otherwise copy broken markup into the target.

### Step 1 — Render the source through Moodle's formatter

Raw DB text is not what students see. In a PHP bootstrap script (see `moodle-db-access`):

```php
$ctx = context_course::instance($courseid);
// messageformat values (lib/weblib.php): 0=FORMAT_MOODLE, 1=FORMAT_HTML, 2=FORMAT_PLAIN, 4=FORMAT_MARKDOWN
$html = format_text($raw, FORMAT_MARKDOWN, ['context' => $ctx, 'cleaning' => true]);
echo $html . "\n";
```

Read the row's `messageformat` FIRST and use the matching constant. Rendering a `messageformat=4` (Markdown) post with `FORMAT_MOODLE` leaves `**bold**` and `- ` bullets literal — a false alarm that can send you chasing a phantom bug (this exact mistake happened on 2026-08-23 while auditing a CE-Quiz FAQ post).

### Step 2 — Audit inline HTML tag balance (Markdown mixes raw HTML)

An unclosed or misspelled inline-HTML tag swallows everything after it into the tag. Real case (2026-08-23): `</kdb>` (typo of `</kbd>`) in a Markdown forum post made the rest of the post render inside the keyboard-key badge — and a user "fix" that only moved the typo's position still shipped broken. Count tags exactly:

```php
echo substr_count($raw, '<kbd>') . " / " . substr_count($raw, '</kbd>') . "\n"; // must be equal
echo "count '</kdb>': " . substr_count($raw, '</kdb>') . "\n";  // scan misspelled variants
```

Also note: JSON tool output escapes the sparkles ✨ (U+2728) as `\u2728` — that's normal escaping, not data corruption.

### Step 3 — Copy with correct plumbing

- `mdl_forum_discussions`: set `course`/`forum` to the target, `firstpost` to the NEW post id, `usermodified` to the author id, and copy `timemodified` from the source — the forum list sorts by `d.timemodified DESC` (pinned first; `forum_get_default_sort_order()` in mod/forum/lib.php), so `timemodified` controls where the topic lands.
- `mdl_forum_posts`: copy `subject`, `message`, `messageformat`, `messagetrust`, `wordcount`, `charcount`, `created`, `modified` verbatim (fix markup issues in `message` only after verifying the fixed version renders).
- Match the target forum's sibling defaults (`assessed`, `pinned`, `groupid`, `timelocked`, `timestart`, `timeend`) — read a couple of existing rows in the target forum rather than reusing the source's flags blindly.
- Attachments: check `mdl_files` with `component='mod_forum'` and `itemid=<postid>` — `mdl_post_attachments` does NOT exist in Moodle 5.x.
- `moosh -n cache-clear`, then verify the topic appears in the target forum (DB read-back + rendered page).

If the source is broken, present the markup fix as part of the change plan and ask the user whether to also repair the source row.

## Pitfalls

- **`mdl_label.intro` not `mdl_label.content`:** Labels store text in `intro`, not `content`. Querying `content` on labels gives "Unknown column" errors.
- **Always include `mod/` in relative URLs:** `../mod/resource/view.php` is correct; `../resource/view.php` drops `mod/` and breaks. Moodle module URLs always have `mod/` in the path.
- **Same-module links need no `../`:** Both pages live in `mod/page/`, so `view.php?id=N` (not `../page/view.php?id=N`).
- **Questions live in shared categories:** A question's category may belong to a different course context (e.g. instanceid=101 != course id). To find which course a question belongs to, trace: `mdl_question` -> `mdl_question_versions` -> `mdl_question_bank_entries` -> `mdl_question_categories.contextid` -> `mdl_context.path`. The category name (e.g. "E-Quiz") is a strong hint.
- **`mdl_question` has `questiontext` and `generalfeedback` columns** — both can contain old URLs.
- **`mdl_quiz` does NOT have a `showquestiontext` column** — always `DESCRIBE mdl_quiz` before guessing columns.
- **CE-Quiz pattern** — CE-Quizzes pull questions from shared "E-Quiz" categories. Quiz intro text contains instructions (adaptive mode, precheck/check with penalties, OPTMentor allowed, SEB required).
- **`mdl_course_modules.section` is the section number**, NOT a `sectionid` foreign key — join directly on `cm.section = N`.