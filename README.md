# agent workcell

An opinionated, containerized environment for running TUI coding agents in YOLO mode, with
Chrome integration, Flutter host bridge support, selective persistence, and isolated GPG-signed
commits.

Supports [Claude Code](https://claude.ai/code), [OpenCode](https://opencode.ai/), and
[Codex](https://github.com/openai/codex), selectable per launch. It is geared toward Rust,
Python, TypeScript, and Flutter development. A global context file is symlinked into each agent
config so the agent is aware of the sandbox's capabilities and constraints.

## Documentation

- [Chrome integration](docs/chrome-integration.md) - host Chrome control for web development.
- [Flutter integration](docs/flutter-integration.md) - in-container SDK and host bridge for
  native/device Flutter work.
- [GPG setup](docs/gpg-setup.md) - verified Git commits from inside the workcell.

## Prerequisites

- Docker installed
- macOS, Linux, or WSL2

Optional integrations have their own host requirements:

- Chrome integration requires Google Chrome and `socat`.
- Flutter bridge integration requires the Flutter SDK and at least one configured target on the host.
- GPG signing requires `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, and `GPG_SIGNING=true` in `config.sh`.

## Setup

### 1. Add the shell alias

Add this to your `~/.zshrc`:

```bash
alias workcell="/path/to/agent-workcell/cli.sh"
```

Replace `/path/to/agent-workcell` with the actual path to this repository, then reload your shell:

```bash
source ~/.zshrc
```

### 2. Build the image

Build the image before first use. Rebuilding also refreshes the bundled agent TUIs in the image to
their latest releases.

```bash
# Build the image
workcell build
```

### 3. Authenticate

Run the workcell with a selected agent once to authenticate with the corresponding account. See
[Run Agents](#run-agents) below for the commands.

### 4. Configure optional integrations

Copy the config template before enabling optional integrations:

```bash
cp config.template.sh config.sh
```

Then follow the focused setup guide you need:

- [Chrome integration](docs/chrome-integration.md)
- [Flutter integration](docs/flutter-integration.md)
- [GPG setup](docs/gpg-setup.md)

`config.sh` is gitignored so personal paths, ports, and identities are not committed.

## Command Reference

### Build

```bash
# Build the image
workcell build
```

`workcell build` runs `docker compose build` from the workcell repository root, so it works even
when you invoke `workcell` from another directory.

### Run Agents

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

# With a prompt
workcell run --yolo -p "fix the tests"

# Pass agent-specific arguments
workcell run --resume
workcell run opencode run "summarize the repo"
workcell run codex "fix the tests"
```

The first positional arg after `run` selects the agent: `claude` (default), `opencode`, or
`codex`. All agents use the same sandbox image, persistent Docker volume, and core flags.

`--with-chrome` and `--with-flutter` are mutually exclusive. In Chrome mode, `--port` exposes
container dev servers to the host. In Flutter mode, `--port` selects the host Flutter bridge port.

`--yolo` maps to each agent's native bypass:

- **claude**: `--dangerously-skip-permissions`
- **opencode**: `{"permission":"allow"}` injected through `OPENCODE_CONFIG_CONTENT`
- **codex**: `--dangerously-bypass-approvals-and-sandbox`

Running `workcell` without a command defaults to `run` with claude:

```bash
workcell --yolo
```

See [Integrations](#integrations) for Chrome, Flutter, and port examples.

### Integrations

```bash
# Chrome enabled for web development
workcell run --with-chrome
workcell run --yolo --with-chrome --port 3000

# Expose container dev-server ports to the host
workcell run --port 3000
workcell run --port 3000 --port 5173

# Start Chrome independently on the host
workcell start-chrome
workcell start-chrome --restart
workcell start-chrome --port 9333 --profile "Profile 1"

# Flutter native/device bridge
workcell run --with-flutter
workcell run codex --with-flutter --port 8765

# Start the Flutter bridge independently on the host
workcell start-flutter-bridge
workcell start-flutter-bridge --port 8766 --project ~/my-flutter-app
```

See [Chrome integration](docs/chrome-integration.md) and
[Flutter integration](docs/flutter-integration.md) for setup details.

### Settings

```bash
workcell settings claude
workcell settings opencode
workcell settings codex
```

These commands open an agent's config file in `vi` inside the workcell Docker volume. The agent
argument is required to avoid accidentally editing the wrong file.

### GPG Keys

```bash
workcell gpg-new
workcell gpg-export --file my-key-backup.asc
workcell gpg-import --file my-key-backup.asc
workcell gpg-revoke --file revoke.asc
workcell gpg-erase
```

See [GPG setup](docs/gpg-setup.md) for key setup, backup, and rotation guidance.

### OpenCode Sessions

```bash
workcell opencode-sessions-export
workcell opencode-sessions-import
```

These commands export and import OpenCode sessions between the Docker volume and
`.workcell/opencode-sessions/`.

### Volume Management

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

Volume commands affect the persisted user data described below.

## How It Works

- Your current directory is mounted at `/workspaces/<project-name>` inside the container.
- Workspace-local workcell files for the current project live under `.workcell/`.
- Claude session history for the project is stored in `.workcell/claude-sessions/`.
- OpenCode session history and storage persist in the Docker volume under
  `~/.local/share/opencode/`.
- Codex auth, config, history, logs, and session data persist under `~/.codex/`, with project
  conversation files bind-mounted into `.workcell/codex-sessions/`.
- Agent settings, credentials, GPG keys, Rust toolchains, Node versions, and global npm packages
  persist in the `agent-workcell` Docker volume.
- The container runs as a non-root `agent` user.
- Filesystem access is isolated to the mounted project directory.
- Host services are reachable from the container through `host.docker.internal`.
- Dev server ports can be exposed with `--port <port>` except in Flutter mode, where `--port`
  selects the host bridge port.
- `/opt/agent-context.md` is symlinked as `~/.claude/CLAUDE.md`,
  `~/.config/opencode/AGENTS.md`, and `~/.codex/AGENTS.md`; focused tool-specific context docs are
  available at `/opt/agent-context-web.md` and `/opt/agent-context-flutter.md`.

## Persistence

User-level data is stored in a Docker volume named `agent-workcell`, mounted at
`/home/agent/persist` inside the container.

Important persisted paths include:

- `~/.claude/` - Claude Code credentials, settings, global context, and install state.
- `~/.config/opencode/` - OpenCode configuration and global context.
- `~/.local/state/opencode/` - OpenCode local UI state.
- `~/.local/share/opencode/` - OpenCode auth, logs, database, and storage.
- `~/.codex/` - Codex auth, config, history, logs, and global context.
- `~/.rustup/` and `~/.cargo/` - Rust toolchains, registry cache, and installed binaries.
- `~/.gnupg/` - GPG keys for commit signing when enabled.
- `~/.nvm/` - Node.js versions and global npm packages.
- `~/persist/.flutter-sdk/` - Flutter SDK (seeded from image on first run; `flutter` and `dart` on PATH).
- `~/.pub-cache/` - Dart pub package cache shared across projects.
- `~/.flutter/` - Flutter CLI config and version state.

The entrypoint sets up symlinks and seeds toolchain templates on first run so each tool sees its
expected home directory paths.

> **Security note.** Agent credentials are stored as plaintext inside the Docker volume. Treat the
> `agent-workcell` volume and its backups as sensitive.

### Workspace-local data

Each project gets a `.workcell/` directory for project-scoped agent state:

- `.workcell/artifacts/` - temporary agent artifacts such as screenshots, logs, traces, and
  generated previews. Agents may create optional subdirectories such as `screenshots/`, `logs/`,
  and `mockups/` when that helps organize related files. Use timestamped filenames such as
  `screenshots/20260429-132400-home-page.png`.
- `.workcell/claude-sessions/` - bind-mounted Claude project sessions.
- `.workcell/opencode-sessions/` - exported OpenCode session backups.
- `.workcell/codex-sessions/` - workspace-local Codex conversation files.
- `.workcell/tasks/` - multi-agent task files and scratch notes.
- `.workcell/flutter-config.json` - project-local Flutter bridge launch and connection settings
  when Flutter integration is used.

Example `.workcell/` layout:

```text
.workcell/
├── .gitignore
├── artifacts/
│   ├── screenshots/
│   ├── logs/
│   └── mockups/
├── claude-sessions/
├── codex-sessions/
├── opencode-sessions/
├── tasks/
└── flutter-config.json
```

On first run, the launcher creates `.workcell/.gitignore` if it does not already exist:

```gitignore
.DS_Store
flutter-config.json
artifacts/
```

It is recommended to gitignore `.workcell/` in the parent project repository. If you want version
control for local agent state, initialize a separate Git repository inside `.workcell/`.

### OpenCode session backup

OpenCode stores its live session database in the Docker volume. Export sessions to workspace-local
JSON files before removing the volume. See [OpenCode sessions](#opencode-sessions).

## Available Tools

| Category | Tools |
|----------|-------|
| **Languages** | Node.js LTS through nvm, Python 3.11, Rust stable |
| **Node.js** | `nvm`, `npm`, `npx` |
| **Python** | `pyright`, `ruff`, `playwright`, `matplotlib`, `numpy` |
| **Browser** | Chrome automation support |
| **Flutter SDK** | `flutter`, `dart` — tests, analysis, formatting, pub (in-container, no host setup) |
| **Flutter Bridge** | `flutterctl` — launch, hot-reload, screenshots, and macOS-hosted macOS/iOS Simulator UI automation via host bridge |
| **Database** | `psql` |
| **Utilities** | `git`, `curl`, `wget`, `jq`, `yq`, `ripgrep`, `fd` |

## Network Restrictions

Use `--firewalled` to restrict network access to essential agent and tooling domains:

- Anthropic API
- OpenAI / Codex
- OpenCode, including Zen and Go
- JavaScript and TypeScript package registries
- Rust package registries and docs
- GitHub

This reduces the risk of data exfiltration while still allowing agents to fetch docs and install
packages.

## Project Structure

```text
agent-workcell/
├── README.md
├── docs/
│   ├── chrome-integration.md
│   ├── flutter-integration.md
│   └── gpg-setup.md
├── docker-compose.yml
├── cli.sh
├── config.template.sh
├── config.sh
├── scripts/
│   ├── run_sandbox.sh
│   ├── start-chrome-debug.sh
│   ├── start-flutter-bridge.sh
│   └── flutter-bridge.py
└── sandbox/
    ├── agent-context.md
    ├── agent-context-web.md
    ├── agent-context-flutter.md
    ├── Dockerfile
    ├── entrypoint.sh
    ├── init-firewall.sh
    ├── browser-tools/
    └── flutter-tools/
```

## License

This project is licensed under the [Apache License, Version 2.0](LICENSE).

## Contribution

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion by
you shall be licensed as Apache-2.0 without any additional terms or conditions.
