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
The container puts `flutter` and `dart` on `PATH` through workcell wrappers that delegate to the
bundled SDK under `~/persist/.flutter-sdk`. Those wrappers automatically repair host-generated
`.dart_tool/package_config.json` metadata before local SDK commands.
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

Agents can restart a reachable bridge without host shell access:

```bash
flutterctl restart-bridge
```

This authenticated command re-execs the existing host bridge process with the same project, port,
token, target, and run arguments.

Launch iOS Simulators with the exact device id reported by Flutter:

```bash
flutterctl devices
flutterctl launch --device <ios-simulator-uuid>
```

`--device ios` only works if Flutter reports a device whose name or id matches `ios`; typical
iOS Simulator devices use CoreSimulator UUIDs. If launch fails, `flutterctl status` reports the
bridge state and `flutterctl logs` shows the underlying host `flutter run` output.

`flutterctl hot-reload` and `flutterctl hot-restart` are command-send operations. They write `r` or
`R` to the host Flutter process and return after the command is sent, not after compilation and
frame rendering are complete. Before screenshots or UI automation, wait briefly or poll for the
expected UI with `flutterctl wait`.

The bridge checks `.dart_tool/package_config.json` before `launch`, `attach`, `hot-reload`, and
`hot-restart`. If package roots point to container-only locations or the metadata is missing, it
runs host-side `flutter pub get` first. This allows agents to alternate between in-container SDK
commands and host bridge runs without manually deleting `.dart_tool` or `build`.

## UI Automation

The bridge currently supports host Flutter workflows from macOS hosts only. UI automation is scoped
to macOS desktop apps and iOS Simulator targets on those hosts. macOS desktop automation uses host
Accessibility and Screen Recording permissions, so the first run may trigger privacy prompts. iOS
Simulator coordinate taps require the host Simulator window to be visible and unminimized.

Prefer stable semantics identifiers for agent-driven Flutter UI interactions when the app can
provide them. Use `Semantics(identifier: 'login_button', child: ...)` on controls and important
containers so selectors are independent of visible copy, localization, and layout changes. Useful
examples: `login_button`, `email_field`, `settings_tab`, `todo_list`, and `delete_item_0`.
When building or modifying Flutter UI, add a `Semantics.identifier` to every element that should be
selectable by automation. A `ValueKey` alone is useful for Flutter widget tests, but it is not the
automation selector contract for the bridge.
For macOS desktop automation, ensure the app actually generates a semantics tree. Flutter desktop
may skip semantics until assistive technology requests it; automation-ready debug builds can force
generation after `WidgetsFlutterBinding.ensureInitialized()` with a retained
`SemanticsBinding.instance.ensureSemantics()` handle.

UI automation is currently scoped to iOS Simulator and macOS desktop backends on macOS hosts.
Android, Linux desktop, Windows desktop, physical iOS, Flutter web, and non-macOS hosts are not
supported by the Flutter bridge UI action API.

iOS Simulator supports:

- `flutterctl inspect` and `flutterctl wait` with `--key` selectors through Flutter VM-service
  semantics identifiers. `--text` uses Flutter VM-service inspector text data.
- `flutterctl tap --x <x> --y <y>` in `simulator-window-points`, relative to
  `status.ui_automation.screen.simulator_window`.
- `flutterctl tap --key <key>` through Flutter VM-service semantics identifiers, defaulting to the
  semantics rect center after mapping it into the visible host Simulator window.
- `flutterctl tap --text <text>` through Flutter inspector selectors, with widget screenshot
  matching when available and the same mapped rectangle-center fallback.
- `flutterctl type "text"` into the currently focused control. The bridge sends host keystrokes to
  the Simulator, similar to the macOS desktop typing backend.
- `flutterctl press <key>` for focused key input through the host Simulator process.
- `flutterctl scroll --move <top|up|down>` as a page-key approximation through host key dispatch.
  `top` sends `home`, `up` sends `pageup`, and `down` sends `pagedown`. This is not pixel-accurate
  scrolling.
- `flutterctl ios-map` as a read-only diagnostic for native screenshot size, Simulator window
  bounds, host-window screenshot dimensions, sampled device-content matching, host Simulator
  Accessibility frames when available, Flutter inspector root size, and coordinate estimates.

When multiple iOS Simulators are booted, launch or attach with an explicit device id. The bridge
uses that selected id for native screenshot probes and prefers the visible Simulator window whose
title matches the selected Flutter device name.

iOS semantics and inspector rectangles are reported in root `flutter-logical-points`; selector taps
map them to `simulator-window-points` at action time. For `--key` selectors, the bridge composes
ancestor semantics offsets so descendants in overlays, dialogs, and bottom sheets are reported in
the same root coordinate space as top-level controls. Semantics identifiers are preferred because
their rects reflect Flutter semantics geometry and have proven more reliable for bottom sheets and
overlays than inspector layout rectangles. Typing requires the intended text field to already be
focused. After tapping a text field, wait briefly before typing so the iOS keyboard and focused
input are ready. The keystroke backend avoids the iOS paste permission prompt, but may be less
suitable for long text or unusual characters than a future paste-based implementation.

On macOS desktop, `flutterctl inspect --key`, `wait --key`, and `tap --key` also use Flutter
VM-service semantics identifiers. Key selector taps use the matched semantics rect center in
`app-window-points`. Text selectors continue to use host Accessibility plus Flutter inspector text
and selected tooltip labels when a VM service is available. If `inspect --key` returns no matches
and the semantics dump says semantics are not generated, enable semantics in the app or turn on a
host assistive technology before relying on key selectors.

The current scroll research points to XCTest/XCUI as Apple's supported gesture automation surface:
`XCUICoordinate` supports swipes, coordinate scrolling, and press-then-drag gestures. Apple's
`simctl` documentation still points users to `simctl io` for screenshots and video, and the bridge's
fixed host probes have not found a direct `simctl` scroll or gesture primitive. The current
`flutterctl scroll` implementation intentionally uses the simpler Simulator page-key behavior; a
future precise scroll backend should be evaluated as either a minimal XCTest/XCUI helper or a
constrained host-window drag implementation.

## Screenshots

The bridge supports screenshots for native/device targets when a Flutter app is running under the
bridge. On iOS Simulator and other mobile targets, screenshots use Flutter's device screenshot
support. On macOS desktop, screenshots capture only the Flutter app window. If the app window cannot
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
- Bridge is reachable but stale after code changes: run `flutterctl restart-bridge`.
- Missing bridge token: when using `--with-flutter`, the token is auto-generated. For a separate
  bridge, start it from the workspace so `.workcell/flutter-config.json` is available.
- Concurrent sandbox needs a bridge: start a separate bridge on a different port.
- Port is already in use: use a different `--port`, update `.workcell/flutter-config.json`, or stop
  the existing process.
- Flutter subprocess fails to start: ensure the project compiles and the target device is
  available. Run `flutter doctor -v` on the host.
- Host bridge `flutter: command not found`: set host `FLUTTER_PATH` in `config.sh`.
- Container `flutter: command not found`: restart with an updated workcell image; the entrypoint
  re-asserts `~/persist/.flutter-sdk/bin` and workcell wrappers on `PATH`.
