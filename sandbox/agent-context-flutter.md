# Flutter Native Agent Context

Use this document when a task involves Flutter or Dart development: in-container
SDK tooling (`flutter test`, `flutter analyze`, `dart format`, `flutter pub`),
native/device targets, the host Flutter bridge, hot reload, screenshots, or UI
automation.

For Flutter web, use [agent-context-web.md](agent-context-web.md) instead.

## Container Flutter SDK

A Flutter SDK is installed inside the container. Use it for all operations that do
not require a running device or simulator:

```bash
# Run unit and widget tests (headless, no device needed)
flutter test
flutter test test/widget_test.dart
flutter test --coverage

# Static analysis
flutter analyze
dart analyze

# Format checking and application
dart format --output=none .          # check only, exit 1 if unformatted
dart format .                        # apply formatting in place

# Package management
flutter pub get
flutter pub upgrade
flutter pub outdated

# Automated fixes
dart fix --dry-run
dart fix --apply

# Code generation (build_runner, l10n, etc.)
flutter gen-l10n
flutter pub run build_runner build --delete-conflicting-outputs
```

These commands run directly in the container without the Flutter bridge. Run them
against the workspace project (`pubspec.yaml` in scope) before and after editing
Dart source.

The `dart` binary is available alongside `flutter`. Both are on `PATH`.

Downloaded pub packages are cached in `~/.pub-cache/` which persists in the Docker
volume across container restarts.

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
flutterctl status                     # Bridge/app status, screenshot support, and UI automation capability
flutterctl devices                    # List available host Flutter devices
flutterctl launch [-d <device>]       # Launch on a device
flutterctl attach [-d <device>]       # Attach to an already-running app
flutterctl detach                     # Stop the app process managed by the bridge
flutterctl hot-reload                 # Hot reload
flutterctl hot-restart                # Hot restart
flutterctl logs                       # Recent Flutter logs
flutterctl screenshot -o <path>       # Screenshot; use .workcell/artifacts/
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

For tasks that only need tests, analysis, or formatting — no device required:

1. Run `flutter pub get` if dependencies are not yet fetched.
2. Edit Dart files in the container workspace.
3. Run `flutter analyze` and `flutter test` to verify correctness.
4. Run `dart format .` to apply formatting.

For tasks that require a running native/device target:

1. Run `flutter analyze` and `flutter test` in the container first.
2. Run `flutterctl test` to confirm bridge connectivity.
3. Run `flutterctl devices` and launch or attach to the app.
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
flutterctl screenshot -o .workcell/artifacts/20260429-132400-before.png
flutterctl hot-reload
flutterctl screenshot -o .workcell/artifacts/20260429-132405-after.png
```

On macOS desktop, screenshots are app-window-only. If the bridge cannot identify the Flutter window or host privacy permissions block capture, the command fails instead of capturing the full screen.

Screenshot support is reported by the top-level `status.screenshot` object, not by
`status.ui_automation.actions`. `ui_automation` only describes interactive UI actions such as tap,
type, press, scroll, inspect, and wait. On macOS desktop, `status.screenshot.supported=true` means
the bridge uses host `screencapture` against the Flutter app window; it does not mean Flutter's own
`flutter screenshot` command supports macOS desktop.

Save temporary screenshots and other generated verification artifacts under `.workcell/artifacts/`. Prefer timestamped filenames so repeated runs do not overwrite useful evidence.

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
