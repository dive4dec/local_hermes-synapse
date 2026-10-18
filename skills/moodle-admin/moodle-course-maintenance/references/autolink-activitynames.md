# Activity-name autolinks (`filter/activitynames`) — why course text links itself

Moodle's **activitynames** filter automatically wraps any activity's *title* that
appears in course text (labels, pages, quiz intros, forum posts, ...) in an
`<a class="autolink" title="NAME" href=".../view.php?id=CMID">NAME</a>` tag. This is
why prose like "Safe Exam Browser" showed a link — **not on "Safe Exam Browser", but on
the whole word "Exam"**, which is the title of the **Exam** quiz. It is enabled by
default and is usually not per-context toggled on this site.

This bites in two task classes:
1. **"Why is this word linked to the wrong activity?"** (diagnosis)
2. **A string rename that changes which link fires** — e.g. "Safe Exam Browser" → "SEB"
   flips the autolink from the Exam quiz to the SEB *page* (verified 2026-08-29, CE-Quiz
   instructions in cs1302a_26a).

## Matching rules (`filter/activitynames/classes/text_filter.php` + `lib/filterlib.php`)

- **Whole-word, case-insensitive.** The phrase is built as a `filterobject(..., fullmatch=true)`
  → `\b` word-boundary assertions at the start/end (only if the name starts/ends with a word
  char). So "SEB" links only when it stands alone; "Exam" inside "Safe **Exam** Browser"
  matches because it is a whole word.
- **Longest name wins first.** Candidate activities are sorted by name length (reverse) before
  matching, so "Mock Exam (25A)" is tried before "Exam". After a match the filter re-scans.
- **Only linkable targets:** a CM qualifies iff `visible && has_view() && uservisible &&
  course_modinfo::is_mod_type_visible_on_course(modname)`. Hidden/restricted activities are
  NOT autolink targets — so a phrase can fail to link if its target activity is hidden.
- **No self-link.** When rendering inside a module's own context, that module's own name is
  removed from the candidate list (a quiz won't autolink to itself).
- **Suppressed regions** (never autolinked, from the `filter_phrases()` ignore-tag list):
  `<nolink>…</nolink>`, `<span class="nolink">…</span>`, `<a>…</a>`, `<script>`,
  `<textarea>`, `<select>`, `<head>`. **This is the escape hatch** — wrap the phrase in
  `<span class="nolink">` to kill its autolink (already done on the SEB page id=12 and the
  "Quiz for testing SEB" intro id=55).
- **Spaces in the name become a whitespace class** (`(?:[\s\xC2\xA0]{n}`) so an activity
  name typed with a double-space / NBSP still matches.
- The anchor text is the *matched substring* (not the full name): "Safe **Exam** Browser"
  links only the word "Exam", leaving "Safe " and " Browser" plain. href = `$cm->url`.

## Empirical before/after verification (the reliable check)

`dive.cs.cityu.edu.hk` is login-gated (anonymous curl → login), so you cannot scrape the
rendered page. The decisive check is to render the stored text through Moodle's own filter
chain in a CLI script. **You MUST pass a module (or course) context AND have a logged-in
user** — the activitynames filter does `$context->get_course_context(false)` and returns the
text *untouched* if there's no course context, so `format_text($t, FORMAT_MOODLE)` with
**no** context shows NO autolinks and gives a false "nothing links" result. Worse (verified
2026-09-02): with a context but **no `$USER`**, the ENTIRE filter chain is skipped — the
text comes back 100% unfiltered (no autolinks, no urltolink URL links), which can masquerade
as "my change killed the autolinks". If a render shows no filters at all, check the script
has a user BEFORE suspecting the change, and always diff a modified context against an
unmodified **control** context in the same logged-in run.

```php
define('CLI_SCRIPT', true); define('MOODLE_INTERNAL', true);
require('/var/www/html/public/config.php');
require_once('/var/www/html/public/lib/setup.php');
global $USER; $USER = get_admin();          // needed for has_view()/uservisible checks
$ctx = context_module::instance(<CMID>);    // any CM in the course; ideally the one you're editing
echo format_text('students must use the **SEB on a Lab PC** to do the test.',
                 FORMAT_MOODLE, ['context' => $ctx, 'noclean' => false]);
```

Read the emitted `<a class="autolink" title="X" href="...">` tags. For a rename that is
*intended* to move the link, confirm `href`/`title` now point at the right CM.
Verified 2026-08-29 (CE-Quiz intros, cmid 146 context):
- OLD `**Safe Exam Browser on a Lab PC**` → `Safe <a class="autolink" title="Exam"
  href=".../mod/quiz/view.php?id=108">Exam</a> Browser on a Lab PC`
- NEW `**SEB on a Lab PC**` → `<a class="autolink" title="SEB"
  href=".../mod/page/view.php?id=191">SEB</a> on a Lab PC`

## Before/after a rename that could change autolinks

1. Sweep for occurrences first (see `rename-string-sweep.md`).
2. For each distinct old/new string, check whether it **equals or contains a whole-word
   activity name** in the course. Eyeball the visible CM names, or just render a sample line
   with `format_text()` (above) before and after.
3. If the rename is *supposed* to (re)target a link: confirm the new phrase is a **visible**
   activity named **exactly** that string (e.g. the SEB *page* is named "SEB", visible=1,
   uservisible=1) so it actually autolinks where you want. A hidden or differently-cased
   target will not link.
4. If the rename is *not* supposed to change links but a collision appears: wrap the phrase
   in `<span class="nolink">…</span>` (or rename the colliding activity).
5. Apply, `moosh -n cache-clear`, re-render to confirm, then show the user the exact
   before/after `<a>` tags you observed (labelled list, no table — Matrix).

## Env gotchas

- **`is_enabled_filter()`, `filter_setup()` are undefined** here, and a naive
  `mdl_filters` / `mdl_filter_instances` query errored. Don't probe filter *state* that way —
  just empirically render; if the autolink shows up in the `format_text()` output, the filter
  is active.
- The filter class is at `filter/activitynames/classes/text_filter.php`; `filter_phrases()`
  and the ignore-tag list are in `lib/filterlib.php` (~line 848+).
- Autolinking is a **rendering** property — it only runs through `format_text()`, not when you
  read the raw `intro`/`content` column. So "is it linked?" is answered by rendering, never
  by reading the stored text.
