---
name: moodle-plugin-install
description: "Install Moodle plugins using moosh, handle upgrade registration, and verify installation. Covers the full workflow from version lookup to DB registration."
---

# Moodle Plugin Installation

## Workflow

### 1. Check latest compatible version

```bash
cd /var/www/html/public && moosh -n plugin-list -v 2>&1 | grep -i <plugin_name>
```

The `-v` flag shows versions. This downloads `~/.moosh/plugins.json` from moodle.org. Without `-v`, `plugin-list` may loop infinitely if the cached JSON is stale.

**If it loops**, seed the cache first:
```bash
curl -s -A "Moosh/1.27" https://download.moodle.org/api/1.3/pluglist.php \
  -o /home/www-data/.moosh/plugins.json
```

Output format: `plugin_name,version,latest_version,download_url`

### 2. Install with moosh

```bash
cd /var/www/html/public && moosh -n plugin-install -f <plugin_name>
```

Always use `-f` — Moodle 5.2 is too new for most plugins' version checks, and they refuse without force.

### 3. Verify files landed correctly

```bash
# aiprovider_* plugins go to ai/provider/
ls /var/www/html/public/ai/provider/<name>/version.php

# local_* plugins go to local/
ls /var/www/html/public/local/<name>/version.php
```

Fix ownership if needed:
```bash
chown -R www-data:www-data /var/www/html/public/ai/provider/<name>
```

### 4. Purge caches and run upgrade

```bash
cd /var/www/html/public && moosh -n php-eval "purge_all_caches();"
```

### 5. Check if it auto-registered

```bash
cd /var/www/html/public && moosh -n sql-run "SELECT * FROM mdl_config_plugins WHERE plugin = '<plugin_component>'"
```

If empty, the plugin didn't register automatically (see Pitfalls below).

## Manual DB Registration

If the plugin shows in "To be installed" but won't install, register it manually:

```bash
cd /var/www/html/public && moosh -n php-eval "
global \$DB;
\$DB->insert_record('config_plugins', ['plugin' => '<component>', 'name' => 'version', 'value' => '<version_int>']);
purge_all_caches();
echo 'Done';
"
```

Replace `<component>` with the frankenstyle name (e.g., `aiprovider_openaicompatible`) and `<version_int>` with the integer version from `version.php`.

## Installing from GitHub (when not in moodle.org catalog)

Some newer releases haven't propagated to moodle.org's plugin API. Check GitHub first:

```bash
curl -sL "https://api.github.com/repos/<owner>/<repo>/releases/latest" | grep -E '"tag_name"|"name"'
```

If the GitHub version is newer than `moosh plugin-list -v`:

1. **Download** using the zipball URL (no assets are usually uploaded):
```bash
curl -sL -o /tmp/plugin.zip "https://api.github.com/repos/<owner>/<repo>/zipball/<tag>"
head -c 2 /tmp/plugin.zip | xxd  # Should show "PK" for a valid ZIP
```

2. **Extract** (GitHub zipball wraps files in an `owner-repo-commit` directory):
```bash
mkdir -p /tmp/extract && unzip -o /tmp/plugin.zip -d /tmp/extract
```

3. **Copy to the correct plugin directory**:
```bash
cp -r /tmp/extract/<unpacked-dir> /var/www/html/public/mod/<pluginname>   # for mod_*
chown -R www-data:www-data /var/www/html/public/mod/<pluginname>
```

4. **Purge and register** (see "Manual DB Registration" above):
```bash
cd /var/www/html/public && moosh -n php-eval "purge_all_caches();"
# Then insert into mdl_config_plugins as shown above
```

## Pitfalls

### `admin/cli/upgrade.php` only handles core Moodle
Running `php admin/cli/upgrade.php --non-interactive` reports "No upgrade needed" even when new plugins are pending. It only checks the core Moodle version. Plugins must be registered via the web UI upgrade page or manually in the DB.

### `plugin-list` without `-v` may loop
Without `-v`, `plugin-list` can enter an infinite loop when `plugins.json` is stale or corrupted. Always use `-v` flag, or seed the cache with curl first.

### `cache_helper::purge_reset()` doesn't exist in Moodle 5.x
Use `purge_all_caches()` instead.

### Plugin directory structure
Moodle 5.x uses `TYPE/SUBTYPE/name/` for some plugin types:
- `aiprovider_*` → `ai/provider/<name>/`
- `local_*` → `local/<name>/`
- `mod_*` → `mod/<name>/`

### Plugin version must be higher than DB version
If the plugin already exists in `mdl_config_plugins` with a higher version, bump `$plugin->version` in `version.php` before reinstalling.

### cURL security blocks non-standard ports
Moodle blocks outbound cURL/Guzzle requests to ports other than 80 and 443 by default. If an AI provider endpoint uses a non-standard port (e.g., 8000), the request is silently blocked with "Something Went Wrong". Fix:

```bash
cd /var/www/html/public && moosh -n sql-run "UPDATE mdl_config SET value = '443\n80\n8000' WHERE name = 'curlsecurityallowedport'"
```

Or via **Site admin → Security → HTTP Security → Allowed ports**. Don't forget to purge caches after.

### cURL security also blocks internal IPs
Private IP ranges (10.x, 172.16-31.x, 192.168.x) and Kubernetes service DNS names are blocked. If your AI endpoint resolves to a private IP, the same "Blocked The URL is blocked" error occurs even with the port whitelisted. Use a public-facing hostname or add the host to the block exception list.
