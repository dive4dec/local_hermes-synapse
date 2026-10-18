# Moosh Path Discovery — Session Diagnosis (2026-07-18)

## Problem
`moosh plugin-install marklar` returned "Could not find Moodle installation!" even though `/var/www/html/config.php` existed.

## Root cause chain

1. `~/.moosh/moosh.json` had `{"moodlepath":"/var/www/html/public"}` — Moosh **ignores this file entirely** for path discovery.
2. `moosh -m /var/www/html plugin-install marklar` exited 255 silently — `-m` flag is unreliable in v1.27.
3. `cd /var/www/html && moosh plugin-install marklar` still said "Could not find Moodle installation!" — `find_top_moodle_dir()` requires `config.php` + `version.php` + `install.php`, but `version.php` and `install.php` were missing from `/var/www/html/`.
4. Actual Moodle root is `/var/www/html/public/` where all three files exist.

## How Moosh discovers Moodle

Source: `/opt/moosh/includes/functions.php`

```php
function find_top_moodle_dir($dir) {
    $max = 10; // max levels up
    while (!$found) {
        if (is_top_moodle_dir($dir)) {
            return $dir;
        }
        if (++$up > $max || $dir == '/') {
            break;
        }
        $dir = dirname($dir);
    }
    return false;
}

function is_top_moodle_dir($dir) {
    return file_exists("$dir/config.php")
        && file_exists("$dir/version.php")
        && file_exists("$dir/install.php");
}
```

**Fix**: Always `cd /var/www/html/public` before running Moosh.

## Moosh `-m` flag silent failure
When `-m /var/www/html` is passed to a subcommand that requires BOOTSTRAP_FULL, it exits 255 with no stderr/stdout. This looks like a PHP fatal error in Moosh's bootstrap code.

## Moosh installation layout
- `/usr/local/bin/moosh` → symlink to `/opt/moosh/moosh.php`
- Helper functions: `/opt/moosh/includes/functions.php`
- Commands: `/opt/moosh/Moosh/Command/<version>/<Category>/`
