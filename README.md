# agent workcell

An opinionated, containerized environment for running TUI coding agents in YOLO mode, with Chrome
integration, Flutter host bridge, selective persistence, and isolated GPG-signed commits.

Supports [Claude Code](https://claude.ai/code), [OpenCode](https://opencode.ai/), and
[Codex](https://github.com/openai/codex), selectable per-launch. Geared towards Rust, Python,
TypeScript, and Flutter development. A global context file is injected so the agent is aware of
the sandbox's capabilities and constraints.

## Prerequisites

- Docker installed
- macOS (or Linux/WSL2)

### Optional: Chrome browser integration

- [Google Chrome](https://www.google.com/chrome/) installed on the host
- `socat` (`brew install socat`, see the [socat manpage](https://manpages.debian.org/socat))

### Optional: Flutter native/device integration

- [Flutter SDK](https://docs.flutter.dev/get-started/install) installed on the host (`flutter doctor`)
- At least one Flutter target configured and available (`flutter devices`)

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
and the same `--yolo` / `--firewalled` / `--with-chrome` / `--with-flutter` / `--port` flags.
`--with-chrome` and `--with-flutter` are mutually exclusive. `--yolo` maps to each agent's native
bypass:

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
- Dev server ports can be exposed with `--port <port>` (sets `$EXPOSED_PORTS` env var),
  except in `--with-flutter` mode where `--port` selects the host bridge port
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

## Flutter Bridge Integration (Native/Device Development)

The workcell includes tools for Flutter development on native targets (iOS Simulator, Android
Emulator, macOS desktop, and physical devices). Agents can edit Dart code inside the container and
control Flutter apps running on the host.

### Prerequisites

- Flutter SDK installed on the host machine
- At least one configured target: iOS Simulator, Android Emulator, macOS desktop, or physical device
- macOS host (primary supported platform; Linux Android Emulator can follow)
- For macOS desktop UI automation and screenshots, allow the host terminal/agent process in macOS
  Accessibility and Screen Recording privacy settings when prompted.

### Setup

Add Flutter bridge settings to `config.sh`:

```bash
# Flutter host bridge integration
FLUTTER_DEFAULT_BRIDGE_PORT=8765
FLUTTER_BRIDGE_LOG_FILE="/tmp/flutter-bridge.log"
```

Project-specific Flutter run settings can live in `.workcell/flutter-config.json`:

```json
{
  "target": "lib/main_dev.dart",
  "run_args": [
    "--flavor",
    "staging",
    "--dart-define",
    "API_BASE_URL=https://api.example.test"
  ]
}
```

The bridge updates the same file with runtime `token` and `port` values when it starts.
When `--with-flutter` starts a bridge, its port is selected from `--port` if supplied,
then `.workcell/flutter-config.json`, then `FLUTTER_DEFAULT_BRIDGE_PORT`.

### Usage

Simply use the `--with-flutter` flag:

```bash
workcell --with-flutter
```

This automatically:
1. Starts a Flutter host bridge HTTP server on the selected port
2. Generates a per-session bearer token for auth
3. Sets `FLUTTER_BRIDGE_URL` and `FLUTTER_BRIDGE_TOKEN` env vars
4. Mounts the bridge log file (for troubleshooting)
5. Cleans up the bridge when the workcell exits

Run `workcell --with-flutter` from the host Flutter project directory. Inside the sandbox,
agents edit files through the mounted workspace path, while the bridge runs host-side
`flutter` commands from that same project directory.

The agent can use `flutterctl test` to check if the bridge is available.

Use `--port` to select the bridge port for this run:

```bash
workcell --with-flutter --port 8765
workcell run opencode --yolo --with-flutter --port 8766
```

`--with-flutter` and `--with-chrome` cannot be used together. Use `--with-chrome` for Flutter web
and `--with-flutter` for native/device targets. In Flutter mode, `--port` is the host bridge port;
it does not expose a container dev-server port.

### Start Flutter Bridge Separately

If you want to start the bridge independently (e.g., to keep it running across workcell sessions):

```bash
# Start Flutter bridge using defaults and project-local settings
workcell start-flutter-bridge

# Override bridge settings
workcell start-flutter-bridge --port 8766 --project ~/my-flutter-app
```

Then run the workcell without `--with-flutter`. The launcher writes connection details to
`.workcell/flutter-config.json`, and `flutterctl` reads that file automatically. The bridge
starts without a selected device; agents choose a target later with `flutterctl devices` and
`flutterctl launch --device <id>`.

### Agent Workflow Inside Container

```bash
# Verify connection
flutterctl test

# Check bridge status
flutterctl status

# List available devices
flutterctl devices

# Launch app on a device
flutterctl launch --device macos

# Take screenshot before changes
flutterctl screenshot -o before.png

# ... edit Dart files in the container ...

# Hot reload
flutterctl hot-reload

# Take screenshot after changes
flutterctl screenshot -o after.png

# Check UI automation capability before using UI action commands
flutterctl status

# UI action commands return structured errors until the active backend
# reports support in status.ui_automation.actions
flutterctl tap --x 150 --y 300
flutterctl tap --text "Sign in"
flutterctl tap --key addItemButton
flutterctl type "hello"
flutterctl press enter
flutterctl scroll --dy 600
flutterctl inspect --text "Settings"
flutterctl inspect --key addItemButton
flutterctl wait --text "Ready" --timeout 5000
flutterctl wait --key addItemButton --timeout 5000

# View logs
flutterctl logs
```

`flutterctl status` includes a `ui_automation` object with backend, target
platform, readiness, missing host tools, coordinate-space metadata, and
per-action capabilities. Treat `status.ui_automation.actions` as authoritative
before using `tap`, `type`, `press`, `scroll`, `inspect`, or `wait`.
For macOS desktop, coordinate taps use `app-window-points`: `x=0,y=0` is the
top-left of the Flutter app window reported in `status.ui_automation.screen`,
not the top-left of the full display.
macOS `scroll` approximates scrolling with keyboard dispatch (`pagedown`,
`pageup`, arrows, `home`, or `end`), so `dx`/`dy` values choose direction and
dominant axis rather than a pixel-exact distance. The actual movement depends
on current focus and how the Flutter widget handles those keys.
macOS `inspect`, `wait --text`, `wait --key`, `tap --text`, and `tap --key`
use the host Accessibility tree plus Flutter inspector text previews, widget
keys, and selected tooltip labels when a VM service is available. Key selectors
are exact matches against Flutter inspector `ValueKey` diagnostics and require
the bridge to derive a rectangle for the keyed widget.
Returned rectangles are normalized into the same `app-window-points`
coordinate space when the backend can derive bounds.
Prefer widget-key selectors for agent-driven Flutter UI interactions when the
app can provide them. Stable, descriptive `ValueKey<String>` values on controls
and important containers give agents a reliable target that is independent of
visible copy, localization, and layout changes. For example, key primary
buttons, text fields, list views, tabs, row actions, and other repeated controls
with names such as `login_button`, `email_field`, `settings_tab`,
`todo_list`, or `delete_item_0`. Agents should check `flutterctl status` for
`key` selector support, use `flutterctl inspect --key <key>` to verify the
resolved rectangle, and then prefer `tap --key` / `wait --key` over text or
coordinate selectors.
For efficiency, agents should use `flutterctl inspect` as the primary
text-based interface for discovering current UI elements, widget keys, visible
text, widget types, and resolved rectangles. Use screenshots as a fallback when
inspection cannot resolve a target, when visual layout is ambiguous, or when
visual validation is needed after an action.
Text selectors are not arbitrary Flutter widget selectors: they work only for
elements that `inspect` can resolve to a rectangle, such as visible `Text`
previews, macOS Accessibility labels, and selected tooltip labels whose bounds
can be derived. Key selectors work only when the Flutter inspector exposes the
key and layout data for the same widget. Custom controls, tooltip-only widgets
without derivable bounds, and widgets without visible text, accessible labels,
or exposed keys may require coordinate taps instead. Run `flutterctl inspect`
first when targeting anything beyond obvious visible text.

UI automation is currently scoped to iOS Simulator and macOS desktop backends.
Android, Linux desktop, Windows desktop, physical iOS, and Flutter web are not
supported by the Flutter bridge UI action API. Flutter web should use the
Chrome/CDP workflow. The bridge returns structured errors such as
`NO_APP_RUNNING`, `UI_NOT_READY`, `UNSUPPORTED_TARGET`, `INVALID_BODY`, and
`UNKNOWN_KEY` when an action cannot run.

On macOS desktop, `flutterctl screenshot` captures only the Flutter app window.
If the bridge cannot identify a visible app window or macOS privacy permissions
block capture, the command fails instead of falling back to a full-screen
screenshot.

### How It Works

```
┌──────────────────────────────────────────────────────────────────────┐
│  HOST (Mac)                                                          │
│                                                                      │
│   Flutter Bridge ◄─── HTTP API (port 8765)                           │
│   0.0.0.0:8765       bearer token auth                               │
│   │                                                                  │
│   ├── flutter run / flutter attach  (subprocess management)          │
│   ├── flutter screenshot             (on-demand)                     │
│   ├── flutter devices                (device discovery)              │
│   └── UI automation capability/status and action API                 │
│                                                                      │
│   iOS Simulator / Android Emulator / macOS Desktop / Device          │
└──────────────────────────────────────────────────────────────────────┘
                                   ▲
                                   │ host.docker.internal:8765
                                   │ (Authorization: Bearer <token>)
┌──────────────────────────────────────────────────────────────────────┐
│  CONTAINER                                                           │
│                                                                      │
│   flutterctl ◄─── FLUTTER_BRIDGE_URL / TOKEN env vars                │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### Limitations

- **One bridge per sandbox/agent.** A `workcell run --with-flutter` session starts a dedicated
  bridge for that sandbox. Multiple sandboxes should use distinct bridge ports and run from the
  corresponding host Flutter project directories.
- **macOS first.** The host bridge targets macOS as the primary platform. Linux Android Emulator
  support can follow. Windows is out of scope for MVP.
- **Native targets only.** Flutter web is handled separately via Chrome/CDP integration
  (`--with-chrome`). The Flutter bridge targets iOS Simulator, Android Emulator, macOS desktop,
  Linux desktop, and physical devices.
- **Fixed project scope.** The bridge operates on a single project directory configured at startup.
  It does not allow the agent to switch to arbitrary host directories.
- **No arbitrary command execution.** The bridge API is fixed: launch, attach, detach, hot-reload,
  hot-restart, screenshot, logs, status, and device discovery. There is no general-purpose exec
  endpoint.
- **Hot reload only.** The MVP supports hot reload (`r`) and hot restart (`R`) via the managed
  Flutter subprocess. Tap/type/scroll UI automation is planned for a future release.
- **Single configured port per bridge.** Automatic multi-instance port allocation is not yet
  supported, so concurrent bridge instances need manually configured ports.

### Troubleshooting

Check the Flutter bridge log if you have connection issues:

```bash
# From host
cat /tmp/flutter-bridge.log

# From container
cat "$FLUTTER_BRIDGE_LOG_FILE"
```

Common issues:

1. **"Cannot reach Flutter bridge"** — the bridge is not running. Start it with
   `workcell start-flutter-bridge` or add `--with-flutter` to `workcell run`.
2. **"Missing FLUTTER_BRIDGE_TOKEN"** — token not available. When using `--with-flutter`,
   the token is auto-generated. For a separately started bridge, run
   `workcell start-flutter-bridge` from the workspace so `.workcell/flutter-config.json`
   is available to the sandbox.
3. **Concurrent sandbox needs a bridge** — start a separate bridge on a different port;
   bridge instances are not shared between agents by default.
4. **"Port 8765 is already in use"** — the port is occupied. Use a different `--port`,
   update `.workcell/flutter-config.json`, or kill the existing process.
5. **Flutter subprocess fails to start** — ensure your Flutter project compiles and the target
   device/simulator is available. Run `flutter doctor -v` on the host to verify your setup.
6. **"flutter: command not found"** — Flutter SDK is not on PATH. Set `FLUTTER_PATH` in `config.sh`
   to the full path to the Flutter binary.

## Available Tools

The workcell comes with the following pre-installed:

| Category | Tools |
|----------|-------|
| **Languages** | Node.js LTS (via nvm), Python 3.11, Rust (stable) |
| **Node.js** | `nvm` (version manager), `npm`, `npx` |
| **Python** | `pyright` (type checker), `ruff` (linter), `playwright`, `matplotlib`, `numpy` |
| **Browser** | `browser` CLI for Chrome automation |
| **Flutter** | `flutterctl` CLI for Flutter bridge control |
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
│   ├── start-chrome-debug.sh   # Chrome debug launcher
│   ├── start-flutter-bridge.sh # Flutter bridge launcher
│   └── flutter-bridge.py       # Flutter bridge HTTP server
└── sandbox/
    ├── agent-context.md        # Global context for the sandboxed agent
    ├── Dockerfile
    ├── entrypoint.sh
    ├── init-firewall.sh
    ├── browser-tools/          # Browser control utilities
    │   ├── browser.sh          # CLI wrapper
    │   └── browser.py          # Python module
    └── flutter-tools/          # Flutter bridge control utilities
        ├── flutterctl.sh       # CLI wrapper
        └── flutterctl.py       # Python module
```

## License

This project is licensed under the [Apache License (Version 2.0)](LICENSE).

## Contribution

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion by
you, shall be licensed as Apache-2.0, without any additional terms or conditions.
