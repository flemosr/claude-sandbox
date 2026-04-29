# Agent Workcell Context

You are running inside an Agent Workcell Docker container. Treat this file as the general sandbox context. Load the focused docs only when the task needs them.

## Focused Context

- For browser-based web development, visual UI checks, dev servers, or the `browser` CLI, read [agent-context-web.md](agent-context-web.md).
- For native/device Flutter work, host Flutter targets, hot reload, screenshots, or the `flutterctl` CLI, read [agent-context-flutter.md](agent-context-flutter.md).
- For Flutter web, use the web development workflow, not the native Flutter bridge.

## Host And Sandbox Boundaries

- Use `host.docker.internal` instead of `localhost` when connecting from the container to services running on the host.
- Your current project directory is bind-mounted from the host. File changes in the workspace persist automatically.
- The container runs as a non-root `agent` user for normal agent commands.
- Filesystem access is scoped to the mounted workspace and persisted user data.
- Interactive project scaffolding prompts usually do not work. Prefer non-interactive CLI flags.

## Persistence

Two kinds of data persist between sessions:

1. **Workspace data:** the mounted project directory, including `.workcell/`.
2. **User data:** Docker volume data under `~/persist/`, symlinked into expected home paths.

Important persisted user paths:

- `~/.nvm/` - Node.js versions and global npm packages.
- `~/.rustup/` and `~/.cargo/` - Rust toolchains, registry cache, installed binaries, and config.
- `~/.gnupg/` - GPG keys for commit signing when enabled.
- `~/.codex/` - Codex config, auth, sessions, history, and global context.
- `~/.claude/` - Claude Code credentials, settings, and global context.
- `~/.config/opencode/` and `~/.local/share/opencode/` - OpenCode config, auth, sessions, logs, and storage.

Installed Node versions, global npm packages, Rust toolchains, and agent upgrades persist across container restarts.

## Ports And Integrations

Check exposed container ports with:

```bash
echo "$EXPOSED_PORTS"
```

If `$EXPOSED_PORTS` is set, dev servers on those ports are reachable from the host at `localhost:<port>`. If a needed port is not exposed, tell the user they can restart the sandbox with `--port <port>`.

`--with-chrome` and `--with-flutter` are mutually exclusive:

- Chrome mode uses `--port` to expose container dev-server ports to host Chrome.
- Flutter mode uses `--port` to select the host Flutter bridge port, not to expose container dev-server ports.

## Network Restrictions

Check firewall status with:

```bash
iptables -L OUTPUT -n 2>/dev/null | grep -q "DROP" && echo "Firewall ACTIVE" || echo "Firewall INACTIVE"
```

When the firewall is active, external network access is limited to essential agent and tooling domains:

- Anthropic: `api.anthropic.com`, `claude.ai`, `statsig.anthropic.com`, `sentry.io`
- OpenAI / Codex: `api.openai.com`, `chatgpt.com`, `auth.openai.com`
- OpenCode: `opencode.ai`
- JavaScript / TypeScript: `registry.npmjs.org`, `npmjs.com`, `yarnpkg.com`, `registry.yarnpkg.com`, `nodejs.org`
- Rust: `crates.io`, `static.crates.io`, `index.crates.io`, `doc.rust-lang.org`, `docs.rs`, `static.rust-lang.org`
- GitHub: `github.com`, `api.github.com`, `raw.githubusercontent.com`, `objects.githubusercontent.com`
- Other: `storage.googleapis.com`

## Available Tools

| Category | Tools |
|----------|-------|
| Languages | Node.js LTS through `nvm`, Python 3.11, Rust stable |
| Node.js | `nvm`, `npm`, `npx` |
| Python | `pyright`, `ruff`, `playwright`, `matplotlib`, `numpy` |
| Browser | `browser` CLI for Chrome automation; read [agent-context-web.md](agent-context-web.md) before use |
| Flutter | `flutterctl` CLI for the host Flutter bridge; read [agent-context-flutter.md](agent-context-flutter.md) before use |
| Database | `psql`; connect to host databases through `host.docker.internal` |
| Utilities | `git`, `curl`, `wget`, `jq`, `yq`, `ripgrep`, `fd` |

## Task Management

Use `.workcell/tasks/` as a shared scratchpad for multi-step work, handoffs, research, or multi-agent coordination. Skip task files for trivial one-step requests.

Before starting non-trivial work:

1. List `.workcell/tasks/`.
2. Read any task file whose title or objective relates to the current request.
3. Continue an existing task file when it already covers the request.
4. Create a new task file only when no existing one applies.

Task files use UTC timestamp prefixes:

```text
YYYYMMDD-HHMMSS-brief-descriptive-slug.md
```

Each task file should include:

```markdown
# <Short Title>

- **Status:** pending | in_progress | blocked | completed | cancelled
- **Created:** <YYYY-MM-DD HH:MM UTC>
- **Updated:** <YYYY-MM-DD HH:MM UTC>

## Objective
## Context
## Plan
## Findings
## Next Steps
## Dependencies
## Notes
```

While working, append timestamped findings instead of rewriting history. Check off plan items as they complete. When pausing, leave concrete `Next Steps`. When finished, set `Status` to `completed`, clear `Next Steps`, update `Updated`, and summarize the outcome in `Findings`.
