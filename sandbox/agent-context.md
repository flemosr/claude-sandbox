# Sandboxed Environment

You are running inside a Docker container sandbox. Keep the following in mind:

## Host Services

Use `host.docker.internal` instead of `localhost` to connect to services running on the host machine.

## Persistence

Two types of data persist between sessions:

1. **Workspace** (bind mount): Your project directory is mounted from the host. All file changes persist automatically.

2. **User data** (Docker volume): Stored in `~/persist/` and symlinked to expected locations. Your agent's config, credentials, and install directory persist here, along with:
   - `~/.nvm/` - Node.js versions and global npm packages
   - `~/.rustup/` - Rust toolchains and components
   - `~/.cargo/` - Cargo registry cache, installed binaries, and config
   - `~/.gnupg/` - GPG keys for commit signing (when GPG_SIGNING is enabled)
   - `~/.codex/` - Codex config, auth, sessions, and history (when using Codex)

This means installed Node versions (`nvm install 20`), global packages (`npm i -g typescript`), Rust toolchains, and agent upgrades persist across container restarts.

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

## Flutter Bridge Integration

A Flutter app can run on the **host machine** (iOS Simulator, Android Emulator, macOS desktop, or physical device) and you can control it via the Flutter host bridge. This lets you launch apps, hot reload, take screenshots, and view logs without running Flutter toolchains inside the container.

**IMPORTANT:** Flutter native toolchains (iOS Simulator, Android Emulator, Xcode, Android Studio) live on the host. The bridge lets you interact with them from inside the container, but you cannot run simulators or emulators inside Docker.

To check if Flutter bridge control is available, use `flutterctl test`. Note that the bridge may not be running, so always verify connectivity before use:

```bash
flutterctl test  # Returns success if bridge is reachable
```

If the bridge is not available, inform the user they can either:
1. Run `workcell start-flutter-bridge` on the host machine from their Flutter project directory (no restart needed)
2. Restart the sandbox with `--with-flutter`

`--with-flutter` and `--with-chrome` are mutually exclusive. For Flutter web,
use the Chrome workflow. For native/device Flutter targets, use the Flutter bridge.
When the sandbox is started with `--with-flutter`, `--port <port>` selects the host
Flutter bridge port and does not expose a container dev-server port.

The bridge requires a bearer token for all requests (except health checks). The token
is auto-generated when the bridge starts. Connection details (token, port)
are written to `.workcell/flutter-config.json` in the workspace root, so agents can
read them directly without the user needing to copy anything:

```bash
cat .workcell/flutter-config.json
```

The same file may contain project-local Flutter launch settings such as `target`
and `run_args`; the bridge preserves those fields when it updates runtime
connection details.

Example project-local launch settings:

```json
{
  "target": "lib/main_dev.dart",
  "run_args": ["--flavor", "staging", "--dart-define", "API_BASE_URL=https://api.example.test"]
}
```

The host-side Flutter project path is intentionally not passed into the sandbox.
Use the current workspace path inside the container for file edits; the bridge maps
commands to the host project path internally.

The intended model is one bridge per sandbox/agent. Concurrent agents should use separate
bridge instances on distinct ports rather than sharing one bridge.

### Flutterctl CLI Commands

```bash
flutterctl test                    # Test connection to Flutter bridge
flutterctl status                  # Get bridge status (idle, running, attached, error)
# idle = no app process managed by bridge
# running = app launched via bridge
# attached = bridge connected to externally-running app
# error = subprocess failed
flutterctl devices                 # List available Flutter devices
flutterctl launch [-d <device>]    # Launch Flutter app on a device
flutterctl attach [-d <device>]    # Attach to a running Flutter app
flutterctl detach                  # Stop the app process managed by the bridge
flutterctl hot-reload              # Hot reload
flutterctl hot-restart             # Hot restart
flutterctl logs                    # Get recent Flutter logs
flutterctl screenshot -o <path>    # Take screenshot (PNG; macOS captures app window only)
flutterctl tap --x 150 --y 300     # UI automation tap, if status says supported
flutterctl tap --text "Sign in"    # Selector tap, if status says supported
flutterctl tap --key loginButton   # Widget-key selector tap, if supported
flutterctl type "hello"            # Type into current focus, if supported
flutterctl press enter             # Press a named key, if supported
flutterctl scroll --dy 600         # Scroll by delta, if supported
flutterctl inspect [--text <text>] # Inspect UI state, if supported
flutterctl inspect --key loginButton # Inspect a widget-key selector, if supported
flutterctl wait --text "Ready"     # Wait for UI state, if supported
flutterctl wait --key loginButton  # Wait for a widget-key selector, if supported
```

`flutterctl status` includes a `ui_automation` object with backend, target,
readiness, missing host tools, coordinate-space metadata, and per-action
capabilities. Treat that object as authoritative before running UI automation
commands. If an action is unsupported, not ready, or no app is running, the
bridge returns structured JSON errors such as `UNSUPPORTED_TARGET`,
`UI_NOT_READY`, or `NO_APP_RUNNING`.
On macOS desktop, coordinate taps use `app-window-points`: `x=0,y=0` is the
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

Current UI automation target scope is intentionally narrow: iOS Simulator and
macOS desktop only. Android, Linux desktop, Windows desktop, physical iOS, and
Flutter web should be treated as unsupported by the Flutter bridge UI action
API. Flutter web remains covered by the Chrome/CDP workflow. Coordinate taps and
selectors must not be assumed available unless `status.ui_automation.actions`
marks them as supported.

### Flutter Development Workflow

When building Flutter apps, use the bridge to verify your work:

1. **First, verify the bridge is running:**
   ```bash
   flutterctl test
   ```

2. **Check available devices:**
   ```bash
   flutterctl devices
   ```

3. **Launch your Flutter app.** Pick from the device list (step 2):
    ```bash
    flutterctl launch --device ios
    # or: flutterctl launch --device macos
    # or: flutterctl launch --device emulator-5554
    ```

4. **Or attach to an already-running app:**
   ```bash
   flutterctl attach --device ios
   ```

5. **Check bridge status** (includes VM service URL when running):
   ```bash
   flutterctl status
   ```

6. **If UI automation is needed, inspect `ui_automation` from status before acting:**
   ```bash
   flutterctl status
   flutterctl tap --x 150 --y 300
   flutterctl press enter
   ```

7. **Edit Dart files** in the container, then trigger hot reload:
   ```bash
   flutterctl hot-reload
   ```

8. **Take screenshots** to verify UI changes:
    ```bash
    flutterctl screenshot -o before.png
    # ... edit code ...
    flutterctl hot-reload
    flutterctl screenshot -o after.png
    ```
   On macOS desktop, screenshots are app-window-only. If the bridge cannot
   identify the Flutter window or host privacy permissions block capture, the
   command fails rather than capturing the full screen.

9. **View app logs** if you need to debug:
   ```bash
   flutterctl logs
   ```

### Troubleshooting

Check the Flutter bridge log if you have connection issues:

```bash
cat "$FLUTTER_BRIDGE_LOG_FILE"  # or: cat /tmp/flutter-bridge.log
```

Check if the bridge env vars are set (env vars override the config file):

```bash
echo "URL: $FLUTTER_BRIDGE_URL"
```

If `flutterctl test` succeeds but `flutterctl launch` fails, check the bridge log for Flutter build errors on the host side.

### Flutter Web vs Native

For **Flutter web**, prefer the existing Chrome/CDP workflow (`--with-chrome`). Build and serve Flutter web from inside the container and use `browser` commands to interact with it.

Use the Flutter bridge (`--with-flutter`) for **native targets** only: iOS Simulator, Android Emulator, macOS desktop, Linux desktop, Windows desktop, and physical devices.

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

**OpenAI / Codex**
- api.openai.com
- chatgpt.com
- auth.openai.com

**OpenCode**
- opencode.ai

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
| **Flutter** | `flutterctl` CLI for Flutter bridge control (use `flutterctl test` to check availability) |
| **Database** | `psql` (PostgreSQL client) - connect to host DBs via `host.docker.internal` |
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

## Task Management (Multi-Agent Workflows)

The `.workcell/tasks/` directory is a shared scratchpad for coordinating work across multiple agent sessions — sub-agents within a single run, or different agents across different sessions. Use it to record plans, findings, and handoff notes so any agent can pick up where another left off without re-reading the whole conversation.

### When to Use Task Files

Create a task file when:
- The user's request spans multiple steps or is likely to continue in a later session.
- You need to hand off work to another agent (sub-agent or future session).
- You are researching or exploring and want to persist context beyond the current conversation.

For trivial one-step requests, skip the task file.

### Naming Convention

Use a UTC timestamp prefix to guarantee chronological ordering and uniqueness across agents:

```
YYYYMMDD-HHMMSS-brief-descriptive-slug.md
```

Example: `20260423-143052-add-user-auth.md`

One task per file. If a task spawns sub-tasks, create new files and link them via `Dependencies` rather than nesting plans inside a single file.

### File Structure

Each task file should contain these sections:

```markdown
# <Short Title>

- **Status:** pending | in_progress | blocked | completed | cancelled
- **Created:** <YYYY-MM-DD HH:MM UTC>
- **Updated:** <YYYY-MM-DD HH:MM UTC>

## Objective

What this task aims to accomplish, and why. Specific enough that a fresh agent can act on it without re-reading the conversation.

## Context

Background a new agent needs to be effective: prior discoveries, constraints, user preferences stated in the original conversation, relevant files, commits, or PRs. Carry forward anything that would otherwise be lost when the conversation ends.

## Plan

- [ ] Step one
- [ ] Step two
- [ ] Step three

## Findings

Append-only log of discoveries, decisions, and issues. Prefix each entry with a UTC timestamp.

Example:
- `2026-04-23 14:35 UTC` — The login flow actually hits `/api/v2/auth`, not `/api/auth` as the README suggests.

Do not delete or rewrite previous findings. If a prior finding was wrong, add a new entry that references it and explains the correction.

## Next Steps

When pausing without completing the task, leave a short note here describing exactly what the next agent should pick up first. Clear this section once the task is `completed`.

## Dependencies

- Links to other task files or external blockers.

## Notes

Free-form scratch area for any agent.
```

### Workflow Rules

1. **Before starting non-trivial work**, list `.workcell/tasks/` and read any task file whose title or objective relates to the current request. Skipping this is the main way multi-agent coordination breaks down.
2. **Continue, don't duplicate.** If an existing task file already covers the request, continue in that file rather than creating a parallel one.
3. **When you begin**, set `Status` to `in_progress` and update the `Updated` timestamp (UTC).
4. **While working**, append findings with a UTC timestamp and check off plan items as you complete them. Record decisions and their reasoning, not just outcomes.
5. **Never rewrite history.** Previous findings stay. Correct mistakes by adding a new entry that references and overrides the earlier one.
6. **When pausing**, fill in `Next Steps` so the next agent has a clear starting point, and update `Updated`.
7. **When finishing**, set `Status` to `completed` (or `blocked` if stuck), clear `Next Steps`, update `Updated`, and summarize the outcome in `Findings`.
8. **Sub-tasks** go in their own task files, linked via `Dependencies`. Do not nest plans within a single file.
9. **If `.workcell/tasks/` does not exist**, create it before writing the first task file.
