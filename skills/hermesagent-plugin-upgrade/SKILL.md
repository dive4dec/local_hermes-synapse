---
name: hermesagent-plugin-upgrade
description: Upgrade the local_hermesagent Moodle plugin to a new release. Covers safe file replacement, config preservation, and the critical Moodle database upgrade step.
---

# Upgrading local_hermesagent

Upgrades the plugin the agent runs inside. The plugin config/data (`~/.hermes/`) is completely separate from plugin files and must be preserved.

## Trigger

## Trigger
User wants to upgrade local_hermesagent to a newer release version.
## Recommended approach: moosh install_plugin

Use `moosh` — it uses Moodle's real PHP API, handles permissions, DB upgrades, and cache purging correctly:

1. **Download the release zip** from GitHub releases:
   ```
   curl -LO https://github.com/dive4dec/local_hermesagent/archive/refs/tags/v<VERSION>.zip
   ```

2. **Install via moosh** (uses Moodle's full plugin installer internally):
   ```
   moosh install_plugin /path/to/v<VERSION>.zip
   ```

3. **Restart gateway/bridge daemons** if the release includes backend changes:
   ```
   /var/www/html/public/local/hermesagent/hermes-gateway-control.sh restart
   /var/www/html/public/local/hermesagent/hermes-bridge-control.sh restart
   ```

4. **Verify config survived** — `~/.hermes/` is outside the plugin directory and should be untouched:
   ```
   ls /var/www/moodledata/.hermes/config.yaml
   ```
## Pitfalls
- **Never manually extract and copy files** — this bypasses Moodle's permission handling and DB upgrade, leading to 404s on static assets and stale plugin versions. Always use `moosh install_plugin`.
 - The plugin directory is a broken git submodule (no usable `.git` or parent modules config). `git pull` won't work.
 - Never touch `~/.hermes/` during upgrade. Config, memories, skills, and session data all live there.
