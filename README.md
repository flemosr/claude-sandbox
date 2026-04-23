# Agent Sandbox

An opinionated, containerized environment for running coding agents in YOLO mode, with Chrome
integration, selective persistence, and isolated GPG-signed commits.

Supports [Claude Code](https://claude.ai/code) and [opencode](https://opencode.ai/), selectable
per-launch. Geared towards Rust, Python, and TypeScript development. A global context file is
injected so the agent is aware of the sandbox's capabilities and constraints.

## Prerequisites

- Docker installed
- macOS (or Linux/WSL2)

## Setup

### 1. Build the sandbox image

```bash
docker compose build
```

### 2. Add the shell alias

Add this to your `~/.zshrc`:

```bash
alias agent-sandbox="/path/to/agent-sandbox/cli.sh"
```

Replace `/path/to/agent-sandbox` with the actual path to this repository.

Then reload your shell:

```bash
source ~/.zshrc
```

### 3. Authenticate (first time only)

Run the sandbox once to authenticate with your Anthropic account:

```bash
agent-sandbox run
```

### 4. Configure Chrome (optional)

To use browser integration (`--with-chrome`), you need to configure Chrome settings.

**Install socat** (required for Chrome integration):

```bash
brew install socat
```

**Create a dedicated Chrome profile for Claude:**

1. Open Chrome and click your profile icon (top-right)
2. Click "Add" to create a new profile
3. Name it "Claude" (or any name you prefer)
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

To have commits made inside the sandbox show as "Verified" on GitHub, enable GPG signing in your
`config.sh`:

```bash
GIT_AUTHOR_NAME="Sandbox Agent Name"
GIT_AUTHOR_EMAIL="agent@example.local"
GPG_SIGNING=true
```

On first launch, the sandbox generates a passphrase-less ed25519 GPG key and prints the public key.
If you want the agent's commits to appear as verified on GitHub, add it to your account at:
**Settings > SSH and GPG keys > New GPG key**.

The key is persisted in the Docker volume, so it survives container restarts and image rebuilds.

See [Manage GPG keys](#manage-gpg-keys) for export, import, revocation, and other key management
commands.

## Usage

### Run the sandbox

Navigate to any project directory and run:

```bash
# Normal mode (defaults to claude)
agent-sandbox run

# Explicit agent selection
agent-sandbox run claude
agent-sandbox run opencode

# YOLO mode (no permission prompts)
agent-sandbox run --yolo
agent-sandbox run opencode --yolo

# Firewalled mode (restricted network access)
agent-sandbox run --firewalled

# Chrome enabled (browser control)
agent-sandbox run --with-chrome

# Expose a port for dev server (accessible at localhost:3000 on host)
agent-sandbox run --port 3000

# Multiple ports
agent-sandbox run --port 3000 --port 5173

# Web dev setup: YOLO + Chrome + port exposed
agent-sandbox run --yolo --with-chrome --port 3000

# YOLO + firewalled
agent-sandbox run --yolo --firewalled

# With a prompt
agent-sandbox run --yolo -p "fix the tests"

# Pass any agent-specific arguments
agent-sandbox run --resume
agent-sandbox run opencode run "summarize the repo"
```

**Choosing an agent.** The first positional arg after `run` selects the agent: `claude` (default)
or `opencode`. Omitting it runs claude for backwards compatibility. Both agents use the same
sandbox image, the same persistent Docker volume, and the same `--yolo` / `--firewalled` /
`--with-chrome` / `--port` flags. `--yolo` maps to each agent's native bypass:

- **claude** → `--dangerously-skip-permissions` CLI flag
- **opencode** → `{"permission":"allow"}` injected via the `OPENCODE_CONFIG_CONTENT` env var
  (opencode's CLI flag only applies to the non-interactive `run` subcommand, not the TUI)

**Shorthand:** Running `agent-sandbox` without a command defaults to `run` with claude:

```bash
agent-sandbox --yolo --with-chrome --port 3000
```

### Start Chrome separately

If you want to start Chrome independently (e.g., to keep it running across sandbox sessions):

```bash
# Start Chrome with remote debugging
agent-sandbox start-chrome

# Auto-restart if Chrome is running
agent-sandbox start-chrome --restart

# Override settings from config
agent-sandbox start-chrome --port 9333 --profile "Profile 1"
```

### Manage GPG keys

```bash
# Generate a new key (reads identity from config.sh)
agent-sandbox gpg-new

# Export the sandbox GPG key
agent-sandbox gpg-export --file my-key-backup.asc

# Import a previously exported key
agent-sandbox gpg-import --file my-key-backup.asc

# Generate a revocation certificate
agent-sandbox gpg-revoke --file revoke.asc

# Erase all GPG keys from the sandbox
agent-sandbox gpg-erase
```

### Edit sandbox settings

Open an agent's config file in `vi` (inside the sandbox Docker volume). The agent argument is
required — there is no default, to avoid accidentally editing the wrong file:

```bash
# Claude Code: edits ~/.claude/settings.json
agent-sandbox settings claude

# opencode: edits ~/.config/opencode/opencode.jsonc if present,
# otherwise ~/.config/opencode/opencode.json
agent-sandbox settings opencode
```

If no opencode config file exists yet, `agent-sandbox settings opencode` creates a minimal
`opencode.json` with the schema URL before opening it.

These edits persist across container restarts.

## How it works

- Your current directory is mounted at `/workspaces/<project-name>` inside the container
- Workspace-local sandbox files for the current project live under `.agent-sandbox/`
- Claude session history for the project is stored in `.agent-sandbox/claude-sessions/`
- `.agent-sandbox/tasks/` is created for task-management files and other local multi-agent scratch work
- opencode session history and storage persist in the Docker volume under
  `~/.local/share/opencode/`
- Agent settings (claude and opencode) persist between sessions via a Docker volume
- The container runs as non-root user `claude` for safety (the username is kept as `claude` for
  backwards compatibility, regardless of which agent is launched)
- Full network access is available (for web searches, docs, git, etc.)
- Filesystem access is isolated to the mounted directory
- Host services are accessible via `host.docker.internal`
- Dev server ports can be exposed with `--port <port>` (sets `$EXPOSED_PORTS` env var)
- A global context file is injected as `~/.claude/CLAUDE.md` (claude) and
  `~/.config/opencode/AGENTS.md` (opencode) to inform each agent about the sandbox environment
- With `--with-chrome`, agents can control Chrome on the host for web development

## Persistence

### User data (Docker volume)

User-level data (credentials, settings, plugins) is stored in a Docker volume `agent-sandbox`,
mounted at `/home/claude/persist` inside the container.

```
agent-sandbox → /home/claude/persist/
├── .claude/                  # Claude Code configuration (~/.claude)
│   ├── .credentials.json     # (plaintext — keep the volume private)
│   ├── settings.json
│   ├── CLAUDE.md             # Global agent context (claude)
│   └── ...
├── .claude.json              # Onboarding state, theme, user ID
├── .claude-versions/         # Claude Code binary versions
│   └── versions/             # Downloaded Claude Code updates
├── .config/opencode/         # opencode configuration (~/.config/opencode)
│   ├── opencode.json{,c}
│   └── AGENTS.md             # Global agent context (opencode)
├── .local/state/opencode/    # opencode local UI state (~/.local/state/opencode)
│   └── model.json            # recent/favorite models and per-model variants
├── .local/share/opencode/    # opencode data (~/.local/share/opencode)
│   ├── auth.json             # (plaintext provider credentials)
│   ├── log/
│   ├── opencode.db           # session/message history
│   └── storage/              # additional opencode session artifacts
├── .opencode/                # opencode install home (binary + bundled dependencies)
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
- `~/.rustup` → `~/persist/.rustup`
- `~/.cargo` → `~/persist/.cargo`
- `~/.gnupg` → `~/persist/.gnupg`
- `~/.nvm` → `~/persist/.nvm`

This ensures authentication, settings, opencode's local model-picker state, installed claude
and opencode versions, Rust toolchains, Node.js versions, and global npm packages persist across
container restarts and image rebuilds.

> **Security note.** Both agents store credentials as plaintext inside the Docker volume
> (`~/.claude/.credentials.json` for claude, `~/.local/share/opencode/auth.json` for opencode).
> Anyone who can read the `agent-sandbox` volume can read those keys. Treat volume backups
> (`agent-sandbox volume-backup`) as sensitive.

### Workspace-local sandbox data

The sandbox creates a workspace-local `.agent-sandbox/` directory for project-scoped agent
sessions and task-management files:

- `.agent-sandbox/claude-sessions/` — bind-mounted to claude's per-project session dir
  (`~/persist/.claude/projects/-workspaces-<project>/`)
- `.agent-sandbox/opencode-sessions/` — destination for `agent-sandbox opencode-sessions-export`
  (one JSON file per session; see [opencode session data](#opencode-session-data))
- `.agent-sandbox/tasks/` — task-management files and scratch notes for multi-agent workflows

If you already have `.agent-sessions/claude/` from an earlier sandbox version, the next Claude
launch moves it to `.agent-sandbox/claude-sessions/` automatically.

### opencode session data

opencode persists its session state in the Docker volume:

- `~/persist/.local/share/opencode/opencode.db` — session/message records
- `~/persist/.local/share/opencode/storage/` — additional session artifacts such as
  `session_diff/` and migration metadata

This means opencode sessions survive sandbox restarts and image rebuilds, but they are tied to the
Docker volume rather than the workspace tree. To keep a workspace-local backup that survives
`agent-sandbox volume-rm`, export them:

```bash
agent-sandbox opencode-sessions-export
```

This writes one JSON file per session to `.agent-sandbox/opencode-sessions/<session-id>.json`,
auto-scoped to the current workspace (opencode derives the project ID from the git root-commit
SHA, or uses `"global"` for non-git directories). Re-running the command overwrites existing
files; session files for sessions later deleted in opencode are left in place as recovery
artifacts. Use opencode's native `opencode import` to restore a session.

> **Tip.** Add `.agent-sandbox/` to your `.gitignore` (global or per-repo). These files are local
> state, not source — and like any agent history they may contain secrets the agent read during
> the session.

### Managing the volume

```bash
# Open a shell in the volume
agent-sandbox volume-shell

# Backup the volume
agent-sandbox volume-backup --file agent-sandbox-bkp.tgz

# Restore from backup
agent-sandbox volume-restore --file agent-sandbox-bkp.tgz

# Remove the volume
agent-sandbox volume-rm
```

## Browser Integration (Web Development)

The sandbox includes browser control tools for web development workflows. Claude can interact with
Chrome running on your host machine via the Chrome DevTools Protocol (CDP).

### Prerequisites

Install `socat` for port forwarding (one-time setup):

```bash
brew install socat
```

### Usage

Simply use the `--with-chrome` flag:

```bash
agent-sandbox --with-chrome
```

This automatically:
1. Starts Chrome with remote debugging (using your "claude" profile)
2. Sets up port forwarding via socat
3. Sets `CHROME_LOG` env var and mounts the log file (for troubleshooting)
4. Cleans up Chrome when the sandbox exits

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
agent-sandbox --with-chrome --port 3000
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
1. Start sandbox with port: `agent-sandbox --with-chrome --port 3000`

*Agent (in container):*  
2. Start dev server: `npm run dev -- --host 0.0.0.0` (must bind to 0.0.0.0)  
3. Navigate Chrome: `browser goto "http://localhost:3000"` (Chrome is on host)

## Available Tools

The sandbox comes with the following pre-installed:

| Category | Tools |
|----------|-------|
| **Languages** | Node.js LTS (via nvm), Python 3.11, Rust (stable) |
| **Node.js** | `nvm` (version manager), `npm`, `npx` |
| **Python** | `pyright` (type checker), `ruff` (linter), `playwright`, `matplotlib`, `numpy` |
| **Browser** | `browser` CLI for Chrome automation |
| **Database** | `psql` (PostgreSQL client) |
| **Utilities** | `git`, `curl`, `wget`, `jq`, `yq`, `ripgrep`, `fd` |

## Network restrictions

Use the `--firewalled` flag to restrict network access to essential domains only:

- Anthropic API (api.anthropic.com, claude.ai)
- JavaScript/TypeScript (npm, Yarn, nodejs.org)
- Rust (crates.io, docs.rs, rust-lang.org)
- GitHub

This reduces the risk of data exfiltration to unauthorized servers while still allowing Claude to
fetch docs and install packages.

## Project structure

```
agent-sandbox/
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
