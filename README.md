# agent workcell

An opinionated, containerized environment for running TUI coding agents in YOLO mode, with Chrome
integration, selective persistence, and isolated GPG-signed commits.

Supports [Claude Code](https://claude.ai/code), [OpenCode](https://opencode.ai/), and
[Codex](https://github.com/openai/codex), selectable per-launch. Geared towards Rust, Python, and
TypeScript development. A global context file is injected so the agent is aware of the sandbox's
capabilities and constraints.

## Prerequisites

- Docker installed
- macOS (or Linux/WSL2)

## Setup

### 1. Add the shell alias

Add this to your `~/.zshrc`:

```bash
alias workcell="/path/to/agent-workcell/cli.sh"
```

Replace `/path/to/agent-workcell` with the actual path to this repository.

Then reload your shell:

```bash
source ~/.zshrc
```

### 2. Build the `agent-workcell` image

```bash
workcell build
```

This runs `docker compose build` from the workcell repository root, so it works even when you invoke
`workcell` from another directory. Rebuilding also refreshes the bundled agent TUIs in the image to
their latest releases.

### 3. Authenticate (first time only)

Run the workcell with a selected agent once to authenticate with your corresponding account:

```bash
workcell run claude
```

### 4. Configure Chrome (optional)

To use browser integration (`--with-chrome`), you need to configure Chrome settings.

**Install socat** (required for Chrome integration):

```bash
brew install socat
```

**Create a dedicated Chrome profile for Agent:**

1. Open Chrome and click your profile icon (top-right)
2. Click "Add" to create a new profile
3. Name it "Agent" (or any name you prefer)
4. Go to `chrome://version` in the new profile
5. Look at "Profile Path" - note the last folder name (e.g., "Profile 3")

**Create your config file:**

```bash
cp config.template.sh config.sh
```

Edit `config.sh` and set `CHROME_PROFILE` to your profile's folder name:

```bash
CHROME_PROFILE="Profile 3"  # <-- Use folder name from chrome://version
```

Your `config.sh` is gitignored, so your personal settings won't be committed.

### 5. Configure GPG commit signing (optional)

To have commits made inside the workcell show as "Verified" on GitHub, enable GPG signing in your
`config.sh`:

```bash
GIT_AUTHOR_NAME="Workcell Agent Name"
GIT_AUTHOR_EMAIL="agent@example.local"
GPG_SIGNING=true
```

On first launch, the workcell generates a passphrase-less ed25519 GPG key and prints the public key.
If you want the agent's commits to appear as verified on GitHub, add it to your account at:
**Settings > SSH and GPG keys > New GPG key**.

The key is persisted in the Docker volume, so it survives container restarts and image rebuilds.

See [Manage GPG keys](#manage-gpg-keys) for export, import, revocation, and other key management
commands.

## Usage

### Run the workcell

Navigate to any project directory and run:

```bash
# Normal mode (defaults to claude)
workcell run

# Explicit agent selection
workcell run claude
workcell run opencode
workcell run codex

# YOLO mode (no permission prompts)
workcell run --yolo
workcell run opencode --yolo
workcell run codex --yolo

# Firewalled mode (restricted network access)
workcell run --firewalled

# Chrome enabled (browser control)
workcell run --with-chrome

# Expose a port for dev server (accessible at localhost:3000 on host)
workcell run --port 3000

# Multiple ports
workcell run --port 3000 --port 5173

# Web dev setup: YOLO + Chrome + port exposed
workcell run --yolo --with-chrome --port 3000

# YOLO + firewalled
workcell run --yolo --firewalled

# With a prompt
workcell run --yolo -p "fix the tests"

# Pass any agent-specific arguments
workcell run --resume
workcell run opencode run "summarize the repo"
workcell run codex "fix the tests"
```

**Choosing an agent.** The first positional arg after `run` selects the agent: `claude` (default),
`opencode`, or `codex`. All agents use the same sandbox image, the same persistent Docker volume,
and the same `--yolo` / `--firewalled` / `--with-chrome` / `--port` flags. `--yolo` maps to each
agent's native bypass:

- **claude** → `--dangerously-skip-permissions` CLI flag
- **opencode** → `{"permission":"allow"}` injected via the `OPENCODE_CONFIG_CONTENT` env var
  (opencode's CLI flag only applies to the non-interactive `run` subcommand, not the TUI)
- **codex** → `--dangerously-bypass-approvals-and-sandbox` CLI flag

**Shorthand:** Running `workcell` without a command defaults to `run` with claude:

```bash
workcell --yolo --with-chrome --port 3000
```

### Start Chrome separately

If you want to start Chrome independently (e.g., to keep it running across workcell sessions):

```bash
# Start Chrome with remote debugging
workcell start-chrome

# Auto-restart if Chrome is running
workcell start-chrome --restart

# Override settings from config
workcell start-chrome --port 9333 --profile "Profile 1"
```

### Manage GPG keys

```bash
# Generate a new key (reads identity from config.sh)
workcell gpg-new

# Export the workcell GPG key
workcell gpg-export --file my-key-backup.asc

# Import a previously exported key
workcell gpg-import --file my-key-backup.asc

# Generate a revocation certificate
workcell gpg-revoke --file revoke.asc

# Erase all GPG keys from the workcell
workcell gpg-erase
```

### Edit workcell settings

Open an agent's config file in `vi` (inside the workcell Docker volume). The agent argument is
required — there is no default, to avoid accidentally editing the wrong file:

```bash
# Claude Code: edits ~/.claude/settings.json. See https://docs.anthropic.com/en/docs/claude-code/settings
workcell settings claude

# OpenCode: edits ~/.config/opencode/opencode.jsonc if present. See https://opencode.ai/docs/config/
# otherwise ~/.config/opencode/opencode.json
workcell settings opencode

# Codex: edits ~/.codex/config.toml. See https://developers.openai.com/codex/config-reference
workcell settings codex
```

If no OpenCode config file exists yet, `workcell settings opencode` creates a minimal
`opencode.json` with the schema URL before opening it.
If no Codex config file exists yet, `workcell settings codex` creates an empty
`config.toml` before opening it.

These edits persist across container restarts.

## How it works

- Your current directory is mounted at `/workspaces/<project-name>` inside the container
- Workspace-local workcell files for the current project live under `.workcell/`
- Claude Code session history for the project is stored in `.workcell/claude-sessions/`
- `.workcell/tasks/` is created for task-management files and other local multi-agent scratch work
- OpenCode session history and storage persist in the Docker volume under
  `~/.local/share/opencode/`
- Codex auth, config, history, and logs persist in the Docker volume under `~/.codex/`
- Codex conversation/session files for the project are bind-mounted into `.workcell/codex-sessions/`
- Agent settings (claude, opencode, and codex) persist between sessions via a Docker volume
- The container runs as non-root user `agent` for safety (agent-neutral, regardless of which agent
  CLI is launched)
- Full network access is available (for web searches, docs, git, etc.)
- Filesystem access is isolated to the mounted directory
- Host services are accessible via `host.docker.internal`
- Dev server ports can be exposed with `--port <port>` (sets `$EXPOSED_PORTS` env var)
- A global context file is injected as `~/.claude/CLAUDE.md` (claude),
  `~/.config/opencode/AGENTS.md` (opencode), and `~/.codex/AGENTS.md` (codex) to inform each
  agent about the sandbox environment
- With `--with-chrome`, agents can control Chrome on the host for web development

## Persistence

### User data (Docker volume)

User-level data (credentials, settings, plugins) is stored in a Docker volume `agent-workcell`,
mounted at `/home/agent/persist` inside the container.

```
agent-workcell → /home/agent/persist/
├── .claude/                  # Claude Code configuration (~/.claude)
│   ├── .credentials.json     # (plaintext — keep the volume private)
│   ├── settings.json
│   ├── CLAUDE.md             # Global agent context (claude)
│   └── ...
├── .claude.json              # Onboarding state, theme, user ID
├── .claude-versions/         # Claude Code binary versions
│   └── versions/             # Downloaded Claude Code updates
├── .config/opencode/         # OpenCode configuration (~/.config/opencode)
│   ├── opencode.json{,c}
│   └── AGENTS.md             # Global agent context (opencode)
├── .local/state/opencode/    # OpenCode local UI state (~/.local/state/opencode)
│   └── model.json            # recent/favorite models and per-model variants
├── .local/share/opencode/    # OpenCode data (~/.local/share/opencode)
│   ├── auth.json             # (plaintext provider credentials)
│   ├── log/
│   ├── opencode.db           # session/message history
│   └── storage/              # additional OpenCode session artifacts
├── .opencode/                # OpenCode install home (binary + bundled dependencies)
├── .codex/                   # Codex configuration and non-session state (~/.codex)
│   ├── config.toml           # User settings
│   ├── auth.json             # (plaintext — keep the volume private)
│   ├── history.jsonl         # Command history
│   ├── log/                  # Logs
│   └── AGENTS.md             # Global agent context (codex)
├── .rustup/                  # Rust toolchains and components
├── .cargo/                   # Cargo registry cache, installed binaries, and config
├── .gnupg/                   # GPG keys for commit signing (when GPG_SIGNING is enabled)
├── .nvm/                     # Node.js versions and global packages
│   ├── versions/node/        # Installed Node.js versions
│   └── ...
```

The entrypoint creates symlinks so tools find their config in the expected locations:

- `~/.claude` → `~/persist/.claude`
- `~/.claude.json` → `~/persist/.claude.json`
- `~/.local/share/claude` → `~/persist/.claude-versions`
- `~/.opencode` → `~/persist/.opencode`
- `~/.config/opencode` → `~/persist/.config/opencode`
- `~/.local/state/opencode` → `~/persist/.local/state/opencode`
- `~/.local/share/opencode` → `~/persist/.local/share/opencode`
- `~/.codex` → `~/persist/.codex`
- `~/.rustup` → `~/persist/.rustup`
- `~/.cargo` → `~/persist/.cargo`
- `~/.gnupg` → `~/persist/.gnupg`
- `~/.nvm` → `~/persist/.nvm`

This ensures authentication, settings, OpenCode's local model-picker state, installed Claude Code
and OpenCode versions, Rust toolchains, Node.js versions, and global npm packages persist
across container restarts and image rebuilds. Codex ships as a standalone binary baked into
the image, so image rebuilds pick up the newer Codex version without any volume interaction.

> **Security note.** All agents store credentials as plaintext inside the Docker volume
> (`~/.claude/.credentials.json` for Claude Code, `~/.local/share/opencode/auth.json` for OpenCode,
> `~/.codex/auth.json` for Codex). Anyone who can read the `agent-workcell` volume can read those
> keys. Treat volume backups (`workcell volume-backup`) as sensitive.

### Workspace-local workcell data

The workcell creates a workspace-local `.workcell/` directory for project-scoped agent
sessions and task-management files:

- `.workcell/claude-sessions/` — bind-mounted to claude's per-project session dir
  (`~/persist/.claude/projects/-workspaces-<project>/`)
- `.workcell/opencode-sessions/` — destination for `workcell opencode-sessions-export`
  (one JSON file per session; see [opencode session data](#opencode-session-data))
- `.workcell/codex-sessions/` — the workspace-local source of truth for Codex conversation
  files, with two sibling subdirectories: `sessions/` (bind-mounted to `~/persist/.codex/sessions/`,
  date-partitioned as `sessions/YYYY/MM/DD/*.jsonl`) and `archived_sessions/` (bind-mounted to
  `~/persist/.codex/archived_sessions/`)
- `.workcell/tasks/` — task-management files and scratch notes for multi-agent workflows
  (see [Multi-agent task files](#multi-agent-task-files))

### Version control for `.workcell`

It is recommended to keep `.workcell/` gitignored by the parent project repository while
initializing a separate Git repository inside `.workcell/`. This keeps agent tasks, session
exports, and other workspace-local state out of the shared project history, while still giving
each user a proper VCS setup for their own agent work.

From the project root:

```bash
echo ".workcell/" >> .gitignore
git -C .workcell init
git -C .workcell add .
git -C .workcell commit -m "Initial workcell state"
```

After that, use `git -C .workcell status`, `git -C .workcell log`, and a private remote if desired.

### Multi-agent task files

`.workcell/tasks/` is a shared scratchpad for coordinating work across multiple agent
sessions — sub-agents within a single run or different agents across different sessions. Agents
are instructed (via the injected global context file) to create a task file whenever a request
spans multiple steps or is likely to continue later, and to read existing task files before
starting non-trivial work so handoffs don't lose context.

Each task file is a single Markdown document named
`YYYYMMDD-HHMMSS-brief-descriptive-slug.md` (UTC timestamp prefix for chronological ordering and
uniqueness across agents). The expected sections are:

- **Status / Created / Updated** — lifecycle metadata.
- **Objective** — what the task aims to accomplish, and why.
- **Context** — background a fresh agent needs (prior discoveries, constraints, user preferences,
  relevant files/commits/PRs).
- **Plan** — checklist of steps.
- **Findings** — append-only, timestamped log of discoveries and decisions. Previous entries are
  never rewritten; corrections are added as new entries.
- **Next Steps** — handoff note left when pausing; cleared on completion.
- **Dependencies** — links to other task files or external blockers.
- **Notes** — free-form scratch area.

Sub-tasks go in their own task files, linked via `Dependencies`, rather than being nested inside
a single file. The full rule set agents follow lives in
[`sandbox/agent-context.md`](sandbox/agent-context.md) under *Task Management (Multi-Agent
Workflows)*.

### OpenCode session data

OpenCode persists its session state in the Docker volume:

- `~/persist/.local/share/opencode/opencode.db` — session/message records
- `~/persist/.local/share/opencode/storage/` — additional session artifacts such as
  `session_diff/` and migration metadata

This means OpenCode sessions survive workcell restarts and image rebuilds, but they are tied to the
Docker volume rather than the workspace tree. To keep a workspace-local backup that survives
`workcell volume-rm`, export them:

```bash
workcell opencode-sessions-export
```

This writes one JSON file per session to `.workcell/opencode-sessions/<session-id>.json`,
auto-scoped to the current workspace (OpenCode derives the project ID from the git root-commit
SHA, or uses `"global"` for non-git directories). Re-running the command overwrites existing
files; session files for sessions later deleted in OpenCode are left in place as recovery
artifacts.

To restore after a `volume-rm` (or on a fresh machine), run:

```bash
workcell opencode-sessions-import
```

This imports every JSON file under `.workcell/opencode-sessions/`. Session IDs and project
scoping are preserved from the JSON, so sessions restore to the original workspace as long as the
git root-commit SHA matches. Re-importing an existing session is a no-op.

> **Tip.** Add `.workcell/` to your `.gitignore` (global or per-repo). These files are local
> state, not source — and like any agent history they may contain secrets the agent read during
> the session.

### Managing the volume

```bash
# Open a shell in the volume
workcell volume-shell

# Backup the volume
workcell volume-backup --file agent-workcell-bkp.tgz

# Restore from backup
workcell volume-restore --file agent-workcell-bkp.tgz

# Remove the volume
workcell volume-rm
```

## Browser Integration (Web Development)

The workcell includes browser control tools for web development workflows. Agents can interact with
Chrome running on your host machine via the Chrome DevTools Protocol (CDP).

### Prerequisites

Install `socat` for port forwarding (one-time setup):

```bash
brew install socat
```

### Usage

Simply use the `--with-chrome` flag:

```bash
workcell --with-chrome
```

This automatically:
1. Starts Chrome with remote debugging (using your "Agent" profile)
2. Sets up port forwarding via socat
3. Sets `CHROME_LOG` env var and mounts the log file (for troubleshooting)
4. Cleans up Chrome when the workcell exits

The agent can use `browser test` to check if Chrome is available.

### How It Works

There are two directions of communication:

**1. Container → Host (Chrome control via CDP)**

Chrome on Mac ignores `--remote-debugging-address=0.0.0.0` and only binds to `127.0.0.1`. Since
Docker containers can't reach the host's localhost directly, we use `socat` as a bridge:

```
┌─────────────────────────────────────────────────────────────────────┐
│  HOST (Mac)                                                         │
│                                                                     │
│   Chrome ◄──────── socat ◄──────── Docker Network                   │
│   127.0.0.1:19222   0.0.0.0:9222    host.docker.internal:9222       │
│   (internal)        (bridge)        (container access)              │
└─────────────────────────────────────────────────────────────────────┘
```

**2. Host → Container (accessing dev servers)**

Dev servers running in the container are exposed via the `--port` flag:

```bash
workcell --with-chrome --port 3000
```

```
┌─────────────────────────────────────────────────────────────────────┐
│  HOST (Mac)                                                         │
│                                                                     │
│   Browser ────► localhost:3000 ────► Docker -p 3000:3000            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  CONTAINER                                                          │
│                                                                     │
│   React/Vite/etc ◄─── 0.0.0.0:3000                                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

The `$EXPOSED_PORTS` env var contains the list of exposed ports (e.g., `3000,5173`).

**Complete flow for web development:**

*User (on host):*
1. Start workcell with port: `workcell --with-chrome --port 3000`

*Agent (in container):*  
2. Start dev server: `npm run dev -- --host 0.0.0.0` (must bind to 0.0.0.0)  
3. Navigate Chrome: `browser goto "http://localhost:3000"` (Chrome is on host)

## Available Tools

The workcell comes with the following pre-installed:

| Category | Tools |
|----------|-------|
| **Languages** | Node.js LTS (via nvm), Python 3.11, Rust (stable) |
| **Node.js** | `nvm` (version manager), `npm`, `npx` |
| **Python** | `pyright` (type checker), `ruff` (linter), `playwright`, `matplotlib`, `numpy` |
| **Browser** | `browser` CLI for Chrome automation |
| **Database** | `psql` (PostgreSQL client) |
| **Utilities** | `git`, `curl`, `wget`, `jq`, `yq`, `ripgrep`, `fd` |

## Network restrictions

Use the `--firewalled` flag to restrict network access to essential agent and tooling domains only:

- Anthropic API (api.anthropic.com, claude.ai)
- OpenAI / Codex (api.openai.com, chatgpt.com, auth.openai.com)
- OpenCode, including Zen and Go (opencode.ai)
- JavaScript/TypeScript (npm, Yarn, nodejs.org)
- Rust (crates.io, docs.rs, rust-lang.org)
- GitHub

This reduces the risk of data exfiltration to unauthorized servers while still allowing the agent
to fetch docs and install packages.

## Project structure

```
agent-workcell/
├── README.md
├── docker-compose.yml
├── cli.sh                      # Main CLI entrypoint
├── config.template.sh          # Configuration template
├── config.sh                   # Your config (create from template, gitignored)
├── scripts/
│   ├── run_sandbox.sh          # Docker container runner
│   └── start-chrome-debug.sh   # Chrome debug launcher
└── sandbox/
    ├── agent-context.md        # Global context for the sandboxed agent
    ├── Dockerfile
    ├── entrypoint.sh
    ├── init-firewall.sh
    └── browser-tools/          # Browser control utilities
        ├── browser.sh          # CLI wrapper
        └── browser.py          # Python module
```

## License

This project is licensed under the [Apache License (Version 2.0)](LICENSE).

## Contribution

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion by
you, shall be licensed as Apache-2.0, without any additional terms or conditions.
