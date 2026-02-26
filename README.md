# Claude Code Sandbox

An opinionated, containerized environment for running Claude Code in YOLO mode, with Chrome
integration, selective persistence, and isolated GPG-signed commits.

Geared towards Rust, Python, and TypeScript development. A global context file is injected so the
agent is aware of the sandbox's capabilities and constraints.

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
alias claude-sandbox="/path/to/claude-sandbox/cli.sh"
```

Replace `/path/to/claude-sandbox` with the actual path to this repository.

Then reload your shell:

```bash
source ~/.zshrc
```

### 3. Authenticate (first time only)

Run the sandbox once to authenticate with your Anthropic account:

```bash
claude-sandbox run
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
# Normal mode
claude-sandbox run

# YOLO mode (no permission prompts)
claude-sandbox run --yolo

# Firewalled mode (restricted network access)
claude-sandbox run --firewalled

# Chrome enabled (browser control)
claude-sandbox run --with-chrome

# Expose a port for dev server (accessible at localhost:3000 on host)
claude-sandbox run --port 3000

# Multiple ports
claude-sandbox run --port 3000 --port 5173

# Web dev setup: YOLO + Chrome + port exposed
claude-sandbox run --yolo --with-chrome --port 3000

# YOLO + firewalled
claude-sandbox run --yolo --firewalled

# With a prompt
claude-sandbox run --yolo -p "fix the tests"

# Pass any claude arguments
claude-sandbox run --resume
```

**Shorthand:** Running `claude-sandbox` without a command defaults to `run`:

```bash
claude-sandbox --yolo --with-chrome --port 3000
```

### Start Chrome separately

If you want to start Chrome independently (e.g., to keep it running across sandbox sessions):

```bash
# Start Chrome with remote debugging
claude-sandbox start-chrome

# Auto-restart if Chrome is running
claude-sandbox start-chrome --restart

# Override settings from config
claude-sandbox start-chrome --port 9333 --profile "Profile 1"
```

### Manage GPG keys

```bash
# Generate a new key (reads identity from config.sh)
claude-sandbox gpg-new

# Export the sandbox GPG key
claude-sandbox gpg-export --file my-key-backup.asc

# Import a previously exported key
claude-sandbox gpg-import --file my-key-backup.asc

# Generate a revocation certificate
claude-sandbox gpg-revoke --file revoke.asc

# Erase all GPG keys from the sandbox
claude-sandbox gpg-erase
```

### Edit sandbox settings

Open the sandbox's `~/.claude/settings.json` in `vi`:

```bash
claude-sandbox settings
```

This edits the Claude Code configuration stored in the Docker volume (persists across container
restarts).

## How it works

- Your current directory is mounted at `/workspaces/<project-name>` inside the container
- Session history is stored in the project's `.claude/sessions/` directory (consider adding it to
  your `.gitignore`)
- Claude Code settings persist between sessions via a Docker volume
- The container runs as non-root user `claude` for safety
- Full network access is available (for web searches, docs, git, etc.)
- Filesystem access is isolated to the mounted directory
- Host services are accessible via `host.docker.internal`
- Dev server ports can be exposed with `--port <port>` (sets `$EXPOSED_PORTS` env var)
- A global context file (`~/.claude/CLAUDE.md`) informs the agent about the sandbox environment
- With `--with-chrome`, agents can control Chrome on the host for web development

## Persistence

### User data (Docker volume)

User-level data (credentials, settings, plugins) is stored in a Docker volume `claude-sandbox`,
mounted at `/home/claude/persist` inside the container.

```
claude-sandbox → /home/claude/persist/
├── .claude/            # Claude Code configuration (~/.claude)
│   ├── .credentials.json
│   ├── settings.json
│   ├── CLAUDE.md       # Global agent context
│   └── ...
├── .claude.json        # Onboarding state, theme, user ID
├── .claude-versions/   # Claude Code binary versions
│   └── versions/       # Downloaded Claude Code updates
├── .gnupg/             # GPG keys for commit signing (when GPG_SIGNING is enabled)
├── .nvm/               # Node.js versions and global packages
│   ├── versions/node/  # Installed Node.js versions
│   └── ...
```

The entrypoint creates symlinks so tools find their config in the expected locations:

- `~/.claude` → `~/persist/.claude`
- `~/.claude.json` → `~/persist/.claude.json`
- `~/.local/share/claude` → `~/persist/.claude-versions`
- `~/.gnupg` → `~/persist/.gnupg`
- `~/.nvm` → `~/persist/.nvm`

This ensures authentication, settings, Claude Code binary versions, Node.js versions, and global npm
packages persist across container restarts and image rebuilds.

### Session data (per-project)

Session data (conversation history, per-project state) is stored in the project directory at
`.claude/sessions/`. This is bind-mounted into the container so sessions persist and are tied to the
project, not the sandbox.

### Managing the volume

```bash
# Open a shell in the volume
claude-sandbox volume-shell

# Backup the volume
claude-sandbox volume-backup --file claude-sandbox-bkp.tgz

# Restore from backup
claude-sandbox volume-restore --file claude-sandbox-bkp.tgz

# Remove the volume
claude-sandbox volume-rm
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
claude-sandbox --with-chrome
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
claude-sandbox --with-chrome --port 3000
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
1. Start sandbox with port: `claude-sandbox --with-chrome --port 3000`

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
claude-sandbox/
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
