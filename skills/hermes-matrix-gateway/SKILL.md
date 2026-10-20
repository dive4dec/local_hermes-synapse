---
name: hermes-matrix-gateway
description: "Set up or troubleshoot the Matrix/Element gateway for Hermes Agent on this pod (<moodle-host>). Exact dependency pins (musl host, E2EE off), .env config, gateway control script, Element room-creation trap, device/verification hygiene. Use when connecting Hermes to Matrix, when the gateway log says 'Matrix: required packages not installed', when Matrix messages silently fail to arrive, or when the user logs the bot in from a new device and gets an Element verification prompt."
---

# Hermes Matrix Gateway Setup (this pod)

Full procedural runbook: <datadir>/.hermes/matrix-gateway-runbook.md (proven end-to-end 2026-08-25). Read it first; this skill carries the environment-specific truths for this pod and verified deltas the runbook leaves implicit.

## Current-state check (do this first)
- `grep -c '^MATRIX_' $HERMES_HOME/.env` — 0 = not configured yet.
- `hermes-gateway-control.sh status` — stopped/running.
- `./venv/bin/python -c "from tools.lazy_deps import feature_missing; print(feature_missing('platform.matrix'))"` — empty tuple = deps ready.

## Environment facts (they decide what is possible)
- Pod is musl (Alpine, Kubernetes, www-data, non-root, no C toolchain). E2EE is impossible: python-olm ships glibc wheels only. Run plaintext; do NOT set MATRIX_ENCRYPTION / MATRIX_E2EE_MODE.
- Matrix plugin is bundled: <venv>/lib/python3.12/site-packages/plugins/platforms/matrix/ — no separate install.
- Gateway is managed by <webroot>/local/hermesagent/hermes-gateway-control.sh (never run `hermes gateway run` in foreground — it blocks forever).
- Log: $HERMES_HOME/logs/gateway.log (does not exist until first start).

## Dependency pins (the part that breaks if wrong)
- Source of truth is the `LAZY_DEPS["platform.matrix"]` tuple in <venv>/lib/python3.12/site-packages/tools/lazy_deps.py — read it LIVE before installing (pins drift on `hermes update`; the runbook's step-1 pin list can lag). 2026-08-25 pins: mautrix[encryption]==0.21.0, aiosqlite==0.22.1, asyncpg==0.31.0, aiohttp-socks==0.11.0, aiohttp==3.14.1.
- On musl install BASE mautrix without the [encryption] extra:
  ./venv/bin/pip install mautrix==0.21.0 aiosqlite==0.22.1 asyncpg==0.31.0 aiohttp-socks==0.11.0 aiohttp==3.14.1 Markdown
  The checker (_is_satisfied) validates bare name + version only, so mautrix==0.21.0 satisfies the mautrix[encryption]==0.21.0 spec without ever attempting the impossible python-olm build.
- Pre-install BEFORE first gateway start. The adapter's lazy install runs prompt=False, so a missing package at startup just logs "Matrix: required packages not installed" and the platform never connects.
- The aiohttp pin may downgrade an existing aiohttp (3.14.3 → 3.14.1 happened). Check `pip show aiohttp` → Required-by first (only edge-tts consumed it; safe). pip's uninstall can leave a `~iohttp` temp dir in site-packages with NFS "Resource busy" .nfs* files — harmless (real package dir intact), NFS reclaims them; don't fight it.

## .env configuration
- $HERMES_HOME/.env is credential-store protected: read_file tool is refused; inspect via terminal (`grep -oE '^[A-Za-z_][A-Za-z0-9_]*' .env` shows keys without values).
- Append: MATRIX_HOMESERVER (default https://matrix.org), MATRIX_USER_ID (@bot:server), MATRIX_PASSWORD (or MATRIX_ACCESS_TOKEN instead — then USER_ID is optional, learned via whoami), MATRIX_ALLOWED_USERS (comma-separated user ids), MATRIX_DEVICE_ID=HERMES01. Pin the device id — with password login, omitting it mints a NEW device on every gateway restart. `chmod 600 .env` after.
- Optional: MATRIX_HOME_ROOM (cron/notification delivery room). MATRIX_REQUIRE_MENTION defaults true in rooms; DMs always work.

## Start and verify
- Pod rebuilds reset exec bits — `chmod +x` the control script. Symptom of the miss: `status` fails with "Permission denied".
- `hermes-gateway-control.sh start`, then gateway.log must show:
  Matrix: logged in as @bot:server
  Matrix: initial sync complete, joined N rooms
  ✓ matrix connected
- Harmless: "rejecting invite ... from unauthorized user" (server's official-account room), "Failed to deserialize ... SecretStorageDefaultKeyEventContent" (old Element account data).

## Element side (the trap that eats messages silently)
- Do NOT use the "send a direct message / DM the bot" flow — on matrix.org it auto-creates an E2EE-encrypted room. With E2EE off on the bot, messages arrive as undecryptable blobs and are silently dropped: no error, no reply, nothing in the log.
- Element has no option to disable encryption on an existing room; it is locked in at creation.
- Correct flow: + → New room (not DM) → add @bot:server → when asked "end-to-end encrypt?" choose **Don't encrypt** (default is Yes — that's the trap) → send `@bot hi` (@mention required in rooms).
- Bot auto-joins invites from allowed users (log: "invited to ... — joining").

## One-time device hygiene
- matrix.org quirk: `DELETE /devices/<id>` returns M_UNRECOGNIZED (device deletion broken server-side, re-confirmed 2026-08-25). Clean leftover diagnostic devices in Element UI: log in as the bot → Settings → Security & Privacy → Devices → delete all except the pinned HERMES01 and your own client. (On a different server try the API first — the route may work there.)
- Every password login (Element or API) mints a device, so user login attempts from a new device show up here too.
- New-device verification is a dead end on this account: it has NO cross-signing keys and NO recovery key (checked 2026-08-25). When the user hits Element's "Verify your identity" after a new login, neither "verify with another device" (headless HERMES01 can't do the SAS/emoji dance) nor "enter recovery key" (doesn't exist) works. Advise: skip/dismiss the banner — harmless since rooms are plaintext. The only path to a trusted session is "Set up security / create recovery phrase" on that device; if the user creates one, record the key so future logins verify properly.
- Probe account device & security state with `scripts/matrix_device_probe.py` (stdlib only, reads MATRIX_* from .env, idempotent via pinned DIAG01 device) — use it before advising, so claims about cross-signing/recovery key are verified, not assumed.

## Credentials flow (who provides what)
- User supplies: bot user id + bot password (or access token), and their own user id for MATRIX_ALLOWED_USERS. Hermes side does the .env edit, gateway start, and log verification. User does the one-time Element room creation.
