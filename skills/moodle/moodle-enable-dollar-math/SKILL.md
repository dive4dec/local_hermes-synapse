---
name: moodle-enable-dollar-math
description: "Enables $...$ inline math delimiters in Moodle by configuring MathJax 3/4's mathjaxconfig. Alternative to converting all questions to \\\\(...\\\\)."
---

# Enable `$...$` Inline Math Delimiters in MathJax 3/4

## When to use

When Code Runner questions (or any Moodle content) use `$...$` for inline math and it doesn't render. This is an alternative to batch-converting all questions to `\\(...\\)`.

## Root cause

Moodle 5.x defaults MathJax 4 to only support `\( ... \)` for inline math and `$$...$$` for display math. Many older questions use `$...$` which isn't enabled by default.

## Fix

Set `mathjaxconfig` in `mdl_config_plugins` to tell MathJax 4 to accept `$...$`:

```bash
moosh -p <webroot> -n sql-run \
"UPDATE mdl_config_plugins SET value = '{\"tex\": {\"inlineMath\": [[\"$\", \"$\"], [\"\\\\\\\\(\", \"\\\\\\\\)\"]]}}'
 WHERE plugin = 'filter_mathjaxloader' AND name = 'mathjaxconfig'"
```

Then clear cache:
```bash
moosh -p <webroot> -n cache-clear
```

## How it works

- The `mathjaxconfig` setting is stored as JSON in `mdl_config_plugins`
- Moodle's JS loader reads it, parses it, and assigns it to `window.MathJax` before loading the MathJax script
- MathJax 4 then uses this config to determine which delimiters to recognize
- `"inlineMath": [["$", "$"], ["\\(", "\\)"]]` adds `$...$` alongside the existing `\(...\)`

## Reverting

```bash
moosh -p <webroot> -n sql-run \
"UPDATE mdl_config_plugins SET value = '' WHERE plugin = 'filter_mathjaxloader' AND name = 'mathjaxconfig'"
moosh -p <webroot> -n cache-clear
```

## Pitfalls

- **NOT the same as `additionaldelimiters`** — that field is only a hint for whether to load MathJax, not for configuring delimiter parsing.
- **`moosh sql-run` escaping** — `\\(` in the JSON requires `\\\\\\\\(` in the moosh shell command (4 levels of escaping: bash → moosh → MySQL → JSON).
- **OPcache** — if it still doesn't render after cache-clear, PHP-FPM may need a pod restart.

## MathJax 3/4 vs MathJax 2

MathJax 2 used `MathJax.Hub.Config({...})`. MathJax 3/4 uses `window.MathJax = {...}`. Moodle 5.x uses MathJax 4, so the config format must be the new one:

```json
{
  "tex": {
    "inlineMath": [["$", "$"], ["\\(", "\\)"]]
  }
}
```

Not:

```js
MathJax.Hub.Config({ tex2jax: { inlineMath: [['$', '$']] } });
```
