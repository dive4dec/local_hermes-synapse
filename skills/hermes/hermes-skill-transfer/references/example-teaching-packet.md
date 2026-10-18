# Worked example: teaching packet structure (from the quiz-ai-misuse-audit port, 2026-09-17)

Full example lives at `~/.hermes/cron/output/quiz-ai-misuse-audit-teaching-packet.md` on the source pod (19 KB, self-contained). Anatomy of a good packet:

```
# Teaching packet: <skill-name>
To the Hermes managing the other course: ... save it using your skill tool:
    skill_manage(action='create', name='...', category='moodle', content=<SKILL.md below>)
    skill_manage(action='write_file', name='...', file_path='scripts/<name>.php', file_content=<script below>)
Then adapt the two configuration points before first use (see checklist at bottom).

## SKILL.md (verbatim — create the skill with this content)
<full frontmatter + body, unchanged from source>

## scripts/<name>.php (verbatim)
```php
<full script inline — NO "attached separately" placeholders>
```

## Adaptation checklist (do this on FIRST run on the new course)
1. Moodle root: set $MOODLE_ROOT (or MOODLE_ROOT env var) to the dir containing config.php
2. Course id: find via mdl_course.idnumber/shortname, set $CID
3. Quiz id: list quizzes with the Step-0 query, set $QUIZ; if names ambiguous, ASK
4. Test accounts: check roster for non-student accounts, extend the exclusion filter
5. Campus CIDRs: ask the instructor before any IP cross-check
6. Smoke test: run and eyeball distributions before reporting anything
7. Version check: probe information_schema for table/column existence before joining

## Worked example (source deployment, for calibration)
<2–5 lines: cohort size, norms, how many flagged, the false positive that was
cleared and why — the calibration evidence, ids included but marked as example>
```

Rules that made the 2026-09-17 port succeed:
- The script was made path-agnostic BEFORE packaging (`$MOODLE_ROOT = getenv('MOODLE_ROOT') ?: '<default>'`, `$CID`, `$QUIZ` as named config vars) and re-smoke-tested after generalization.
- Course-specific *facts* in the source SKILL.md (e.g. "E-Quiz 1 = 80-grade, 16 questions") were demoted to a quoted *example*; the *rule* ("confirm by name + question count + max mark + timelimit; ask when ambiguous") was generalized.
- The packet was verified before delivery: `grep -c "attached separately"` → 0; `grep -c "<distinctive script marker>"` → 1; section-header listing eyeballed.
- Delivery: `hermes send --list` first (this pod: course Matrix room + user Telegram DM only — the other course's bot is NOT reachable from here), then the user hand-copies; remember `600 www-data` perms on `~/.hermes/` files.
