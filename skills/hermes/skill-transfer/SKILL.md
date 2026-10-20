---
name: skill-transfer
description: Transfer a skill from this Hermes instance to another one (different course / pod / deployment) — generalize hard-coded values, verify the script still runs, build a self-contained teaching packet, and deliver. Use when the user asks to "teach this skill to another hermes", "transfer a skill to the other course", or "give this to the other instance".
---

# Skill transfer to another Hermes instance

## When to use
The user wants another Hermes (another course / pod / deployment) to have a skill that exists here.

## Procedure
1. **Identify** the source skill (skill_view) and list its deployment-specific values: course ids, Moodle root / data dir, relay host + From address, campus CIDRs, group-name conventions, test-account emails, quiz ids.
2. **Generalize in place** (patch the live skill): promote values to env vars (`getenv('X') ?: default`) or constants marked `// <-- adapt`; replace course-specific rules with detect/ask steps (e.g. "list all quizzes; confirm by name + question count + max mark; ASK if ambiguous"). Keep worked examples, clearly labelled "source deployment".
3. **Verify the generalized script still runs** on this pod (read-only smoke test). `php -l` is unreliable/broken in this pod — verify by running, never by linting.
4. **Build a self-contained packet** (one .md, e.g. `~/.hermes/cron/output/<skill>-teaching-packet.md`) with:
   - the recipient's install commands (skill_manage create / write_file)
   - verbatim SKILL.md
   - verbatim support files (scripts) — embedded, not referenced by path
   - "First-run checklist (this box)" — what to verify/set on the OTHER deployment (schema check, mail-path check, ids)
   - a worked example from this deployment for calibration
5. **Strip secrets**: no SMTP credentials, tokens, DB passwords — reference "ask the instructor" instead.
6. **Deliver**: `hermes send --list` to see if a route to the other instance exists; if not (typical — cross-instance usually has no shared channel), ask the user how to move the file (copy / forward / upload to the other course). Packet files are 600 www-data — recipient may need `sudo cp`.

## Pitfalls
- No `python3` in this pod — assemble packets with a small PHP builder script (or the write_file tool). Backticks and special chars in the content break inline `php -r '...'` in the shell: write the builder to a file and run that.
- `sed` with `|` delimiters breaks on content containing `|` (e.g. PHP usage strings); prefer writing the generalized file directly with write_file.
- The other deployment may differ in schema/version (mail subsystem stripped or intact; behaviour vars in `question_attempt_step_data` vs `question_attempt_step_behaviour`; Moodle root path). The packet's first-run checklist must tell the recipient to VERIFY their own environment, not assume the source deployment's facts.
- Never bake this course's ids/conventions into the generalized skill — future sessions on THIS instance also read it and will be misled.

## Verification
Packet integrity: zero leftover placeholders (grep the placeholder string), script embedded (grep a known marker line like a `getenv(` call), section headers present, plausible size.
