---
name: port-skill-between-deployments
description: Transfer a Hermes skill from one deployment/instance to another (another course, another pod, another Moodle install). Generalize deployment-specific values, make scripts env-overridable, verify the adapted script actually runs, and package it as a self-contained teaching packet the other agent can ingest. Use when asked to "teach this skill to another hermes / the other course", "share/port/move a skill to another deployment", or "make a skill transferable".
---

# Port a skill between Hermes deployments / instances

Move a capability from one Hermes deployment to another (e.g. this course's Hermes → a sibling course's Hermes on a different pod / course code / route). The two instances are usually NOT network-connected, so transfer is **manual**: produce a self-contained packet the other agent can read and ingest with its own skill tool.

## When to use
- "Teach this skill to another hermes / the other course's agent"
- "Share / port / move this skill to another deployment"
- "Make this skill transferable to the other install"
- A skill proven on THIS deployment that must also work on a sibling deployment with a different course code / route / Moodle install.

## Why not just copy the SKILL.md
A working skill is usually laced with **deployment-specific values that are WRONG on the target**: hardcoded course/quiz/group ids, Moodle root paths, lab/campus CIDRs, hostnames, test-account emails, and scripts with `require('...config.php')` paths baked in. Copying verbatim makes the other agent confidently do the wrong thing (audit the wrong course, hit a non-existent path, mail the wrong From). The whole job is to strip those and re-generalize.

## Procedure
1. **Inventory the deployment-specific surface.** Grep the SKILL.md + every `scripts/` + `references/` file for: numeric course/quiz/group ids, absolute paths (`/var/www/...`), CIDR/IP ranges, hostnames, test-account emails, `require('...config.php')` lines. Classify each as (a) universally true — keep; (b) deployment-specific — must generalize; (c) a worked-example detail — keep but LABEL "in the source deployment".
2. **Generalize the prose.** Replace hard values with placeholders + "adapt for your install": course id → `<cid>` / `$CID`; moodle root → `$MOODLE_ROOT` / `<your_moodle_root>`; CIDRs → "ask the instructor"; test accounts → "derive from your own roster". Keep ONE concrete example but mark it explicitly as a single deployment's numbers so it reads as **calibration**, not instruction.
3. **Make scripts env-overridable.** In each `scripts/*.php`, hoist the deployment constants to the top and drive them from env vars with the current deployment as the default, so the SAME file works on both sides:
   ```php
   $MOODLE_ROOT = getenv('MOODLE_ROOT') ?: '/var/www/html/public';
   $CID         = getenv('CID') ?: 3;
   $host        = getenv('SMTP_HOST') ?: 'smtp.example.edu.hk';
   require($MOODLE_ROOT . '/config.php');
   require_once($MOODLE_ROOT . '/lib/setup.php');
   ```
   The other agent sets the env var (or edits one line) instead of forking the script.
4. **VERIFY the adapted script actually runs.** On this deployment, re-run the generalized script end-to-end (read-only queries, or a send to a safe/invalid address) and confirm it reproduces the known-good output. Do NOT trust `php -l` — it is broken in the pod (reports "Errors parsing" on valid one-liners). The proof is a real run.
5. **Package a self-contained teaching packet** (a single `.md`, e.g. under `<hermes_home>/cron/output/`). It must contain, in order:
   - The exact `skill_manage` commands the other agent runs (`action='create'` for the SKILL.md, `action='write_file'` per script).
   - The **verbatim** generalized SKILL.md.
   - The **verbatim** generalized script(s), **inline** (never "attached separately").
   - A **first-run checklist** for the target: verify its own mail/DB paths, set its course id + moodle root, learn its group-name convention, smoke-test, plus any version/schema checks.
   - A **worked example** from this deployment (for calibration, clearly labeled).
6. **Hand off.** If there's no direct channel to the other instance (check `hermes send --list`), give the user the packet path and that they copy it; offer to `hermes send` it if a target exists.

## Pitfalls
- **`php -l` is broken in the pod** (false "Errors parsing" on valid code) — never gate a transfer on lint; run the script.
- **Inline the script, don't reference it.** "Script attached separately" leaves the other agent unable to self-serve. Embed verbatim in the packet.
- **Generalize the data-source, not just the paths.** `WHERE courseid = 3` is wrong on the target — make it `$CID`. A hardcoded list of this course's test emails will mis-fire elsewhere — tell them to derive it from their own roster.
- **Keep one labeled worked example.** Stripping ALL concrete numbers untethers the skill; the other agent needs the source's real numbers as a calibration reference, clearly marked "source deployment".
- **Don't over-strip.** Universally-true facts (Moodle 5.x table schemas, "Precheck is a step flag, not a state", "sumgrades is on the question scale") are the VALUE — they must survive the transfer.
- **Don't pre-bake dates into the packet or email.** PHP `date()` on this pod shows UTC+8 while the system clock is UTC (a date/lateness claim computed the wrong way is how a "still open" claim was wrong ~9h after close). Teach the other agent to compute `time()` vs `timeopen`/`timeclose` at run time, not to copy a stale "N days left".

## Verification that the packet is good
- No leftover deployment-specific hard values in the "instructional" parts (they only appear in the labeled worked example).
- Every script runs cleanly on this deployment with defaults, and its output matches the known-good result.
- The packet is self-contained: a fresh agent with the file + its `skill_manage` tool can reproduce the skill with zero follow-up questions.
