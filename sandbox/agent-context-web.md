# Web Development Agent Context

Use this document when a task involves browser-based web development, visual UI verification, container dev servers, or the `browser` CLI.

## Browser Model

Chrome runs on the host machine. The container controls it through the Chrome DevTools Protocol using the `browser` CLI.

Because Chrome is on the host, it can reach container dev servers only through exposed ports. If `$EXPOSED_PORTS` is empty, Chrome cannot reach container services. Do not try `localhost`, `host.docker.internal`, or container IPs from Chrome in that case; tell the user they can restart the sandbox with `--port <port>`.

Host services from inside the container still use `host.docker.internal`; that is separate from host Chrome reaching a container dev server.

## Project Scaffolding

Interactive scaffolding prompts usually do not work in this environment. Use non-interactive flags:

```bash
# Vite
npm create vite@latest my-app -- --template react-ts
npm create vite@latest my-app -- --template vue-ts
npm create vite@latest my-app -- --template svelte-ts

# Next.js
npx create-next-app@latest my-app --typescript --eslint --app --src-dir --no-tailwind --import-alias "@/*"

# Create React App
npx create-react-app my-app --template typescript
```

The `--` before Vite template flags is required so npm passes the arguments to the scaffolding tool.

## Availability Checks

Check exposed ports before starting a dev server:

```bash
echo "$EXPOSED_PORTS"
```

Check Chrome control before using browser automation:

```bash
browser test
```

Chrome can be closed by the user at any time, so verify connectivity before relying on it. If Chrome is unavailable, tell the user they can either run `./start-chrome-debug.sh` on the host or restart the sandbox with `--with-chrome`.

## Dev Server Rules

Start dev servers on an exposed port and bind to `0.0.0.0`, not `localhost` or `127.0.0.1`:

```bash
# Vite
npm run dev -- --host 0.0.0.0 --port 3000

# Next.js
npm run dev -- -H 0.0.0.0 -p 3000

# Create React App
HOST=0.0.0.0 PORT=3000 npm start
```

Navigate Chrome using host-style URLs:

```bash
browser goto "http://localhost:3000"
```

If the requested port is not exposed, use an exposed port when possible. If no suitable port is exposed, tell the user to restart with `--port <port>`.

## Browser CLI

```bash
browser test                    # Test connection to Chrome
browser goto <url>              # Navigate to URL
browser screenshot [-o path]    # Take screenshot
browser click <selector>        # Click by CSS selector
browser fill <selector> <text>  # Fill form field
browser console                 # Read browser console logs
browser info                    # Current page URL and title
browser wait <selector>         # Wait for element
browser eval <js>               # Execute JavaScript; use --json for JSON output
browser scroll [target]         # Scroll pixels, selector, or bottom; use --by for relative
```

Python API:

```python
from browser import Browser

async with Browser() as b:
    await b.goto("http://localhost:3000")
    await b.screenshot("preview.png")
    logs = await b.get_console_logs()
```

## Verification Workflow

For frontend work, visually verify the result when Chrome is available:

1. Confirm the dev-server port is exposed.
2. Start the server on `0.0.0.0`.
3. Navigate Chrome to `http://localhost:<port>`.
4. Check the console for errors.
5. Take screenshots for visual layout checks.
6. Interact with the page for key workflows.

Use screenshots for layout, responsive behavior, canvas rendering, and asset checks. Use `browser console` for runtime errors and warnings after page load and after interactions.

## Troubleshooting

Check Chrome debug logs when browser control fails:

```bash
cat "$CHROME_LOG"
```

Common failures:

- Chrome control unavailable: host Chrome is not running with debugging enabled, or the sandbox was not started with Chrome support.
- Page cannot load: the dev server is not bound to `0.0.0.0`, the port is not exposed, or Chrome was pointed at the wrong host URL.
- Server works in the container but not in Chrome: re-check `$EXPOSED_PORTS` and ensure Chrome uses `localhost:<port>`.
