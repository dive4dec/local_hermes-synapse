---
name: moodle-math-delimiter-fix
description: "Fixes broken inline math rendering in Code Runner questions. Two approaches: enable $...$ in MathJax config (preferred) or batch-convert to \\\\(...\\\\)."
---

# Math Delimiter Fix for Code Runner Questions

## When to use

When a Code Runner question has broken inline math rendering, or the user asks to fix math delimiters in a specific question or course.

## Approach 1: Enable `$...$` in MathJax (PREFERRED)

The simplest fix — no data changes needed. MathJax 3/4 (used by Moodle 5.x) doesn't enable `$` delimiters by default. Set `mathjaxconfig` in `filter_mathjaxloader`:

```bash
moosh -p <webroot> -n sql-run "UPDATE mdl_config_plugins SET value = '{\"tex\": {\"inlineMath\": [[\"$\", \"$\"], [\"\\\\\\\\(\", \"\\\\\\\\)\\\"]]}}' WHERE plugin = 'filter_mathjaxloader' AND name = 'mathjaxconfig'"
```

This stores the JSON:
```json
{"tex": {"inlineMath": [["$", "$"], ["\\(", "\\)"]]}}
```

Then clear cache:
```bash
moosh -p <webroot> -n cache-clear
```

Moodle's mathjaxloader parses this via `JSON.parse()` and sets it as `window.MathJax = config` before loading the library. Both `$...$` and `\(...\)` work.

**Pros:** No data changes; all questions work immediately.
**Cons:** Small false positive risk (e.g. `$100`), but very low for CS programming courses.

### MathJax 4 config format

Moodle 5.2 uses MathJax 4. The `mathjaxconfig` uses `tex.inlineMath`, NOT `tex2jax.inlineMath` (which was MathJax 2.7).

### CRITICAL PITFALL: `additionaldelimiters` does NOT configure MathJax

The `additionaldelimiters` setting in `filter_mathjaxloader` is **only a hint** to tell Moodle whether MathJax should be loaded on a page. It is a comma-separated list of delimiter characters used for text-scanning, NOT MathJax's actual delimiter config. Setting it to anything has **no effect** on math rendering. The MathJax filter code at `filter/mathjaxloader/classes/text_filter.php` line 103 shows:

```php
$extradelimiters = explode(',', get_config('filter_mathjaxloader', 'additionaldelimiters'));
```

It only checks if any of those substrings appear in the text to decide whether to wrap content in `.nolink` spans. It does NOT configure MathJax's parsing.

## Approach 2: Batch-convert database (alternative)

When the database stores `\\(...\\)` (double backslash), Twig reduces it to `\(...\)` for MathJax. The database must store `\\(...\\)` because Code Runner question text passes through **Twig** first.

| Database stores | After Twig | MathJax | Result |
|---|---|---|---|
| `$X$` | `$X$` | — | ❌ broken |
| `\(`X`\)` | `(X)` | — | ❌ broken |
| `\\(X\\)` | `\(`X`\)` | renders | ✅ correct |
| `$$...$$` | `$$...$$` | renders | ✅ correct |

### Fix a single question

```bash
cat > <datadir>/temp/fix_math.php << 'PHPEOF'
<?php
define('CLI_SCRIPT', true);
require_once('<webroot>/config.php');
$questionid = (int)$argv[1];
$q = $DB->get_record('question', ['id' => $questionid]);
$text = $q->questiontext;
$new = preg_replace('/(?<!\$)\$([^$]+)\$(?!\$)/', '\\\\($1\\\\)', $text);
if ($new !== $text) {
    $update = new stdClass();
    $update->id = $questionid;
    $update->questiontext = $new;
    $DB->update_record('question', $update);
    echo "Fixed question $questionid\n";
} else {
    echo "No changes needed\n";
}
PHPEOF
php <datadir>/temp/fix_math.php QUESTION_ID
```

## Discover questions with broken math delimiters

See `moodle-question-course-mapping` for correct question-to-course queries.

```sql
-- Find all coderunner questions with $...$ inline math
SELECT q.id, q.name
FROM mdl_question q
WHERE q.qtype = 'coderunner'
  AND q.questiontext REGEXP '(?<![$])[$][^$]+[$](?![$])'
```

**Do NOT join `mdl_question_coderunner_options`** — cloned questions can be missing that row, silently dropping them from results.

### Hidden `$$x$$` MathJax triggers

Some questions contain `<span style="display:none">$$x$$</span>` at the end — this is a common Moodle trick to force MathJax to load, NOT broken inline math. MySQL's REGEXP can match `$x$` inside `$$x$$` (the first pair of dollars), producing false positives. Verify with HEX dump before claiming a question is broken.

## Pitfalls

- **NEVER use `moosh sql-run`** for backslash-heavy updates — shell escaping mangles backslashes. Always use a PHP script.
- **Only inline `$...$` needs conversion** — `$$...$$` display math is already correct.
- **Verify with PHP**, not moosh — `json_encode()` output shows exact stored bytes.
- **Hidden `$$x$$` triggers** can be mistaken for broken math. Check the HEX dump.
