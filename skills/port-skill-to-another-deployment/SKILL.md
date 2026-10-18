---
name: port-skill-to-another-deployment
description: Transfer / teach a skill (or a capability scattered across several skills) to another Hermes instance managing a different course or pod. Generalizes deployment-specific values, verifies by running (not linting), and builds a self-contained teaching packet with install commands + first-run checklist. Use when asked to "teach the skill to another hermes", "port this to the other course", or "transfer other skills".
---

# Port a skill / capability to another Hermes instance

The other instance is a SEPARATE install (different pod/course/filesystem) — there is
no shared `skills/` dir. So "teach it" = **generalize → verify by running → build a
self-contained packet → deliver**. Do all four; a packet that ships hard-coded
course/quiz/paths teaches the other instance to get plausible-but-wrong answers.

## 1. Inventory & decide shape
- `skills_list` to see what exists. The requested capability is often **scattered
  across several overlapping skills**. Example: "emailing student groups" = a
  raw-ESMTP sender skill + a campus-SMTP skill + a group-roster DB query from a
  DB-access skill. 
- Decide: **consolidate** the scattered pieces into ONE clean class-level skill for
  the recipient (preferred — matches the "rich umbrella, not flat list" shape), or
  port an existing single skill as-is.
- If consolidating, create the recipient skill with `skill_manage(action='create')`.

## 2. Generalize deployment-specific values
Find every hard-coded value that is true of THIS course/pod but not the other's, and
turn it into an env var or a clearly-marked constant with a "change for your install"
comment:
- Moodle root path (`config.php` location), hermes home / run dir
- Course id, quiz id(s), group names
- Hostnames: SMTP relay host:port, EHLO name, Message-ID domain, campus CIDRs
- Sender/From address (must be a real same-domain mailbox on the other box)
- Test-account filters, thresholds tuned to this cohort

## 3. Verify by RUNNING, not linting
- `php -l` may be broken in these pods (it reports "Errors parsing" even on valid
  one-liners). Do NOT trust lint.
- Actually run the generalized script: a read-only smoke test for DB scripts, or a
  real send to the instructor's own address for mail scripts. Confirm the success
  signal (`250 2.0.0 …` for SMTP, expected row counts for queries).
- A one-off real side-effect (a test email to a deliberately-invalid address that
  just bounces) is acceptable to prove the path — say what you did.

## 4. Build a self-contained teaching packet (one .md)
Structure (see `templates/teaching-packet.md`):
1. **Install commands** the recipient runs verbatim:
   `skill_manage(action='create', name=…, category=…, content=<SKILL.md>)` and
   `skill_manage(action='write_file', name=…, file_path='scripts/…', file_content=…)`.
2. **Full SKILL.md verbatim** (generalized).
3. **Full script(s) verbatim** — EMBED the contents inline, do not reference a path
   (the recipient may not share your filesystem).
4. **"Step 0: verify YOUR environment first"** — frame deployment-specific facts
   (mail subsystem stripped, schema shape, available tools) as "check on your box",
   not universal truth.
5. **First-run checklist** — set the env vars/constants, smoke-test, learn local
   conventions (group naming, campus CIDRs), confirm before bulk actions.
6. **Worked example** from the source deployment, for calibration.

Write it to `<hermes>/cron/output/<skill>-teaching-packet.md`. (Assembling it: use a
small PHP/Python builder that reads the skill files and inlines them — do not paste
by hand.)

## 5. Deliver
- `hermes send --list` to see configured targets. If the other instance's channel is
  configured, `hermes send --to <target>` the packet.
- Otherwise give the user the file path. Note the **permissions**: skill/packet files
  are often `600 www-data` — the user copying as root/another user needs `sudo cp`.

## Pitfalls
- Never ship a skill with hard-coded course/quiz/paths un-generalized — that's how
  the other instance inherits your context as a false fact.
- Don't port 3 narrow overlapping skills when one class-level umbrella serves the
  recipient; consolidate.
- A "lesson" like "mail is stripped here" is deployment-specific — phrase it as
  "verify your mail path" in the packet, else the other instance over-applies it.
- `hermes send` and skill paths are the two things users most often need to copy
  manually; always state the absolute path + permission caveat.
