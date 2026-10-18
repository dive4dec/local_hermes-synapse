# Rename a string across an entire course (verified 2026-08-28)

Task class: "rename OPTMentor to OPT_Mentor in course X" — a string used as a
display name, in prose, in URLs, and as part of uploaded filenames. The danger is
changing the wrong subset: breaking image refs, URLs, or missing quiz/label prose.

## Step 1 — Occurrence sweep (READ-ONLY, before proposing anything)

Count "standalone" occurrences — matches NOT immediately followed by `_`, so
filename hits (`OPTMentor_main_page.jpg`) are classified separately:

```php
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php');
require_once('/var/www/html/public/lib/setup.php');
global $DB;
function count_standalone($text) {
    if (!is_scalar($text)) return 0;
    return preg_match_all('/OLDNAME(?!_)/', (string)$text);
}
foreach ($DB->get_records('label', ['course' => $COURSE]) as $l)
    if (count_standalone($l->intro)) echo "label#{$l->id} {$l->name}\n";
foreach ($DB->get_records('page', ['course' => $COURSE]) as $p) {
    $n = count_standalone($p->name) + count_standalone($p->intro) + count_standalone($p->content);
    if ($n) echo "page#{$p->id} ({$p->name}) x$n\n";
}
foreach ($DB->get_records('quiz', ['course' => $COURSE]) as $q)
    if (count_standalone($q->intro)) echo "quiz#{$q->id} ({$q->name})\n";
// also: assign (intro,name), url (intro,name,externalurl), forum (intro,name),
// forum posts:  SELECT ... FROM mdl_post WHERE courseid=$COURSE AND module='forum' AND content LIKE '%OLDNAME%'
// question banks: per quiz CM → contextlevel=70 instanceid=cmid → question_categories (contextid, then parent)
//                → mdl_question WHERE parent=$catid  (NOT `category` — see MCP query skill)
```

Classify every hit into: **(a) display name**, **(b) prose mention**, **(c) URL**,
**(d) uploaded filename**. Only (a)+(b) get replaced; (c) often already uses the
new form; (d) must never be text-replaced — check real files exist first:

```php
$DB->get_records_sql("SELECT id, filename FROM mdl_files WHERE filename LIKE :x",
    ['x' => '%OLDNAME%']);
```

## Step 2 — Propose + confirm

Present the classified list (count per location) and wait for explicit user
confirmation. Note siblings: the same string usually exists in the other live
courses too (cs1302_25b=2, cs1302a_26a=3, cs1302_26a=7) — run the sweep
sitewide and tell the user, but only change what was confirmed.

## Step 3 — Apply (PHP bootstrap, per field)

```php
function fix($text) { // negative lookahead protects OLDNAME_*.jpg filenames
    $n = preg_match_all('/OLDNAME(?!_)/', (string)$text);
    return [preg_replace('/OLDNAME(?!_)/', 'NEWNAME', (string)$text), $n];
}
[$new, $n] = fix($record->field);
if ($n) {
    $DB->set_field('table', 'field', $new, ['id' => $id]);
    $DB->set_field('table', 'timemodified', time(), ['id' => $id]); // bump for UI/cache
}
```

Apply to: `page.name`, `page.content`, `label.intro`, `quiz.intro` — exactly the
locations the sweep reported. Do NOT touch `mdl_files` rows or URL strings.

## Step 4 — Verify + cache

1. Re-run the sweep: expect **0 standalone OLDNAME** in the course.
2. Confirm the NEW name in the title rows, and that image refs still contain the
   old filename (intentionally unchanged):
   `preg_match_all('/@@PLUGINFILE@@\/(\S+\.jpg)/', $content, $m)`
3. Optional render check: `format_text($content, FORMAT_MARKDOWN, ['context' => $ctx])`.
4. `cd /var/www/html/public && moosh -n cache-clear`

## Gotchas found while doing this

- **Renaming can silently change autolinks.** If the old or new string equals/contains a
  whole-word activity name, Moodle's `activitynames` filter re-targets (or kills) the link
  that word produces. E.g. "Safe **Exam** Browser" → "SEB" flipped the autolink from the
  Exam quiz to the SEB page. Before applying, render a sample line before/after via
  `format_text($t, FORMAT_MOODLE, ['context' => context_module::instance(<cmid>)])` (a module
  context is REQUIRED — no context = no autolinks = false negative). Full mechanics + the
  `<span class="nolink">` escape hatch: **`references/autolink-activitynames.md`**.
- **moodle_db MCP `query` tool rejects `REPLACE()`** ("dangerous keyword") — counting
  via `(LENGTH(x)-LENGTH(REPLACE(x,'a','')))/n` won't work there; do it in PHP.
- `mdl_question` has **no `category` column** on this install — the FK is **`parent`**
  (`mdl_question.parent` → `mdl_question_categories.id`).
- `mdl_course` has **no `deleted` column** — `WHERE deleted = 0` errors; courses are
  hard-deleted, just `SELECT id FROM mdl_course ORDER BY id`.
- `mdl_post` (Moodle 5.x) text column is **`content`** (no `message`/`fullmessage`);
  filter `module='forum'` + `courseid`.
- Page intros of "OPTMentor"-style pages already contain the NEW-style URL
  (`/OPT_Mentor/`) — URL hits are pre-existing-correct, don't "fix" them.
