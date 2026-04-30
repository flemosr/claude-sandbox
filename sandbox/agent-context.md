# Agent Workcell Context

You are running inside an Agent Workcell Docker container. Treat this file as the general sandbox context. Load the focused docs only when the task needs them.

## Focused Context

- For browser-based web development, visual UI checks, dev servers, or the `browser` CLI, read the sibling file `agent-context-web.md` next to this main context file.
- For native/device Flutter work, host Flutter targets, hot reload, screenshots, or the `flutterctl` CLI, read the sibling file `agent-context-flutter.md` next to this main context file.
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

Project-specific workcell data lives under `.workcell/`:

- `.workcell/artifacts/` - temporary artifacts from agent work, such as screenshots, logs, traces, and generated previews. Put throwaway files here instead of the repo root.
- `.workcell/tasks/` - shared task notes for multi-step work and handoffs.
- `.workcell/flutter-config.json` - Flutter bridge launch settings and runtime connection details when Flutter integration is used.

Prefer timestamped artifact names so files sort chronologically and avoid collisions. For example:

```text
.workcell/artifacts/20260429-132400-home-page.png
.workcell/artifacts/20260429-132405-test-output.txt
```

Important persisted user paths:

- `~/.nvm/` - Node.js versions and global npm packages.
- `~/.rustup/` and `~/.cargo/` - Rust toolchains, registry cache, installed binaries, and config.
- `~/.gnupg/` - GPG keys for commit signing when enabled.
- `~/persist/.flutter-sdk/` - Flutter SDK (`flutter` and `dart` on PATH, seeded from image on first run).
- `~/.pub-cache/` - Dart pub package cache shared across projects.
- `~/.flutter/` - Flutter CLI config and version state.
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
| Browser | `browser` CLI for Chrome automation; read sibling `agent-context-web.md` before use |
| Flutter | `flutter` and `dart` for tests, analysis, formatting, and pub; `flutterctl` for the host bridge (launch, hot-reload, screenshots); read sibling `agent-context-flutter.md` before use |
| Database | `psql`; connect to host databases through `host.docker.internal` |
| Utilities | `git`, `curl`, `wget`, `jq`, `yq`, `ripgrep`, `fd` |

## Task Management

Use `.workcell/tasks/` for work that benefits from continuity: multi-step changes, handoffs, research, parallel-agent coordination, risky debugging, or anything likely to span sessions. Skip task files for trivial one-step requests.

Before starting non-trivial work:

1. List `.workcell/tasks/`.
2. Skim task filenames and title lines only. Do not read full task files yet.
3. Ask the user how to track the work: continue a previous task (including likely matches by title when any exist), create a new task, or skip task file creation.
4. Read only the task file the user chooses.
5. Create a new task file only when the user asks for a new one.

Task filenames use UTC timestamp prefixes:

```text
YYYYMMDD-HHMMSS-brief-descriptive-slug.md
```

Inside task files, use local time for logs and metadata. Write the timezone as a compact GMT offset, such as `GMT-3`, to keep entries short.

Each task file should include:

```markdown
# <Short Title>

- **Status:** pending | in_progress | blocked | completed | cancelled
- **Created:** <YYYY-MM-DD HH:MM GMT-offset>
- **Updated:** <YYYY-MM-DD HH:MM GMT-offset>

## Objective
## Context
## Plan
## Next Steps
## Log

- `<YYYY-MM-DD HH:MM GMT-offset>` | `<author>` | <entry>
  - **CORRECTION** | `<YYYY-MM-DD HH:MM GMT-offset>` | `<author>` | <correction>

## Dependencies
## Notes
```

Keep task files concise and operational. Record decisions, blockers, ownership boundaries, important commands, verification results, and links to artifacts. Put large logs, screenshots, traces, and generated previews in `.workcell/artifacts/` instead of pasting them into the task file.

Keep `Plan` current with succinct notes about what was done and what remains. Add `Log` entries in descending time order, and include the authoring harness/model, such as `codex/gpt-5.5`, when known. If the harness/model is unknown, ask the user; do not infer it from previous log entries. Preserve previous log content. When a correction is needed, add an indented `CORRECTION` entry below the original entry or its previous corrections. Update status, plan checkboxes, and next steps as the task changes. When pausing, leave concrete `Next Steps`. When finished, set `Status` to `completed`, clear `Next Steps`, update `Updated`, and summarize the outcome in `Log`.
