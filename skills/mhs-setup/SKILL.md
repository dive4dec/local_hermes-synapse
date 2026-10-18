---
name: mhs-setup
description: "Bootstrap the portable Moodle skill set: detect the Moodle version, gate on 5.2+, derive MHS_* environment variables from config.php / the DB, and persist them conflict-aware and idempotently. Run this FIRST before using any other skill in this repo, and re-run it after merging updated skills. Use when a skill reports a missing MHS_* var, when you land on a new course/site, or when the user asks to 'set up the moodle skills' or 'configure MHS'."
---

# MHS Setup (meta-skill)

This is the **bootstrap** for the whole portable skill set. Every other skill
in this repo reads its course/site-specific values from `MHS_*` environment
variables (see `skills/_conventions/PORTABLE.md` for the full scheme and the
read→default→ask→persist contract). `mhs-setup` is what *fills* those variables
from the live install, checks the Moodle version, and persists them safely.

**Run this once per site/course, and re-run it after merging updated skills.**
It is idempotent and safe to run repeatedly.

## 0. Invariants (non-negotiable)

- **Moodle 5.2+ only.** The skill set's assumptions (question-bank,
  `question_references`, versioned questions, `mdl_question_attempt_step_data`
  layout, quiz-engine behaviour, gradebook aggregation constants) are 5.2+.
  If the detected version is lower, **stop and warn** — do not proceed silently.
- **Never clobber.** A value already present in `$HERMES_HOME/.env` is never
  overwritten. Re-runs only fill what's missing (incremental merge).
- **Never guess credentials or IDs.** Course id, helpers-group id, host, IP
  ranges, and SMTP credentials come from the live source of truth or the user —
  never invented.
- **Read-only probe.** `mhs_probe.php` only reads; it never writes.

## 1. The scripts

- `scripts/mhs_probe.php [webroot]` — read-only. Boots Moodle from
  `config.php` and prints a JSON object: `version` (big Moodle int),
  `release`, `wwwroot`, `host`, `datadir`, `dbhost`, `smtphosts`, `smtpport`,
  `noreply`, candidate `courses[]`, and `helpers[]` group ids.
- `scripts/mhs_env.sh show | set K=V ... | unset K ...` — idempotent, conflict-
  aware manager for `$HERMES_HOME/.env` (chmod 600). Never overwrites an
  existing key; only appends missing ones. Also mirrors `MHS_CAMPUS_CIDR` into
  the plugin's un-prefixed `MOODLE_AUDIT_CAMPUS_IPS`.

## 2. Procedure

### Step 1 — Locate the webroot
Determine the Moodle webroot (dir containing `config.php`):
1. If `MHS_WEBROOT` is set in the env / `.env`, use it.
2. Otherwise check the default `/var/www/html/public` (or `MHS_DATA_DIR`'s
   sibling). If unsure, **ask the user** for the webroot.

### Step 2 — Run the probe
```
php <skill>/scripts/mhs_probe.php "<webroot>"
```
Read the JSON. If `error` is set, fix the webroot and re-run.

### Step 3 — VERSION GATE (critical)
Compare `version` (the big int) against the **5.2 floor = `2026042000`**
(Moodle version numbers are `YYYYMMDDNN`; 5.2.0 = 2026042000, so any 5.2.x or
newer satisfies the gate).

- **`version >= 2026042000` → proceed.** Record the detected `release`
  (e.g. "5.2.1") for the summary.
- **`version < 2026042000` → STOP and warn the user.** State the detected
  release, that this skill set targets Moodle 5.2+, and which skills are
  affected (quiz-engine, integrity-audit, question-bank/diagnostics, gradebook
  aggregation constants, question-progress/review). Ask whether to continue
  anyway; if the user overrides, persist `MHS_VERSION_GATE=override` so the
  warning is not repeated every run. Do not set the other vars as "ready" until
  the user confirms.

### Step 4 — Build the plan table (conflict-aware)
For each variable below, decide the **action**:
- `set`   — value detected (or user supplied), not yet in `.env`.
- `keep`  — already in `.env` (user value preserved — never overwritten).
- `ask`   — no default, not detected, not set → must ask the user.
- `skip`  — explicitly left alone.

| Variable | Source of truth | Default |
|---|---|---|
| `MHS_WEBROOT` | probe (webroot we booted from) | `/var/www/html/public` |
| `MHS_WWWROOT` | probe `wwwroot` | — (ask) |
| `MHS_HOST` | probe `host` | — (ask) |
| `MHS_DATA_DIR` | probe `datadir` | `/var/www/moodledata` |
| `MHS_COURSE_ID` | probe `courses[]` → **ask user which** | — (ask) |
| `MHS_COURSE_CODE` | probe `courses[].shortname` for the chosen id | — (ask) |
| `MHS_HELPER_GROUP_ID` | probe `helpers[]` for the chosen course | — (ask) |
| `MHS_LAB_CIDR` | not in config → **ask the user** | — (ask) |
| `MHS_CAMPUS_CIDR` | not in config → **ask the user** | — (ask) |
| `MHS_SMTP_HOST` | probe `smtphosts` | — (ask) |
| `MHS_SMTP_PORT` | probe `smtpport` | — (ask) |
| `MHS_SMTP_FROM` | probe `noreply` | — (ask) |
| `MHS_SMTP_USER` / `MHS_SMTP_PASS` | never auto — **ask the user** | — (ask) |
| `MHS_EHLO_HOST` | usually = `MHS_HOST` | derived (ask to confirm) |

### Step 5 — Ask the user for the `ask` items
Present the plan table (variable → detected → current .env → action) and ask
for the values that have no safe source: which course, the lab/campus CIDRs,
and any SMTP credentials. Never present credentials back in output; confirm by
mask.

### Step 6 — Persist (idempotent)
```
bash <skill>/scripts/mhs_env.sh set MHS_WEBROOT=... MHS_COURSE_ID=... \
     MHS_COURSE_CODE=... MHS_HELPER_GROUP_ID=... MHS_LAB_CIDR=... \
     MHS_CAMPUS_CIDR=... MHS_SMTP_HOST=... MHS_SMTP_PORT=... MHS_SMTP_FROM=... \
     [MHS_SMTP_USER=... MHS_SMTP_PASS=... MHS_EHLO_HOST=...]
```
This writes only the missing keys, preserves existing ones, `chmod 600`'s the
file, and mirrors `MHS_CAMPUS_CIDR` into `MOODLE_AUDIT_CAMPUS_IPS` (so the
`moodle_audit_quiz` plugin tool keeps working).

### Step 7 — Verify
```
bash <skill>/scripts/mhs_env.sh show
```
Confirm every required var is present, the version gate passed (or was
explicitly overridden), and no value was clobbered. Reload the env for the
current session (`source "$HERMES_HOME/.env"` in the shell that runs the
scripts) so subsequent skill calls pick the values up.

## 3. Re-running after merging updated skills

Because step 6 only *adds* missing keys and step 4 *keeps* existing ones, you
can freely merge new skill versions and re-run `mhs-setup`:
- New skills that reference **new** `MHS_*` vars simply appear as `ask`/`set`
  rows on the next run.
- Values the user already customized are reported as `keep` and left intact.
- Nothing is ever lost on re-merge.

If a var was *renamed* between versions, `mhs_env.sh unset OLD_KEY` then re-run
setup to migrate it deliberately.

## 4. Pitfalls

- **The version number is a big int, not "5.2".** Compare numerically against
  `2026042000`; do not string-compare the release.
- **`config.php` boot needs a writable `moodledata` and the DB reachable.** If
  the probe errors at bootstrap but the site is fine, the pod may lack the PHP
  DB driver — fall back to reading `config.php` by eye for wwwroot/dbhost and
  ask the user for the course id.
- **Course id ≠ shortname.** `MHS_COURSE_ID` is the numeric id; `MHS_COURSE_CODE`
  is the shortname string. Both matter (code strings appear in content, ids in
  SQL). Always set both and cross-check the probe `courses[]` row.
- **Multiple `helpers` groups.** If the probe returns more than one, ask which
  course's group is the one to exclude from student counts.
- **Never write SMTP credentials into skill files or logs.** They live only in
  `$HERMES_HOME/.env` (chmod 600) and are read at runtime.
