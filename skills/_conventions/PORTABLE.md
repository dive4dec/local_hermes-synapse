/usr/bin/bash: _parse_usage: line 16: syntax error near unexpected token `('
/usr/bin/bash: _parse_usage: line 16: ` -?(\[)+([a-zA-Z0-9?]))'
/usr/bin/bash: error importing function definition for `_parse_usage'
/usr/bin/bash: _longopt: line 6: syntax error near unexpected token `('
/usr/bin/bash: _longopt: line 6: ` --!(no-*)dir*)'
/usr/bin/bash: error importing function definition for `_longopt'
# Portable-skill conventions (`MHS_`)

This file is the single source of truth for how every skill in this repo is
parameterised so the set is **hermetic** (self-contained), **secret-free**, and
**course-agnostic**. If a skill references a `MHS_*` variable or a `<token>`
placeholder, this is where the meaning lives. Read it before touching any skill.

## 1. The `MHS_` environment variable scheme

Every course/site-specific value is held in an environment variable under one
distinctive, fixed prefix — **`MHS_`** (Moodle Hermes Synapse). The prefix is
deliberately namespaced so it cannot collide with other skills, instances, or
user environment. The *variable names* never contain a course name; only the
*values* differ per course.

| Variable | Meaning | Default | Fallback if unset |
|---|---|---|---|
| `MHS_COURSE_ID` | Numeric Moodle course id (the `$courseid` used everywhere) | — | **ask the user** |
| `MHS_COURSE_CODE` | Course short-name string (e.g. `<coursecode>`) | — | **ask the user** |
| `MHS_HELPER_GROUP_ID` | Id of the "helpers"/exam group (excluded from student counts) | — | **ask the user** |
| `MHS_CODE_RUNNER_PROTOTYPE` | Name of the Code Runner `python3` prototype question (e.g. `python3_<coursecode>_prototype`) | `python3_cs1302_prototype` | ask if your instance differs |
| `MHS_WEBROOT` | Moodle PHP filesystem webroot | `<webroot>` | ask if wrong |
| `MHS_WWWROOT` | Full HTTP base incl. sub-path, e.g. `https://host/codename` | — | **ask the user** |
| `MHS_DATA_DIR` | `moodledata` directory | `<datadir>` | ask if wrong |
| `MHS_HOST` | Moodle host (FQDN) | — | **ask the user** |
| `MHS_LAB_CIDR` | Lab/campus-network CIDR(s) for IP-based audit | — | **ask the user** |
| `MHS_CAMPUS_CIDR` | Broader campus CIDR(s) for IP-based audit | — | **ask the user** |
| `MHS_SMTP_HOST` / `MHS_SMTP_PORT` / `MHS_SMTP_FROM` / `MHS_SMTP_USER` / `MHS_SMTP_PASS` / `MHS_EHLO_HOST` | Outbound SMTP relay settings | — | **ask the user** (never guess credentials) |

> **Note on `MOODLE_AUDIT_CAMPUS_IPS`:** the in-repo `moodle_audit_quiz` plugin
> tool reads the *un-prefixed* `MOODLE_AUDIT_CAMPUS_IPS`. To keep that tool
> working without renaming it, the campus-audit value is mirrored into both
> `MHS_CAMPUS_CIDR` (this scheme) **and** `MOODLE_AUDIT_CAMPUS_IPS` (the plugin
> name) by `mhs-setup`. Lab CIDR has no plugin twin.

### Token → environment mapping (used in the skill text)
The skill bodies were generalised with these placeholder tokens. When a skill
shows a `<token>`, resolve it from the matching env var:

| Token in skill text | Resolved from |
|---|---|
| `<coursecode>` | `MHS_COURSE_CODE` |
| `<cid>` | `MHS_COURSE_ID` |
| `<helpergid>` | `MHS_HELPER_GROUP_ID` |
| `<webroot>` | `MHS_WEBROOT` |
| `<datadir>` | `MHS_DATA_DIR` |
| `<moodle-host>` | `MHS_HOST` |
| `<smtp-host>` | `MHS_SMTP_HOST` |
| `<lab-cidr>` / `<campus-cidr>` | `MHS_LAB_CIDR` / `MHS_CAMPUS_CIDR` |
| `<student-domain>` / `<domain>` | site user-mail domain / general domain (from `config.php` / LTI roster) |
| `<staff-email>` / `<student-email>` / `<Instructor-Name>` / `<Staff-X>` | identity placeholders — resolve per course; **never hardcode a real person** |

## 2. The read → default → ask → persist contract

Every skill that needs one of these values follows the **same** 4-step contract.
`mhs-setup` (the meta-skill) performs it up front, so a skill normally just
*reads*; but each skill must degrade gracefully if a var is missing:

1. **Read** the env var (`getenv("MHS_COURSE_ID")` etc.).
2. **Default**: if the var is unset but the variable has a documented default
   (e.g. `MHS_WEBROOT` → `<webroot>`), use the default.
3. **Ask**: if still unknown (no default, or default wrong for this site),
   **stop and ask the user** for the value. Do not guess a course id, a group
   id, a host, or credentials.
4. **Persist**: once the user supplies a value, write it to
   `$HERMES_HOME/.env` (create the file, `chmod 600`, **append if the key is
   not already present, never overwrite an existing value**). This makes the
   next run silent and lets the user re-merge updated skills safely.

This mirrors the repo's existing convention (check env order, don't clobber an
already-set value). `mhs-setup` is the canonical place that fills the vars from
the live source of truth (see §4) and writes them, so skills rarely need to
prompt directly — but they still must handle the missing case.

## 3. Moodle version gate (5.2+ required)

**The whole skill set assumes Moodle 5.2 or later.** The question-bank,
`question_references`, versioned-questions, `mdl_question_attempt_step_data`
layout, and several quiz-engine behaviours these skills rely on were not present
in older Moodle releases. Therefore:

- **Before setup, detect the real version** — do NOT assume it. `mhs-setup`
  reads it via `config.php` (`$CFG->version`) or `SELECT version FROM mdl_config`.
- **If the detected version < 5.2, STOP and warn the user**: name which skills
  are affected (quiz-engine, integrity-audit, question-bank, gradebook
  aggregation constants) and that they may misbehave or be wrong on the older
  schema. Do not silently proceed.
- If the user overrides the gate anyway, record that override in the env so the
  warning is not repeated every run.

## 4. How `mhs-setup` fills the variables (source of truth)

`mhs-setup` derives values from the live site rather than hardcoding them:

- **`config.php`** — `wwwroot`, `dbhost`/`dbport`/`dbuser`/`dbname`, SMTP
  settings (`smtphosts`, `smtpport`, `from`, noreplyaddress). Gives
  `MHS_WWWROOT`, `MHS_HOST`, `MHS_WEBROOT`, `MHS_DATA_DIR`, SMTP vars.
- **Moodle DB** — `mdl_config` / `mdl_config_plugins` for site + plugin settings
  (Jobe, LTI/ltigroups, SMTP), `mdl_course` for the course id/code,
  `mdl_groups` for the helpers-group id, `mdl_user`/`mdl_role_assignments` for
  who owns the site. Gives `MHS_COURSE_ID`, `MHS_COURSE_CODE`,
  `MHS_HELPER_GROUP_ID`.
- **IP ranges** — these are an *operational* fact about the lab/campus network
  that is not in `config.php`; `mhs-setup` **asks the user** (or reuses an
  existing value) for `MHS_LAB_CIDR` / `MHS_CAMPUS_CIDR`.

## 5. Conflict-aware + incremental merge

- `mhs-setup` is **idempotent** and **safe to re-run after merging updated
  skills**. On each run it:
  1. Scans `$HERMES_HOME/.env` for existing `MHS_*` (and the plugin's
     `MOODLE_AUDIT_CAMPUS_IPS`) values.
  2. Shows a `variable → detected → current .env → action` table where
     **action ∈ {set (new), keep (already set — never clobber), ask (no
     default, not set), skip (user-supplied)}**.
  3. Writes only what is missing or explicitly changed; user-customised values
     are preserved, so re-merging new skill versions never loses a local tweak.
- New skills added in a future update that reference new `MHS_*` vars are picked
  up on the next `mhs-setup` run — no manual edits required.

## 6. What must never appear in a skill (hermetic / secret-free)

- No real personal email, name, student id, or staff identity.
- No real SMTP password, API key, or token (credentials live only in
  `$HERMES_HOME/.env`, `chmod 600`, and are read at runtime).
- No course-locked values baked into prose — use the `<token>`/`MHS_*` scheme.
- No agent state (`.hub/`, `.curator_*`, `.usage.json`) — that is runtime
  artefact, not portable content.
