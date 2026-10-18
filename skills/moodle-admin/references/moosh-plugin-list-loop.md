# Moosh `plugin-list` Failures

## Problem

`moosh plugin-list` is unreliable in this environment. Two distinct failure modes:

### 1. Invalid JSON / stale temp directory

**Error**: `Invalid JSON file, deleted /home/www-data/.moosh/plugins.json. Run command again.`

**Cause**: A previous plugin install left a partial extraction inside `local/_temp_<hash>/`. Moosh's plugin scanner treats it as a plugin and crashes, producing invalid data that gets written to `plugins.json`.

**Fix**:
```bash
find <webroot>/local -maxdepth 1 -name "_temp_*" -type d -exec rm -rf {} +
```

### 2. HTTP 403 from download.moodle.org

**Error**: Same "Invalid JSON file" message, but root cause is different.

**Diagnosis** (enable PHP errors to see the real cause):
```bash
php -d display_errors=1 -d error_reporting=E_ALL /usr/local/bin/moosh plugin-list 2>&1
# Warning: file_get_contents(https://download.moodle.org/api/1.3/pluglist.php): 
# Failed to open stream: HTTP request failed! HTTP/1.1 403 Forbidden
```

**Cause**: `download.moodle.org` returns 403 Forbidden to PHP's `file_get_contents()` (missing or filtered User-Agent). Moosh writes the 403 HTML response to `plugins.json`, which fails JSON parsing, so it deletes the file and gives up.

**Fix** — seed the file manually with curl:
```bash
curl -s -A "Moosh/1.27" https://download.moodle.org/api/1.3/pluglist.php \
  -o /home/www-data/.moosh/plugins.json
```

This works because curl sends a proper User-Agent header.

**Warning**: Moosh will re-download the file if it's older than 24 hours, which will trigger the same 403. This is a recurring problem. If `plugin-list` or `plugin-install` fails again after a valid cache was seeded, re-run the curl command above.

### Recommendation

**Do not use `plugin-list`** in this environment. Use `info-plugins` or `config-plugins` for listing installed plugins. Only use `plugin-list` as a prerequisite for `plugin-install`, and only after seeding the cache with curl.