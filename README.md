# local_hermes-synapse

Hermes skills and plugins for the local_hermesagent Moodle integration. "Synapse" — the connections between Hermes' memory and its extended capabilities.

**Related repos:**
- [dive4dec/local_hermesagent](https://github.com/dive4dec/local_hermesagent) — the Moodle plugin + Hermes bootstrap (`bootstrap.sh` wires this repo in)
- [dive4dec/e-quiz](https://github.com/dive4dec/e-quiz/) — the e-quiz platform (LTI-hosted collaborative quizzes)

---

## What's in here

```
local_hermes-synapse/
├── skills/                         # 61 skills across 16 categories
│   ├── _conventions/PORTABLE.md    # MHS_ env-var scheme (single source of truth)
│   ├── mhs-setup/                  # Meta-skill: version gate, config.php autodetect, env persistence
│   ├── moodle/                     # 24 — quiz, Code Runner, email, groups, math, integrity
│   ├── moodle-admin/               # 21 — cache, gradebook, LTI, SMTP, SEB, plugins, courses
│   ├── hermes/                     #  3 — skill transfer between deployments
│   ├── moodle-cequiz-management/   #  1 — CE-Quiz timing + group overrides
│   ├── moodle-cequiz-schedule-propagation/  #  1 — CE-Quiz schedule fix
│   ├── moodle-db-access/           #  1 — PHP bootstrap + PyMySQL bridge
│   ├── moodle-fix-course-url-migration/     #  1 — URL migration after WWWROOT change
│   ├── moodle-group-management/    #  1 — groups + quiz group overrides
│   ├── moodle-lti-management/      #  1 — LTI custom params, notebook links
│   ├── moodle-pdf-generation/      #  1 — quiz PDF (student sheets + answer keys)
│   ├── moodle-seb-quiz-access/     #  1 — SEB access diagnosis
│   ├── moodle-troubleshooting/     #  1 — logstore, enrollment, access failures
│   ├── hermes-matrix-gateway/      #  1 — Matrix/Element gateway setup
│   ├── hermesagent-plugin-upgrade/ #  1 — safe plugin upgrade procedure
│   └── port-skill-to-another-deployment/    #  1 — transfer a skill to another instance
│
└── plugins/                        # Python code extending Hermes
    └── moodle-bridge/              # Per-session identity + 3 registered tools
        ├── plugin.yaml
        └── __init__.py             # moodle_get_my_courses, moodle_upload_file, moodle_audit_quiz
```

---

## Skills by category

### `mhs-setup` — Bootstrap (run first)
Version-gates on Moodle 5.2+, auto-derives `MHS_*` env vars from `config.php`/DB, persists them conflict-aware and idempotently to `$HERMES_HOME/.env`. Re-runnable after merging updated skills.

### `moodle/` (24 skills) — Core course operations

| Skill | Purpose |
|---|---|
| **Quiz & grading** | |
| `moodle-absent-zero-grade` | Mark quiz grade zero for absent students or a single failed question |
| `moodle-quiz-attempt-inspection` | Inspect attempts by state, in-progress, step traces |
| `moodle-quiz-question-progress` | Per-question per-slot completion (answered / gave up / never reached) |
| `moodle-quiz-question-review` | Validate questions pre/post-publish: execute CodeRunner, check tests |
| `moodle-quiz-integrity-audit` | Detect AI answer-pasting, copying, off-campus access patterns |
| `quiz-ai-misuse-audit` | Per-question step-trace analysis (fast + high score + near-zero self-correct) |
| `quiz-integrity-deep-dive` | Single-student integrity + technical claim investigation |
| `quiz-sampling-consequence` | Pipeline for sampling-for-explanation consequences |
| `moodle-answer-dispute-investigation` | Investigate "quiz recorded wrong answer" claims |
| `crossquiz-ai-divergence-audit` | Compare performance on identical quizzes to flag AI misuse |
| `moodle-cross-quiz-cohort` | Who attempted quiz X but NOT quiz Y |
| `moodle-equiz-student-status` | Three student-status cohorts for an LTI-enrolled quiz |
| **Code Runner** | |
| `coderunner-question-creation` | Author new Code Runner (python3) questions for mock exams |
| `coderunner-prototype-import` | Fix missing prototype errors via direct SQL inserts |
| `moodle-coderunner-jobe-diagnosis` | Diagnose Code Runner check/precheck slow/frozen/not-working |
| `moodle-math-delimiter-fix` | Fix broken inline math in Code Runner questions |
| **Email** | |
| `campus-smtp-email` | Send real emails from the Moodle box via campus SMTP |
| `email-student-group` | Email one or many students (whole group / lab section) |
| **Groups & structure** | |
| `moodle-course-group-management` | Create/delete/audit groups + quiz group overrides |
| `moodle-course-structure` | Group/grouping lifecycle, quiz group mode, overrides |
| `moodle-group-management` | Manage groups + quiz group overrides |
| **Course admin** | |
| `course-clone-with-moosh` | Clone a course (backup → restore, no enrolled users) |
| `moodle-enable-dollar-math` | Enable $...$ inline math via MathJax config |
| `moodle-question-course-mapping` | Map questions to courses via versioning chain + context |
| **Diagnosis & pitfalls** | |
| `moodle-php-cli-pitfalls` | Pitfall bank for PHP CLI scripts against this Moodle |

### `moodle-admin/` (21 skills) — Instance administration

| Skill | Purpose |
|---|---|
| `moodle-admin` | Environment admin: plugin discovery, config, Moosh, introspection |
| `moodle-add-activity-via-db` | Create activities (forum, quiz, assignment) via DB/PHP |
| `moodle-create-activity` | Create activities via direct DB inserts (when moosh is broken) |
| `moodle-lti-create-activity` | Create LTI activities via PHP API + cache purge |
| `moodle-lti-management` | LTI custom params, notebook links, URL fixes |
| `moodle-gradebook` | Grade structure, weight semantics, aggregation constants |
| `moodle-cache-purge` | Purge caches after DB changes (course_modinfo, question, etc.) |
| `moodle-content-maintenance` | Bulk fixes: URL migration, delimiter fixes, hardcoded content |
| `moodle-course-content-audit` | Read-only consistency audit of all course text content |
| `moodle-course-maintenance` | Rename labels, update contacts, completion, diagnostics |
| `moodle-ai-courseassist` | AI course-assist (Explain/Summarise) UI flow + settings |
| `moodle-curl-security-for-ai` | Fix cURL security blocking AI provider API calls |
| `moodle-forum-management` | Forum URLs, copy discussions/posts between forums |
| `moodle-internal-messaging` | Deliver messages via Moodle internal messaging (inbox + popup) |
| `moodle-lock-profile-editing` | Lock users from editing own profile (especially email) |
| `moodle-mcp-db-query` | Query DB with moodle_db MCP read-only SQL tool |
| `moodle-plugin-install` | Install Moodle plugins via moosh, handle upgrades |
| `moodle-quiz-attempt-deletion` | Delete quiz attempts safely (fans out across 6+ tables) |
| `moodle-seb-template-management` | Bulk-standardize SEB template config across quizzes |
| `moodle-smtp-email` | Find SMTP config + send test emails via PHPMailer |
| `moodle-wiki-data-access` | Read/modify wiki module data |
| `pod-smtp-email-send` | Send outbound email via campus SMTP relay |

### `moodle-cequiz-*` (2 skills) — Collaborative E-Quiz
- `moodle-cequiz-management` — CE-Quiz timing + group overrides
- `moodle-cequiz-schedule-propagation` — Fix CE-Quiz/E-Quiz timing from weekly lab schedule

### `moodle-pdf-generation` (1 skill)
Generate quiz PDF documents (student question sheets + instructor answer keys) via dompdf.

### `hermes/` + `port-skill-to-another-deployment/` (4 skills) — Skill transfer
Transfer a skill (or capability scattered across several) from one deployment to another, generalizing course-specific values.

### `hermes-matrix-gateway` / `hermesagent-plugin-upgrade` (2 skills)
- Matrix/Element gateway setup + troubleshooting
- Safe local_hermesagent plugin upgrade procedure

### `moodle-db-access` / `moodle-fix-course-url-migration` / `moodle-seb-quiz-access` / `moodle-troubleshooting` (4 skills)
- PHP bootstrap + PyMySQL bridge for DB access
- URL migration after WWWROOT/route changes
- SEB access diagnosis + fixes
- Logstore-based access failure diagnosis

---

## The `MHS_` portable convention

All 61 skills are **hermetic, secret-free, and course-agnostic**. Course/site-specific values are read from `MHS_*` environment variables (see [`skills/_conventions/PORTABLE.md`](skills/_conventions/PORTABLE.md)). Run `mhs-setup` on a new site to auto-derive and persist them.

Key variables: `MHS_COURSE_ID`, `MHS_COURSE_CODE`, `MHS_WEBROOT`, `MHS_DATA_DIR`, `MHS_HOST`, `MHS_HELPER_GROUP_ID`, `MHS_CODE_RUNNER_PROTOTYPE`, `MHS_SMTP_*`, `MHS_LAB_CIDR`, `MHS_CAMPUS_CIDR`.

---

## Skills vs Plugins vs Toolsets

### Skills — *knowledge the agent reads*
Markdown instructions + supporting files (PHP scripts, templates). The agent reads SKILL.md and follows instructions using existing tools (terminal, file). Distributed via `hermes skills tap add` + `hermes skills install`.

### Plugins — *Python code that extends Hermes*
`moodle-bridge` registers:
- **`moodle_get_my_courses`** — list courses for the current user
- **`moodle_upload_file`** — upload a file to Moodle
- **`moodle_audit_quiz`** — in-process DB audit of a quiz (replaces the old `moodle_quiz_audit` skill that had a concurrency bug)

### Toolsets — *static tool groupings*
Compiled into Hermes. Not relevant to most use cases.

---

## Installation

### From a Hermes install (any platform)

```bash
# Add this repo as a skill tap
hermes skills tap add dive4dec/local_hermes-synapse

# Install a skill (example: quiz PDF generation)
hermes skills install dive4dec/local_hermes-synapse/skills/moodle-pdf-generation

# Install dompdf dependency (one-time, pure PHP)
sh $HERMES_HOME/skills/moodle-pdf-generation/scripts/install_deps.sh

# Install the moodle-bridge plugin (requires MOODLE_CONFIG_PATH env var)
hermes plugins install dive4dec/local_hermes-synapse/plugins/moodle-bridge --enable
```

### From local_hermesagent (Moodle plugin bootstrap.sh)

[`bootstrap.sh`](https://github.com/dive4dec/local_hermesagent) handles all of the above automatically. See the [local_hermesagent repo](https://github.com/dive4dec/local_hermesagent) for details.

### After installing (first run on a new site)

```bash
# Bootstrap the MHS_ env vars (version gate + auto-detect + persist)
# The agent runs this skill: "set up the moodle skills" or "configure MHS"
php $HERMES_HOME/skills/mhs-setup/scripts/mhs_probe.php /var/www/html/public
bash $HERMES_HOME/skills/mhs-setup/scripts/mhs_env.sh set MHS_COURSE_ID=<id> ...
```

---

## Dependency management

- **Pins versions** — dompdf v3.1.5 is hardcoded in `install_deps.sh`
- **Verifies downloads** — zip integrity checked before extraction
- **Platform-independent** — dompdf is pure PHP, no arch/libc detection needed
- **Self-contained** — `install_deps.sh` is the only network call, runs once
- **Idempotent** — skips if already installed

For future skills with platform-specific binary dependencies, use the cross-platform detection pattern from [local_hermesagent](https://github.com/dive4dec/local_hermesagent)'s `bootstrap.sh`.

---

## e-quiz integration

The [dive4dec/e-quiz](https://github.com/dive4dec/e-quiz/) platform is LTI-hosted inside Moodle. Several skills in this repo support e-quiz operations:
- `moodle-equiz-student-status` — student cohorts for LTI-enrolled quizzes
- `moodle-cequiz-management` — CE-Quiz timing + group overrides
- `moodle-cequiz-schedule-propagation` — fix CE-Quiz timing from lab schedule
- `moodle-lti-management` — LTI custom params, notebook links

---

## Rollback

Each release is a git commit (see [CHANGELOG.md](CHANGELOG.md)). Roll back any phase with `git revert <commit>`.
