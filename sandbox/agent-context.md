# Sandboxed Environment

You are running inside a Docker container sandbox. Keep the following in mind:

## Host Services

Use `host.docker.internal` instead of `localhost` to connect to services running on the host machine.

## Persistence

Two types of data persist between sessions:

1. **Workspace** (bind mount): Your project directory is mounted from the host. All file changes persist automatically.

2. **User data** (Docker volume): Stored in `~/persist/` and symlinked to expected locations:
   - `~/.claude/` - Claude Code config, credentials, settings
   - `~/.claude.json` - Onboarding state
   - `~/.local/share/claude/` - Claude Code binary versions (stored as `~/persist/.claude-versions`)
   - `~/.nvm/` - Node.js versions and global npm packages
   - `~/.rustup/` - Rust toolchains and components
   - `~/.cargo/` - Cargo registry cache, installed binaries, and config
   - `~/.gnupg/` - GPG keys for commit signing (when GPG_SIGNING is enabled)

This means installed Node versions (`nvm install 20`), global packages (`npm i -g typescript`), Rust toolchains, and Claude Code updates persist across container restarts.

## Exposed Ports

To check which ports are exposed to the host:

```bash
echo "$EXPOSED_PORTS"  # e.g., "3000,5173"
```

If `$EXPOSED_PORTS` is set, dev servers on those ports are accessible from the host at `localhost:<port>`.

If you need a port that isn't exposed, inform the user they can restart the sandbox with `--port <port>`.

## Chrome Browser Integration

Chrome runs on the **host machine** and you can control it remotely via the Chrome DevTools Protocol (CDP). This lets you navigate pages, take screenshots, click elements, and inspect console logs.

**IMPORTANT:** Since Chrome runs on the host, it can only reach dev servers in the container via exposed ports. If `$EXPOSED_PORTS` is empty, Chrome **cannot** reach any container services - do not attempt `localhost`, `host.docker.internal`, or container IPs. Ask the user to restart with `--port <port>`.

To check if Chrome browser control is available, use `browser test`. Note that Chrome can be closed at any time by the user, so always verify connectivity before use:

```bash
browser test  # Returns success if Chrome is connected and available
```

If Chrome is not available, inform the user they can either:
1. Run `./start-chrome-debug.sh` on the host machine (no restart needed)
2. Restart the sandbox with `--with-chrome`

### Browser CLI Commands

```bash
browser test                    # Test connection to Chrome
browser goto <url>              # Navigate to URL
browser screenshot [-o path]    # Take screenshot (PNG)
browser click <selector>        # Click element by CSS selector
browser fill <selector> <text>  # Fill form field
browser console                 # Get console logs (errors, warnings, etc.)
browser info                    # Get current page URL and title
browser wait <selector>         # Wait for element to appear (--timeout <ms>)
browser eval <js>               # Execute JavaScript (--json for JSON output)
browser scroll [target]         # Scroll: pixels, selector, or 'bottom' (--by for relative)
```

### Python API

```python
from browser import Browser

async with Browser() as b:
    await b.goto("http://localhost:3000")  # Chrome is on host, use localhost
    await b.screenshot("preview.png")
    logs = await b.get_console_logs()
```

### Web Development Workflow

When building web apps, use Chrome to visually verify your work:

1. **First, verify the port is exposed** (if empty, Chrome cannot reach your dev server):
   ```bash
   echo "$EXPOSED_PORTS"  # Must include your dev server port (e.g., "3000")
   ```

2. **Start your dev server** - it **must** bind to `0.0.0.0` (not `localhost` or `127.0.0.1`):
   ```bash
   # Vite
   npm run dev -- --host 0.0.0.0 --port 3000

   # Next.js
   npm run dev -- -H 0.0.0.0 -p 3000

   # Create React App
   HOST=0.0.0.0 PORT=3000 npm start
   ```

   Without `--host 0.0.0.0`, the server only listens on localhost inside the container and Chrome (on the host) cannot connect.

3. **Navigate Chrome to your app** (Chrome is on the host, so use `localhost`):
   ```bash
   browser goto "http://localhost:3000"
   ```

4. **Take screenshots** to verify UI changes:
   ```bash
   browser screenshot -o "preview.png"
   ```

5. **Check for errors** in the browser console:
   ```bash
   browser console
   ```

6. **Interact with the page** to test functionality:
   ```bash
   browser click "button.submit"
   browser fill "input[name=email]" "test@example.com"
   ```

### Troubleshooting

Check Chrome debug logs if you have connection issues:

```bash
cat "$CHROME_LOG"
```

## Firewall Status

To check if network restrictions are active:

```bash
iptables -L OUTPUT -n 2>/dev/null | grep -q "DROP" && echo "Firewall ACTIVE" || echo "Firewall INACTIVE"
```

## Allowed Domains (when firewalled)

If the firewall is active, only the following domains are accessible:

**Anthropic**
- api.anthropic.com
- claude.ai
- statsig.anthropic.com
- sentry.io

**JavaScript/TypeScript**
- registry.npmjs.org
- npmjs.com
- yarnpkg.com
- registry.yarnpkg.com
- nodejs.org

**Rust**
- crates.io
- static.crates.io
- index.crates.io
- doc.rust-lang.org
- docs.rs
- static.rust-lang.org

**GitHub**
- github.com
- api.github.com
- raw.githubusercontent.com
- objects.githubusercontent.com

**Other**
- storage.googleapis.com

All other external network access is blocked when firewalled.

## Available Tools

The following tools are pre-installed:

| Category | Tools |
|----------|-------|
| **Languages** | Node.js LTS (via nvm), Python 3.11, Rust (stable) |
| **Node.js** | `nvm` (version manager), `npm`, `npx` - versions and global packages persist |
| **Python** | `pyright` (type checker), `ruff` (linter), `playwright`, `matplotlib`, `numpy` |
| **Browser** | `browser` CLI for Chrome automation (use `browser test` to check availability) |
| **Utilities** | `git`, `curl`, `wget`, `jq`, `yq`, `ripgrep`, `fd` |

## Project Scaffolding

Interactive CLI prompts (like `npm create vite@latest`) don't work in this environment. Use non-interactive flags instead:

```bash
# Vite (React + TypeScript)
npm create vite@latest my-app -- --template react-ts

# Vite (Vue)
npm create vite@latest my-app -- --template vue-ts

# Vite (Svelte)
npm create vite@latest my-app -- --template svelte-ts

# Next.js
npx create-next-app@latest my-app --typescript --eslint --app --src-dir --no-tailwind --import-alias "@/*"

# Create React App
npx create-react-app my-app --template typescript

# Express (manual setup - no scaffolding tool)
mkdir my-app && cd my-app && npm init -y && npm install express
```

The `--` before template flags is required for npm create commands to pass arguments to the scaffolding tool.
