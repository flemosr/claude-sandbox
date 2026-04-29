# Flutter Native Agent Context

Use this document when a task involves native/device Flutter targets, the host Flutter bridge, hot reload, screenshots, UI automation, or the `flutterctl` CLI.

For Flutter web, use [agent-context-web.md](agent-context-web.md) instead.

## Bridge Model

Native Flutter toolchains and targets live on the host machine. The container does not run iOS Simulator, Android Emulator, Xcode, Android Studio, or physical-device tooling directly.

The Flutter bridge lets the container launch, attach to, hot reload, screenshot, inspect, and interact with a host-running Flutter app. The host-side project path is intentionally not passed into the container; edit files in the current workspace and let the bridge map commands to the host project path.

Use one bridge per sandbox or agent. Concurrent agents should use separate bridge instances on distinct ports.

## Availability Checks

Check bridge connectivity first:

```bash
flutterctl test
```

If the bridge is unavailable, tell the user they can either run `workcell start-flutter-bridge` on the host from the Flutter project directory or restart the sandbox with `--with-flutter`.

`--with-flutter` and `--with-chrome` are mutually exclusive. In Flutter mode, `--port <port>` selects the host Flutter bridge port and does not expose a container dev-server port.

Connection details and optional launch settings live in `.workcell/flutter-config.json`:

```bash
cat .workcell/flutter-config.json
```

The file may include project-local launch settings such as:

```json
{
  "target": "lib/main_dev.dart",
  "run_args": ["--flavor", "staging", "--dart-define", "API_BASE_URL=https://api.example.test"]
}
```

The bridge preserves those settings when it writes runtime connection details.

## Flutterctl CLI

```bash
flutterctl test                       # Test bridge connection
flutterctl status                     # Bridge/app status and UI automation capability
flutterctl devices                    # List available host Flutter devices
flutterctl launch [-d <device>]       # Launch on a device
flutterctl attach [-d <device>]       # Attach to an already-running app
flutterctl detach                     # Stop the app process managed by the bridge
flutterctl hot-reload                 # Hot reload
flutterctl hot-restart                # Hot restart
flutterctl logs                       # Recent Flutter logs
flutterctl screenshot -o <path>       # Screenshot; macOS captures app window only
flutterctl inspect                    # Discover visible UI state when supported
flutterctl inspect --key <key>        # Inspect a keyed widget when supported
flutterctl inspect --text <text>      # Inspect resolvable visible text when supported
flutterctl tap --key <key>            # Tap keyed widget when supported
flutterctl tap --text "Sign in"       # Tap visible text when supported
flutterctl tap --x 150 --y 300        # Coordinate tap when supported
flutterctl type "hello"               # Type into focused input when supported
flutterctl press enter                # Press a named key when supported
flutterctl scroll --dy 600            # Scroll when supported
flutterctl wait --key <key>           # Wait for keyed widget when supported
flutterctl wait --text "Ready"        # Wait for visible text when supported
```

Status values:

- `idle` - no app process managed by the bridge.
- `running` - app launched through the bridge.
- `attached` - bridge attached to an externally-running app.
- `error` - Flutter subprocess failed.

## Development Workflow

1. Run `flutterctl test`.
2. Run `flutterctl devices`.
3. Launch or attach to the app.
4. Run `flutterctl status` and inspect any reported errors.
5. Edit Dart files in the container workspace.
6. Run `flutterctl hot-reload` or `flutterctl hot-restart`.
7. Use logs, inspect output, screenshots, and supported UI automation to verify behavior.

Launch examples:

```bash
flutterctl launch --device ios
flutterctl launch --device macos
flutterctl launch --device emulator-5554
```

Attach example:

```bash
flutterctl attach --device ios
```

Screenshot example:

```bash
flutterctl screenshot -o before.png
flutterctl hot-reload
flutterctl screenshot -o after.png
```

On macOS desktop, screenshots are app-window-only. If the bridge cannot identify the Flutter window or host privacy permissions block capture, the command fails instead of capturing the full screen.

## UI Automation

Treat `flutterctl status` as authoritative before running UI automation. It includes a `ui_automation` object with backend, target, readiness, coordinate-space metadata, missing host tools, and per-action support.

Do not assume coordinate taps, selectors, scrolling, typing, or waits are available unless `status.ui_automation.actions` marks them as supported. Unsupported or unavailable actions return structured errors such as `UNSUPPORTED_TARGET`, `UI_NOT_READY`, or `NO_APP_RUNNING`.

Prefer this order for agent-driven interaction:

1. `flutterctl inspect` to discover visible text, widget keys, widget types, and rectangles.
2. `flutterctl inspect --key <key>` when a stable key should exist.
3. `flutterctl tap --key` or `flutterctl wait --key` when key selectors are supported.
4. Text selectors when inspect can resolve visible text to a rectangle.
5. Coordinate taps only when selectors are unavailable and coordinates are known.
6. Screenshots when visual layout is ambiguous or after UI changes need visual validation.

Stable `ValueKey<String>` values make automation reliable. Prefer keys on important controls and containers such as `login_button`, `email_field`, `settings_tab`, `todo_list`, and repeated row actions like `delete_item_0`.

Text selectors are not arbitrary Flutter selectors. They work only for elements whose bounds can be resolved through inspect, accessibility, or selected tooltip labels. Key selectors require Flutter inspector key and layout data for the same widget.

Current UI automation target scope is narrow: iOS Simulator and macOS desktop only. Android, Linux desktop, Windows desktop, physical iOS, and Flutter web should be treated as unsupported by the Flutter bridge UI action API.

On macOS desktop:

- Coordinate taps use `app-window-points`; `x=0,y=0` is the top-left of the Flutter app window reported in `status.ui_automation.screen`.
- `scroll` approximates scrolling with keyboard dispatch. `dx` and `dy` choose direction and dominant axis, not exact pixels.
- Inspect, wait, and selector taps use host Accessibility plus Flutter inspector previews, keys, and selected tooltip labels when a VM service is available.

## Troubleshooting

Check the bridge log when connection or launch fails:

```bash
cat "$FLUTTER_BRIDGE_LOG_FILE"
```

Fallback log path:

```bash
cat /tmp/flutter-bridge.log
```

Check bridge environment overrides:

```bash
echo "URL: $FLUTTER_BRIDGE_URL"
```

If `flutterctl test` succeeds but `flutterctl launch` fails, inspect the bridge log for Flutter build errors on the host side.
