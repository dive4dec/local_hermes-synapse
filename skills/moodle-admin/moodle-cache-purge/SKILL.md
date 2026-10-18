---
name: moodle-cache-purge
description: "Purge Moodle caches after making database changes so changes are visible in the UI. Covers course_modinfo, question caches, requirejs, and more."
---

# Moodle Cache Purge

Moodle caches aggressively. After making database changes (raw SQL, direct INSERT/UPDATE), the UI will not reflect changes until caches are purged.

## Quick purge (most common)

```bash
cd /var/www/html/public && moosh -n cache-clear
```

This clears Moodle's general caches and is usually sufficient for most changes.

## When `moosh cache-clear` isn't enough

### Course section changes (visible, name, sequence)

Course structure is cached in the `coursemodinfo` cache. After changing sections via SQL:

```php
// Via moosh php-eval:
cd /var/www/html/public && moosh -n php-eval "
cache_helper::purge_by_event('changesincourse');
cache::make('core', 'coursemodinfo')->purge();
"
```

Or use the Moodle API directly (preferred — handles cache automatically):

```php
cd /var/www/html/public && moosh -n php-eval "
require_once(\$CFG->dirroot . '/course/lib.php');
set_section_visible(3, 1, 0);  // courseid, sectionnumber, visibility
"
```

### Question bank changes (new questions, category changes)

```php
cd /var/www/html/public && moosh -n php-eval "
cache_helper::purge_by_event('changesincourse');
"
```

### Static files (JS, CSS, theme changes)

```php
cd /var/www/html/public && moosh -n php-eval "
purge_all_caches();
"
```

## Full purge (nuclear option)

```php
cd /var/www/html/public && moosh -n php-eval "
cache_helper::purge_reset();
purge_all_caches();
"
```

## Cache events

| Event name | Use case |
|---|---|
| `changesincourse` | Section changes, activity changes, module adds/removes |
| `changesincoursecat` | Course category changes |
| `clearfilecache` | File/asset changes |
| `changesinquestionbank` | Question/category changes |

## How to purge by event

```php
cache_helper::purge_by_event('changesincourse');
```

## Rule of thumb

**After any raw SQL change to Moodle tables, always purge caches before telling the user it's done.** The user cannot verify the change otherwise.

```bash
cd /var/www/html/public && moosh -n cache-clear
```

Or if that doesn't work:

```bash
cd /var/www/html/public && moosh -n php-eval "cache_helper::purge_reset(); purge_all_caches();"
```

## Pitfalls

- **`moosh cache-clear`** works for general caches but may not invalidate `coursemodinfo` specifically — if sections still appear after cache-clear, use `moosh php-eval`.
- **OPcache**: PHP-FPM holds stale bytecode. After plugin code or prototype changes, `cache-clear` is insufficient — requires pod restart.
- **RequireJS cache**: Moodle 5.x caches AMD builds. After plugin JS changes, use `purge_all_caches()`.
