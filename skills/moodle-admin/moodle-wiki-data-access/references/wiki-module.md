# mod/wiki schema & content locations (Moodle 5.x)

Verified against `<webroot>/mod/wiki/db/install.xml` (schema VERSION 20250414) on this site.

## Tables

| Table | Key columns | Notes |
|---|---|---|
| `wiki` | `id`, `course`, `name`, `intro`, `introformat`, `firstpagetitle`, `wikimode`, `defaultformat`, `forceformat`, `editbegin`, `editend` | Activity settings. **`intro` = the description shown under the activity title on the course page** |
| `wiki_subwikis` | `id`, `wikiid`, `groupid`, `userid` | One subwiki per (wiki, group, user); unique key `wikiid+groupid+userid`. Main subwiki = `groupid=0, userid=0` (matches URL `group=0&uid=0`). Rows are created lazily — **zero rows on a fresh wiki with no edits** |
| `wiki_pages` | `id`, `subwikiid`, `title`, `cachedcontent`, `timecreated`, `timemodified`, `timerendered`, `userid`, `pageviews`, `readonly` | Only exists after first edit. Unique key `subwikiid+title+userid`. `cachedcontent` is render cache, **not** source |
| `wiki_versions` | `id`, `pageid`, `content`, `contentformat`, `version`, `timecreated`, `userid` | **Source of truth for page text.** Current page = max `version` per `pageid` |
| `wiki_synonyms` | `id`, `subwikiid`, `pageid`, `pagesynonym` | Alternate page names |
| `wiki_links` | `id`, `subwikiid`, `frompageid`, `topageid`, `tomissingpage` | Page-to-page links |
| `wiki_locks` | `id`, `pageid`, `sectionname`, `userid`, `lockedat` | Edit locks |

`mdl_wiki_suburbs` does NOT exist (pre-4.1) — querying it fails with "Error reading from database".

## URL params (from `mod/wiki/view.php`)

`view.php` takes one of three param sets — **never `w=`, `wiki=`, or `page=`** (those 404):

| Params | Meaning |
|---|---|
| `view.php?id=<cmid>` | Canonical entry — shows first page, or 303 → `create.php` for a fresh wiki |
| `view.php?wid=<wikiid>&title=<slug>` | Page by title. `wid` = `mdl_wiki.id` (= `course_modules.instance`), **not** the CM id or subwiki id |
| `view.php?pageid=<pageid>` | Page by `wiki_pages.id` |

`index.php?id=<courseid>` takes a **course id** (not a wiki/cm id) and 303-redirects to the course overview. Grouped wikis carry `group`/`uid` (collaborative main subwiki = `group=0&uid=0`).

### URL → row resolution

```php
// Given view.php?wid=<wikiid>&title=<slug>&group=<g>&uid=<u>
$sw   = $DB->get_record('wiki_subwikis', ['wikiid' => $wikiid, 'groupid' => $g, 'userid' => $u]);
$page = $DB->get_record('wiki_pages', ['subwikiid' => $sw->id, 'title' => $slug]);
$vers = $DB->get_records('wiki_versions', ['pageid' => $page->id]);
// pick max (int)$v->version -> $v->content + $v->contentformat is the current page text
```

## Format constants

`FORMAT_MOODLE=0`, `FORMAT_HTML=1`, `FORMAT_PLAIN=2`, `FORMAT_WIKI=3` (deprecated), `FORMAT_MARKDOWN=4` — defined in `<webroot>/lib/weblib.php` (~lines 42-65). Both `wiki.introformat` and `wiki_versions.contentformat` use these. `introformat=4` = Markdown, so `*single asterisk*` in the intro renders as italics.

## Editing

- **Description:** `$DB->update_record('wiki', ...)` on `intro`/`introformat` (set `timemodified` too), then `cd <webroot> && moosh -n cache-clear`.
- **Page text:** prefer the UI. Direct DB writes must insert a new `wiki_versions` row at `version = max+1` and update page cache/timestamps, or UI/history desync. Never treat `wiki_pages.cachedcontent` as editable source.

## Verifying in the UI (login-gated site)

`<moodle-host>` is LTI-login-gated: any unauthenticated `curl` of a course URL 303s to `login/index.php` (or 404s "Error"). Don't burn time probing URL variations. Verify server-side instead:

```php
define('CLI_SCRIPT', true);
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['SCRIPT_NAME'] = '/admin/cli/check.php';
require_once('/var/www/html/config.php');
$wiki = $DB->get_record('wiki', ['id' => $wikiId]);
$html = format_text($wiki->intro, (int)$wiki->introformat);
echo $html;   // exactly what the course section / wiki view renders
```

`format_text()` works on CLI for Markdown/Moodle/HTML formats. Assert on the rendered HTML (`<em>`, `<ul>`/`<li>`, corrected phrases). Use **case-sensitive** `strpos()` for absence checks of old text — `stripos()` false-fails when the fix was only capitalization (old string is a case-variant substring of the new one).
