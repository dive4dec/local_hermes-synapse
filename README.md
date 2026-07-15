# local_hermes-synapse

Hermes skills and plugins for the local_hermesagent Moodle integration. "Synapse" — the connections between Hermes' memory and its extended capabilities.

## What's in here

```
local_hermes-synapse/
├── skills/                         # Knowledge the agent reads (text-based)
│   └── moodle-pdf-generation/      # Quiz PDF generation (student sheets + answer keys)
│       ├── SKILL.md
│       ├── scripts/
│       │   ├── convert_html_to_pdf.php
│       │   └── install_deps.sh     # One-time dompdf v3.1.5 download (pinned, pure PHP)
│       └── references/
│           ├── html-preview-template.md
│           ├── quiz-pdf-example.md
│           └── solutions-template.md
│
└── plugins/                        # Python code extending Hermes (lifecycle hooks + tools)
    └── moodle-bridge/              # Per-session user identity + Moodle file upload
        ├── plugin.yaml
        └── __init__.py
```

## Skills vs Plugins vs Toolsets

Three distinct extension mechanisms in Hermes. They are NOT interchangeable:

### Skills — *knowledge the agent reads*

- **What:** Markdown instructions + supporting text files (PHP scripts, templates)
- **How distributed:** `hermes skills tap add owner/repo` → `hermes skills install owner/repo/skills/name`
- **Transport:** GitHub Contents/Trees API — fetches **text files only** (binary files break)
- **Runs code?** No — the agent reads SKILL.md and follows instructions using existing tools (terminal, file)
- **Binary deps:** Must be handled by an `install_deps.sh` script in the skill (download + pin version)
- **Example:** `moodle-pdf-generation` — tells the agent how to generate quiz PDFs via PHP scripts

### Plugins — *Python code that extends Hermes itself*

- **What:** Python packages with a `register(ctx)` entry point that runs at load time
- **How distributed:** `hermes plugins install owner/repo[/subdir]` — does a `git clone --depth 1`
- **Transport:** Full git clone — **binary files, vendor dirs, anything ships**
- **Runs code?** Yes — `register(ctx)` executes at Hermes load time
- **Can register:**
  - New tools (`ctx.register_tool`) — full JSON schema + Python handler
  - Lifecycle hooks (`ctx.register_hook`) — `on_session_start`, `on_turn_start`, `on_session_end`
  - Memory providers, platform adapters, middleware, slash commands
  - `pip_dependencies` declared in `plugin.yaml` are installed automatically
- **Example:** `moodle-bridge` — identifies the current Moodle user per-session and provides file upload tools

### Toolsets — *static tool groupings, compiled into Hermes*

- **What:** Collections of tool names (e.g. `web`, `terminal`, `file`, `browser`)
- **How distributed:** **They aren't.** Toolsets are defined in `toolsets.py` inside the Hermes package
- **Can you create new ones?** Only indirectly — a plugin can register tools with a `toolset` parameter, creating a new toolset dynamically. You cannot define a standalone toolset via config or files.
- **Not relevant to most use cases** — you use existing tools through skills/plugins

### Quick decision guide

| If you need to... | Use a |
|---|---|
| Tell the agent how to do something (instructions, scripts) | **Skill** |
| Run code at session start, register hooks, maintain state across turns | **Plugin** |
| Register new tools with Python handlers | **Plugin** |
| Group existing tools together | Toolset (but you probably don't need this) |
| Ship a PHP/Python script the agent calls via terminal | **Skill** |
| Ship a binary dependency with the extension | **Plugin** (git clone ships binaries); or **Skill** with `install_deps.sh` |

## When to use which (PDF generation example)

**moodle-pdf-generation is a skill** because:
- The agent reads instructions, then runs PHP scripts via the existing `terminal` tool
- No lifecycle hooks needed (no `on_session_start`, no state across turns)
- No new tools needed (terminal + file tools already exist)
- dompdf (pure PHP) is handled by `install_deps.sh` — one pinned download

**moodle-bridge is a plugin** because:
- Needs `on_session_start` hook to identify WHO is chatting (per-session, not shared memory)
- Needs to maintain state (current user info) across turns
- Registers new tools (`moodle_get_my_courses`, `moodle_upload_file`) that require Python DB access
- Memory cannot do this: memory is static text shared across all sessions, not per-user

## How memory fits in

Hermes memory is **static text injected at startup**. It stores durable facts:
- Course IDs, quiz IDs, file paths (accumulated across sessions)
- User preferences, environment details

Memory **cannot**:
- Run code (can't query Moodle DB)
- Be per-user (each chat session is a different Moodle user — memory is shared)
- Upload files to Moodle (requires Moodle's file API)
- Check permissions (teacher vs student)

The three layers work together:
```
Memory (automatic):    "CS2310 IRAT1 is quizid=142"     ← static knowledge
Skill (on demand):     "Run quiz_pdf_generator.php"      ← how to generate
Plugin (lifecycle):    "You are user #5, teacher"        ← who am I?
Plugin (tool):         moodle_upload_file(course=3, ...)  ← action
```

## Installation

### From a Hermes install (any platform)

```bash
# Add this repo as a skill tap
hermes skills tap add dive4dec/local_hermes-synapse

# Install the PDF generation skill
hermes skills install dive4dec/local_hermes-synapse/skills/moodle-pdf-generation

# Install dompdf dependency (one-time, pure PHP)
sh $HERMES_HOME/skills/moodle-pdf-generation/scripts/install_deps.sh

# Install the moodle-bridge plugin (requires MOODLE_CONFIG_PATH env var)
hermes plugins install dive4dec/local_hermes-synapse/plugins/moodle-bridge --enable
```

### From local_hermesagent (Moodle plugin bootstrap.sh)

`bootstrap.sh` handles all of the above automatically. See the local_hermesagent repo for details.

## Dependency management

Unlike hermes-usb-portable (which downloads everything at runtime with inconsistent version pinning), this repo:

- **Pins versions** — dompdf v3.1.5 is hardcoded in `install_deps.sh`
- **Verifies downloads** — zip integrity checked before extraction
- **Platform-independent** — dompdf is pure PHP, no arch/libc detection needed
- **Self-contained** — `install_deps.sh` is the only network call, runs once
- **Idempotent** — skips if already installed

For future skills with platform-specific binary dependencies (like uv, Node.js, ripgrep), use the cross-platform detection pattern from local_hermesagent's `bootstrap.sh` (uname + libc check).
