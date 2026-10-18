---
name: moodle-wiki-data-access
description: "Read and modify Moodle wiki module (mod/wiki) data: where the description and page text actually live, the current schema, resolving a page from a URL, and format constants. Use when editing a wiki's description, inspecting/creating wiki pages, or debugging why wiki tables seem empty."
---

# Moodle Wiki Module Data Access

How to find and change content in the `mod/wiki` module. Covers the two places people look in the wrong spot: the **activity description** (it's not in a page) and **page text** (it's not in `wiki_pages.cachedcontent`).

## Triggers

- "Edit/improve the description of the wiki activity"
- "Where is the wiki page content stored?"
- "The wiki shows nothing / the tables are empty"
- Creating or inspecting wiki pages programmatically
- Debugging "Error reading from database" when touching `wiki_*` tables

## The two things people get wrong

1. **The description under the wiki title on the course page is `mdl_wiki.intro`, NOT a wiki page.** A brand-new collaborative wiki has **zero** rows in `wiki_subwikis` and `wiki_pages` until someone makes the first edit — yet it still displays a full description. So an "empty wiki" with a description is normal, not a bug.
2. **Page source text is in `mdl_wiki_versions`, not `wiki_pages.cachedcontent`.** `cachedcontent` is rendered cache. The current page text = the `wiki_versions` row with the max `version` for that `pageid`.

## Access method

Use the PHP bootstrap (see the `moodle-db-access` skill):

```php
<?php
define('CLI_SCRIPT', true);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/check.php';
require_once('/var/www/html/config.php');
// $DB now available
```

## Reading a wiki's description

```php
$wiki = $DB->get_record('wiki', ['id' => $wikiId]);   // $wikiId == course_modules.instance
echo $wiki->name;          // activity name
echo $wiki->intro;         // the description text
echo $wiki->introformat;   // format constant (see below)
```

## Resolving a page from a URL

`view.php` accepts three distinct param sets (see `public/mod/wiki/view.php`):
- `view.php?id=<cmid>` — canonical entry: shows the first page (or redirects to `create.php` for a fresh wiki).
- `view.php?wid=<wikiid>&title=<slug>` — view a page by title. **`wid` is the wiki id (== `course_modules.instance`), NOT the subwiki id** (despite the variable name).
- `view.php?pageid=<pageid>` — view a page by its `wiki_pages.id`.

`index.php?id=<courseid>` takes a **course id** and 303-redirects to the course overview — it is not a wiki page URL. A URL like `view.php?w=1` (using `w=`) 404s; the param is `wid`, `id`, or `pageid`, never `w`/`wiki`/`page`. Grouped wikis carry `group` and `uid` params (a collaborative wiki always uses `group=0&uid=0` for the main subwiki).

```php
$sw   = $DB->get_record('wiki_subwikis', ['wikiid' => $wikiid, 'groupid' => $groupId, 'userid' => $userId]);
$page = $DB->get_record('wiki_pages', ['subwikiid' => $sw->id, 'title' => $slug]);
$vers = $DB->get_records('wiki_versions', ['pageid' => $page->id]);
// pick the row with max (int)$v->version -> $v->content + $v->contentformat
```

For the main (ungrouped) subwiki use `groupid=0, userid=0`.

## Format constants

Defined in `<webroot>/lib/weblib.php` (~lines 42-65). Both `wiki.introformat` and `wiki_versions.contentformat` use these:

`FORMAT_MOODLE=0`, `FORMAT_HTML=1`, `FORMAT_PLAIN=2`, `FORMAT_WIKI=3` (deprecated), `FORMAT_MARKDOWN=4`.

So `introformat=4` means the description is **Markdown** — single-asterisk `*em*` renders as italics (intentional emphasis, don't "fix" it).

## Editing the description (safe)

```php
$wiki = $DB->get_record('wiki', ['id' => $wikiId]);
$wiki->intro = $newText;                 // keep $wiki->introformat unless changing it
$DB->update_record('wiki', $wiki);
```

For multiple small fixes, don't rewrite the whole text by hand — apply targeted `str_replace()` pairs and **assert each old string occurs exactly once** before replacing (exit 1 otherwise), so a typo or already-applied edit can't silently corrupt the text:

```php
foreach ($pairs as [$from, $to]) {
    if (substr_count($wiki->intro, $from) !== 1) { fwrite(STDERR, "no unique match: $from\n"); exit(1); }
    $wiki->intro = str_replace($from, $to, $wiki->intro);
}
$wiki->timemodified = time();
$DB->update_record('wiki', $wiki);
```

Then **always** `cd <webroot> && moosh -n cache-clear`.

## Verifying a description edit in the UI

The live site (`<moodle-host>`) is **login-gated (LTI)** — unauthenticated `curl` of any course URL returns a 303 to `login/index.php` or a 404 "Error" page. Do NOT loop on curl variations of `view.php`; it will never render without a session.

Instead verify **server-side**: boot the framework (CLI) and run the exact same function the UI uses to render the text:

```php
$wiki = $DB->get_record('wiki', ['id' => $wikiId]);
$html = format_text($wiki->intro, (int)$wiki->introformat);
echo $html;  // this is exactly what the course section / wiki view will display
```

`format_text()` on the CLI with `CLI_SCRIPT=true` works for all standard formats (Markdown, Moodle, HTML). For Markdown (`introformat=4`) it converts `*em*` → `<em>`, `- item` → `<ul><li>`, etc. — so you can assert on the rendered HTML (e.g. `strpos($html, '<em>public git repository</em>') !== false`).

Then tell the user the DB value + rendered HTML are correct and ask them to do the final browser refresh, since only their logged-in session can see the page.

**Caveat on string-matching assertions:** when the fix was a capitalization change (e.g. `python` → `Python`), a `stripos()` check for the *old* string will falsely "fail" because the new string contains the old one case-insensitively. Use case-sensitive `strpos()` for absence checks of the old form.

## Editing page text (caution)

Do NOT update `wiki_pages.cachedcontent` directly — it's cache and the module will overwrite it. Do NOT hand-insert `wiki_versions` without incrementing `version` or the UI/history will desync. Prefer the UI. If programmatic write is unavoidable, mirror the module's page-save path: insert a new `wiki_versions` row at `version = max+1`, update the page's cache/timestamps, and purge caches.

## Pitfalls

- **`mdl_wiki_suburbs` does NOT exist** (pre-Moodle-4.1 schema). Querying it → "Error reading from database". The current chain is `wiki` → `wiki_subwikis` → `wiki_pages` → `wiki_versions`.
- **`$DB->get_fields()` and `$DB->describe_table()` do not exist** on `mariadb_native_moodle_database` ("Call to undefined method"). To inspect schema, read `<webroot>/mod/wiki/db/install.xml`.
- **Fresh wiki = 0 subwikis/pages.** Don't conclude "no content" — the description is in `wiki.intro`.
- **`wid` param in `view.php` = `mdl_wiki.id`** (= `course_modules.instance`), not the course-module id or subwiki id. `view.php?id=<cmid>` is the CM id.
- **Always `moosh -n cache-clear`** after any DB change so the UI reflects it.

## Reference files

- `references/wiki-module.md` — full current table schema (columns + keys), format constants, and URL→page resolution detail.
