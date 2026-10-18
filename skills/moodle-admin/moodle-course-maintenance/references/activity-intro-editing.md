# Editing an activity's description text (intro field)

Procedure distilled from editing the wiki "Agentic Coding Assignment" description in <coursecode> (wiki id=1, CM 663, section 105).

## Where activity description text lives

Every core module stores its "description" in `mdl_<mod>.intro` with a companion `mdl_<mod>.introformat` (int) column. `mdl_label` uses the same convention. The user-facing URL (e.g. a wiki `create.php?wid=...`) points at the **instance table** (`wiki`, `assign`, `forum`, ...), not at `course_modules` — so "the description the user sees on that page" is usually `<instance_table>.intro`.

## Format constants (Moodle)

| Value | Constant | Notes |
|---|---|---|
| 0 | FORMAT_MOODLE | Editor text (markdown-ish) |
| 1 | FORMAT_HTML | Raw HTML |
| 2 | FORMAT_PLAIN | Plain text |
| 3 | FORMAT_WIKI | Deprecated |
| 4 | FORMAT_MARKDOWN | **Markdown** — `*text*` renders as `<em>text</em>` |

Single-asterisk italics in a Markdown intro are intentional emphasis, not a typo — don't "fix" them.

## Editing workflow

1. Locate the instance row: `$DB->get_record('<mod>', ['id' => <instance from CM or URL param>])`
2. Print the full current `intro` and identify each error precisely.
3. Present changes as a before → after table; **wait for explicit confirmation** (user's standing rule for data changes).
4. In one PHP script, apply replacements with a **strict occurrence guard**:

```php
$pairs = [['a python package', 'a Python package'], /* ... */];
$new = $old;
foreach ($pairs as [$from, $to]) {
    if (substr_count($new, $from) !== 1) {
        fwrite(STDERR, "Expected exactly one match for: $from\n");
        exit(1);
    }
    $new = str_replace($from, $to, $new);
}
$record->intro = $new;
$record->timemodified = time();
$DB->update_record('<mod>', $record);
```

The hard-fail on `substr_count !== 1` prevents double-application or silent no-ops when the same fix is retried.

5. `cd <webroot> && moosh -n cache-clear`
6. **Verify rendering** — see below.

## Verifying when the live site is login-gated

`<moodle-host>` sits behind LTI login — anonymous `curl` returns the login/error page regardless of URL, so you cannot scrape rendered HTML. Two options:

- **Strongest available check:** render the stored text through Moodle's own renderer in a CLI script:

```php
global $USER; $USER = get_admin();          // REQUIRED — see gotcha below
$html = format_text($record->intro, (int)$record->introformat, ['noclean' => true]);
echo $html;
```

  **Gotcha (verified 2026-09-02): `format_text()` in CLI applies NO filters at all without a logged-in user.** A bare bootstrap script (no `$USER`) returns the text 100% unfiltered — no `urltolink` URL links, no `activitynames` autolinks, nothing — which looks exactly like "the filter change broke rendering" and can send you down a false-alarm investigation (this happened when disabling `urltolink` per-activity: the no-user render showed every URL AND every activity name unlinked, even in unmodified contexts). Always set `$USER = get_admin()` before any filter-rendering verification, and diff the rendered output of a MODIFIED context against an UNMODIFIED control context in the same run — if both look identical and unfiltered, the script is missing the user, not the site.

  Then assert the new substrings are present and the old ones absent, and that intended markup (e.g. `<em>...</em>`) survived. Tell the user honestly that a human UI check is still warranted because the live page couldn't be fetched.
- **Know which "error" you're seeing when curling the login-gated site:** anonymous GETs to `/`, `course/section.php?id=...` return a clean 303 → `login/index.php` (expected). Wiki-specific URLs fail differently: `view.php?w=1` (missing `id`/`title`) throws `invalidparameters` → HTTP 404 "Error | <coursecode>" page; `index.php?id=<cmid>` treats `id` as a **course** id → 303 to `overview.php?id=<cmid>` → 404. Canonical logged-in wiki URLs: `view.php?id=<cmid>` or `view.php?wid=<wikiid>&title=<PageTitle>`.
- Do NOT reach for stored service tokens to curl as a logged-in user — out of scope for normal edits.

## Pitfalls

- **`$DB->get_fields()` and `$DB->describe_table()` are undefined** in this environment (mariadb native driver). To learn a table's columns, read the plugin's `db/install.xml` instead.
- **Plugin path gotcha:** `config.php` is at `/var/www/html/config.php`, but plugins live under `<webroot>/mod/<mod>/` (and `<webroot>/local/...`). Don't probe `/var/www/html/mod/...` — it doesn't exist.
- **Wrong column name = generic error:** querying a nonexistent column (e.g. `wiki_pages.suburbid` when the real column is `subwikiid`) produces the bare `!!! Error reading from database !!!` with no hint. On a read failure, suspect the column/field name first and check `install.xml`.
- **Community wiki plugin (2025 version) schema differs from core's old one:** pages link to subwikis via `wiki_pages.subwikiid`; page *content* is NOT on `wiki_pages` (only `cachedcontent` lives there) — the editable text is in `wiki_versions` (latest `version` per `pageid`), each with its own `contentformat`. `wiki_suburbs` does not exist in this version.
- **No pages yet ≠ broken wiki:** an unstarted collaborative wiki has 0 rows in `wiki_subwikis` and `wiki_pages` until a student creates the first page. The activity description (intro) is still fully editable and visible from the wiki's own page.
- **Verification assertions — case sensitivity trap:** when asserting an *old* string is gone, use case-sensitive `strpos()`, not `stripos()`. Checking `stripos($html, 'a python package') === false` FAILS on the corrected text because "a **P**ython package" still matches case-insensitively. Only the case-sensitivity of the fix is the point, so the absence check must be `strpos()`. (Same for markup checks: assert the exact `<em>...</em>` tags, and for list checks use a non-greedy regex like `/<ul>\s*(<li>.*?<\/li>\s*){4}<\/ul>/s` — a naive `(<li>){4}` misses inter-element whitespace.)
- **Punctuation collision when inserting phrases:** if the inserted fragment carries its own trailing punctuation (e.g. `", e.g. [link](url),"`), the original sentence may already end with a comma/period, producing `,,` or `..` artifacts in the saved text. Either include the boundary punctuation inside the matched `from` string, or before saving assert the result is clean: `strpos($new, ',,') === false && strpos($new, '..') === false` (exit 1 on failure). The sliveshow hyperlink round shipped a `),,` in bullet 1 that was caught in output review and fixed in a second guarded pass.
- **Verify links before embedding:** before adding a hyperlink to course content, confirm each URL is live: `curl -s -o /dev/null -w "%{http_code}" -L <url>` (expect 200; follow redirects). For URLs with a `#fragment`, additionally fetch the page and grep the HTML for `id="<fragment>"` — Jupyter Book/MyST pages expose heading anchors as `id="..."` attributes, so this confirms the fragment lands on a real section rather than silently dropping to top-of-page.
