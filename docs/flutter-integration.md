# Flutter Integration

The workcell supports Flutter development in two ways:

- **In-container Flutter SDK** — `flutter test`, `flutter analyze`, `dart format`, and `flutter pub`
  run directly inside the container with no host setup required.
- **Host Flutter bridge** — for native/device work, a bridge runs host-side `flutter` commands
  against simulators, emulators, desktop apps, or devices while agents edit code in the container.

For Flutter web, use [Chrome integration](chrome-integration.md) instead.

## In-Container Flutter SDK

A Flutter SDK is bundled with the container image. Agents can run tests, static analysis,
formatting, and package management against any workspace project with no host setup required.
The rest of this document covers the host bridge for native/device targets.

## Prerequisites

- Flutter SDK installed on the host machine.
- At least one configured Flutter target, such as iOS Simulator, Android Emulator, macOS desktop,
  or a physical device.
- macOS host for the primary supported path. Linux Android Emulator support can follow.
- For macOS desktop UI automation and screenshots, allow the host terminal or agent process in
  macOS Accessibility and Screen Recording privacy settings when prompted.

## Setup

Create your local config file if it does not exist:

```bash
cp config.template.sh config.sh
```

The default Flutter bridge settings are:

```bash
FLUTTER_DEFAULT_BRIDGE_PORT=8765
FLUTTER_BRIDGE_LOG_FILE="/tmp/flutter-bridge.log"
```

If `flutter` is not on the host `PATH`, set `FLUTTER_PATH` in `config.sh`:

```bash
FLUTTER_PATH="/usr/local/bin/flutter"
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

The bridge updates the same file with runtime `token` and `port` values when it starts. When
`--with-flutter` starts a bridge, the port is selected from:

1. `--port`, if supplied.
2. `.workcell/flutter-config.json`.
3. `FLUTTER_DEFAULT_BRIDGE_PORT`.
4. `8765`.

## Usage

Run from the host Flutter project directory:

```bash
workcell --with-flutter
```

This automatically:

1. Starts a Flutter host bridge HTTP server on the selected port.
2. Generates a per-session bearer token.
3. Makes the bridge available to the sandboxed agent.
4. Mounts the bridge log file for troubleshooting.
5. Cleans up the bridge started by the workcell when the session exits.

Use `--port` to select the bridge port for one run:

```bash
workcell --with-flutter --port 8765
workcell run opencode --yolo --with-flutter --port 8766
```

`--with-flutter` and `--with-chrome` cannot be used together. Use `--with-chrome` for Flutter web
and `--with-flutter` for native/device targets. In Flutter mode, `--port` is the host bridge port;
it does not expose a container dev-server port.

## Start the Bridge Separately

Start the bridge independently if you want it to keep running across workcell sessions:

```bash
# Start using defaults and project-local settings
workcell start-flutter-bridge

# Override bridge settings
workcell start-flutter-bridge --port 8766 --project ~/my-flutter-app
```

Then run the workcell without `--with-flutter`. The launcher writes connection details to
`.workcell/flutter-config.json`, and future workcell sessions can reuse those connection details.
The bridge starts without a selected device; the agent can choose one during the session.

## UI Automation

The bridge can support UI automation on selected targets. macOS desktop automation uses host
Accessibility and Screen Recording permissions, so the first run may trigger privacy prompts.

Prefer widget-key selectors for agent-driven Flutter UI interactions when the app can provide them.
Stable, descriptive `ValueKey<String>` values on controls and important containers give agents a
reliable target independent of visible copy, localization, and layout changes. Useful examples:
`login_button`, `email_field`, `settings_tab`, `todo_list`, and `delete_item_0`.

UI automation is currently scoped to iOS Simulator and macOS desktop backends. Android, Linux
desktop, Windows desktop, physical iOS, and Flutter web are not supported by the Flutter bridge UI
action API.

## Screenshots

The bridge supports screenshots for native/device targets when a Flutter app is running under the
bridge. On macOS desktop, screenshots capture only the Flutter app window. If the app window cannot
be found or macOS Screen Recording permission blocks capture, the request fails instead of falling
back to a full-screen screenshot.

## How It Works

```text
HOST

Flutter Bridge HTTP API, usually 0.0.0.0:8765 with bearer-token auth
  - flutter run / flutter attach subprocess management
  - screenshots (`flutter screenshot` for mobile targets; app-window capture for macOS desktop)
  - flutter devices
  - hot reload / hot restart
  - UI automation capability/status and action API

iOS Simulator / Android Emulator / macOS desktop / device

CONTAINER

Sandboxed agent -> Flutter bridge
```

The host owns Flutter SDK execution for native/device builds, simulators, emulators, desktop
windows, and OS-level automation permissions. The container owns source edits, in-container
SDK tooling (tests, analysis, formatting), and calls to the fixed-purpose bridge API.

## Limitations

- One bridge per sandbox/agent. Multiple sandboxes should use distinct bridge ports and run from
  the corresponding host Flutter project directories.
- macOS is the primary supported host platform.
- Flutter web is handled by Chrome/CDP integration.
- The bridge operates on a single project directory configured at startup.
- The bridge does not expose arbitrary host command execution.
- Concurrent bridge instances need manually configured ports.

## Troubleshooting

Check the Flutter bridge log:

```bash
cat /tmp/flutter-bridge.log
```

Common issues:

- Cannot reach Flutter bridge: start it with `workcell start-flutter-bridge` or
  `workcell --with-flutter`.
- Missing bridge token: when using `--with-flutter`, the token is auto-generated. For a separate
  bridge, start it from the workspace so `.workcell/flutter-config.json` is available.
- Concurrent sandbox needs a bridge: start a separate bridge on a different port.
- Port is already in use: use a different `--port`, update `.workcell/flutter-config.json`, or stop
  the existing process.
- Flutter subprocess fails to start: ensure the project compiles and the target device is
  available. Run `flutter doctor -v` on the host.
- `flutter: command not found`: set `FLUTTER_PATH` in `config.sh`.
