---
name: hermes-skill-transfer
description: Port a Hermes skill from this instance to another Hermes instance/deployment (another course's pod, another profile). Covers locating the target, generalizing deployment-specific hard-codes before shipping, packaging a self-contained teaching packet with exact skill_manage calls, and delivery options (hermes send, hand-copy). Use when the user asks to "teach a skill to another hermes", share a skill across course instances, or migrate a skill to a different deployment.
---

# Porting a skill to another Hermes instance

## When to use
User wants another Hermes (another course's pod, another profile, another deployment) to have a skill this instance already has.

## Steps
1. **Locate the target.**
   - Local profile on this machine? Check `ls /var/www/moodledata/.hermes/profiles/`. If it exists, the other agent's skills dir is `profiles/<name>/skills/` (cross-profile writes need explicit user direction; skill_manage has a cross_profile guard).
   - Separate pod/deployment (the common case on this site: one pod per course)? No direct file access — package and hand off (steps 3–5).
2. **Generalize before shipping.** Audit the skill + its scripts for deployment-specific hard-codes and remove them:
   - Numeric ids (course id, quiz id, cmid, group ids) → variables at the top of scripts ("set to your course id") + a "look it up, don't guess" step in SKILL.md
   - Absolute paths (moodle root, hermes home) → env vars or clearly-marked defaults
   - IP/CIDR ranges, campus names, email domains, test-account names → "ask the instructor / check your roster"
   - Course-specific *facts* (e.g. "E-Quiz 1 has 16 questions, grade 80") → demote to a clearly marked *example from one deployment*; keep the *procedure* (list all quizzes, confirm by name + question count + max mark + time limit, ask when ambiguous)
   - Transferable lessons (state semantics, schema pitfalls, PHP gotchas, false-positive case studies) are the value — keep them.
3. **Smoke-test the generalized version on your own deployment** (it must still produce correct output). Never ship unverified code.
4. **Package a single self-contained file** (e.g. `~/.hermes/cron/output/<skill>-teaching-packet.md`) containing:
   - Exact receiver-side commands: `skill_manage(action='create', name=..., category=..., content=<SKILL.md>)` plus one `write_file` per support file
   - Full SKILL.md inline; full scripts inline in fenced blocks — **no "attached separately" placeholders**
   - An **adaptation checklist** for first run on the destination (paths, ids, version schema checks via information_schema, smoke test)
   - A worked example from the source deployment for calibration
5. **Deliver.**
   - `hermes send --list` shows reachable targets (on this pod: the course Matrix room + the user's Telegram DM). `hermes send -t <target> -f <packet>` for text; `MEDIA:<path>` in the message text attaches a file.
   - Or the user hand-copies. Note file perms: files under `~/.hermes/` are `600 www-data` — the user needs `sudo cp` if copying as another user.

## Pitfalls
- **No python3 in this pod** — use PHP one-liners for string manipulation (e.g. embedding a script file into the packet).
- Verify the packet before delivery: grep for leftover placeholders (expect 0) and confirm each major section plus a marker of the embedded script (e.g. a distinctive function call) is present.
- `skill_manage(action='write_file')` only accepts `file_path` under `references/`, `templates/`, `scripts/`, or `assets/`.
- Don't strip *examples* that contain specific ids — the worked example is the calibration evidence; just mark clearly which parts are examples vs rules.
- If the two instances' deployments differ in Moodle version, the packet's adaptation checklist should include a schema probe (`information_schema` for table/column existence) before the first real run.
