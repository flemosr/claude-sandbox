# Claude Code Sandbox

A Docker-based sandbox environment for running Claude Code safely in YOLO mode.

## Prerequisites

- Docker installed and running
- macOS (or Linux/WSL2)
- `socat` for Chrome integration: `brew install socat`

## Setup

### 1. Build the sandbox image

```bash
docker compose build
```

### 2. Configure Chrome settings

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

Edit `config.sh` with your new profile's folder name:

```bash
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_USER_DATA="$HOME/Library/Application Support/Google/Chrome"
CHROME_DEBUG_DATA="$HOME/Library/Application Support/Google/Chrome-Debug"
CHROME_PROFILE="Profile 3"      # <-- Use folder name from chrome://version
CHROME_DEBUG_PORT=9222
CHROME_INTERNAL_PORT=19222
```

Your `config.sh` is gitignored, so your personal settings won't be committed.

### 3. Add the shell alias

Add this to your `~/.zshrc`:

```bash
alias claude-sandbox="/path/to/claude-sandbox/run_sandbox.sh"
```

Replace `/path/to/claude-sandbox` with the actual path to this repository.

Then reload your shell:

```bash
source ~/.zshrc
```

### 4. Authenticate (first time only)

Run the sandbox once to authenticate with your Anthropic account:

```bash
claude-sandbox
```

## Usage

Navigate to any project directory and run:

```bash
# Normal mode
claude-sandbox

# YOLO mode (no permission prompts)
claude-sandbox --yolo

# Firewalled mode (restricted network access)
claude-sandbox --firewalled

# Chrome enabled (browser control)
claude-sandbox --with-chrome

# Expose a port for dev server (accessible at localhost:3000 on host)
claude-sandbox --port 3000

# Multiple ports
claude-sandbox --port 3000 --port 5173

# Web dev setup: YOLO + Chrome + port exposed
claude-sandbox --yolo --with-chrome --port 3000

# YOLO + firewalled
claude-sandbox --yolo --firewalled

# With a prompt
claude-sandbox --yolo -p "fix the tests"

# Pass any claude arguments
claude-sandbox --resume
```

## How it works

- Your current directory is mounted at `/workspaces/<project-name>` inside the container
- Session history is stored in the project's `.claude/sessions/` directory
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
```

The Dockerfile creates symlinks so Claude Code finds its config in the expected locations:

- `~/.claude` → `~/persist/.claude`
- `~/.claude.json` → `~/persist/.claude.json`

This ensures authentication, settings, and onboarding state persist across container restarts and
image rebuilds.

### Session data (per-project)

Session data (conversation history, per-project state) is stored in the project directory at
`.claude/sessions/`. This is bind-mounted into the container so sessions persist and are tied to the
project, not the sandbox.

### Managing the volume

```bash
# Access volume's contents
docker run --rm -it -v claude-sandbox:/data -w /data alpine sh

# Backup the volume
docker run --rm -v claude-sandbox:/data -v $(pwd):/backup alpine tar -czf /backup/claude-sandbox-bkp.tgz -C /data .

# Restore from backup
docker run --rm -v claude-sandbox:/data -v $(pwd):/backup alpine tar -xzf /backup/claude-sandbox-bkp.tgz -C /data

# Remove the volume
docker volume rm claude-sandbox
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

Chrome on Mac ignores `--remote-debugging-address=0.0.0.0` and only binds to `127.0.0.1`. Since Docker
containers can't reach the host's localhost directly, we use `socat` as a bridge:

```
┌─────────────────────────────────────────────────────────────────────┐
│  HOST (Mac)                                                         │
│                                                                     │
│   Chrome ◄──────── socat ◄──────── Docker Network                  │
│   127.0.0.1:19222   0.0.0.0:9222    host.docker.internal:9222      │
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
│   React/Vite/etc ◄─── 0.0.0.0:3000                                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

The `$EXPOSED_PORTS` env var contains the list of exposed ports (e.g., `3000,5173`).

**Complete flow for web development:**
1. Start sandbox with port: `claude-sandbox --with-chrome --port 3000`
2. Start dev server in container: `npm run dev` (runs on port 3000)
3. Access from host browser: `http://localhost:3000`
4. Or use `browser` CLI: `browser goto "http://host.docker.internal:3000"`

### Manual Setup (alternative)

If you prefer to manage Chrome separately:

1. **Start Chrome with remote debugging:**

   ```bash
   ./start-chrome-debug.sh
   ```

   **Important:** Chrome must not be running. The script will detect if Chrome is already open and
   show an error with instructions to quit it. You can use `--restart` to automatically kill and
   restart Chrome:

   ```bash
   ./start-chrome-debug.sh --restart    # Auto-kill running Chrome and restart with debugging
   ./start-chrome-debug.sh --port 9333  # Override port from config
   ./start-chrome-debug.sh --profile "Profile 1"  # Override profile from config
   ```

2. **In the sandbox, test the connection:**

   ```bash
   browser test
   ```

### Available Commands

```bash
browser test                    # Test connection to Chrome
browser goto <url>              # Navigate to URL
browser screenshot [-o path]    # Take screenshot
browser click <selector>        # Click an element
browser fill <selector> <text>  # Fill a form field
browser console                 # Get console logs
browser info                    # Get current page info
```

### Programmatic Usage (Python)

```python
from browser import Browser

async with Browser() as b:
    await b.goto("http://host.docker.internal:3000")
    await b.screenshot("my-app.png")
    logs = await b.get_console_logs()
```

### Web Development Workflow

1. Start your dev server in the sandbox (e.g., `npm run dev` on port 3000)
2. From within the sandbox, use `browser goto "http://host.docker.internal:3000"` to navigate Chrome
3. Use `browser screenshot`, `browser click`, etc. to interact and verify
4. You can also view the app directly in Chrome on your Mac at `http://localhost:3000`

## Available Tools

The sandbox comes with the following pre-installed:

| Category | Tools |
|----------|-------|
| **Languages** | Python 3.11, Rust (stable) |
| **Python** | `pyright` (type checker), `ruff` (linter), `playwright` |
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
├── config.template.sh          # Configuration template
├── config.sh                   # Your config (create from template, gitignored)
├── run_sandbox.sh              # Main entry point script
├── start-chrome-debug.sh       # Start Chrome with remote debugging (run on host)
└── sandbox/
    ├── agent-context.md        # Global context for the sandboxed agent
    ├── Dockerfile
    ├── entrypoint.sh
    ├── init-firewall.sh
    └── browser-tools/          # Browser control utilities
        ├── browser             # CLI wrapper
        └── browser.py          # Python module
```
