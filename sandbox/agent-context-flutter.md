# Flutter Native Agent Context

Use this document when a task involves Flutter or Dart development: in-container
SDK tooling (`flutter test`, `flutter analyze`, `dart format`, `flutter pub`),
native/device targets, the host Flutter bridge, hot reload, screenshots, or UI
automation.

For Flutter web, read `/opt/agent-context-web.md` and use the web development workflow instead.

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

The `dart` binary is available alongside `flutter`. Both are on `PATH`. The
container exposes workcell wrappers for `flutter` and `dart`; they repair
host-generated `.dart_tool/package_config.json` metadata with `flutter pub get`
before delegating to the real SDK binaries when needed.

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

If the bridge is reachable but running stale bridge code, use `flutterctl restart-bridge`. This authenticated command re-execs the existing host bridge process with the same launch settings.

`--with-flutter` and `--with-chrome` are mutually exclusive. In Flutter mode, `--bridge-port <port>` selects the host Flutter bridge port and `--port <port>` exposes a container dev-server port.

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
flutterctl restart-bridge             # Restart the host bridge process
flutterctl hot-reload                 # Hot reload
flutterctl hot-restart                # Hot restart
flutterctl logs                       # Recent Flutter logs
flutterctl screenshot -o <path>       # Screenshot; use .workcell/artifacts/screenshots/ when useful
flutterctl ios-map                    # Diagnose iOS coordinate mapping when applicable
flutterctl inspect                    # Discover visible UI state when supported
flutterctl inspect --key <key>        # Inspect an automation id when supported
flutterctl inspect --text <text>      # Inspect resolvable visible text when supported
flutterctl tap --key <key>            # Tap an automation id when supported
flutterctl tap --text "Sign in"       # Tap visible text when supported
flutterctl tap --x 150 --y 300        # Coordinate tap when supported
flutterctl type "hello"               # Type into focused input when supported
flutterctl press enter                # Press a named key when supported
flutterctl scroll --move down         # Scroll when supported
flutterctl wait --key <key>           # Wait for an automation id when supported
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
flutterctl devices
flutterctl launch --device <ios-simulator-uuid>
flutterctl launch --device macos
flutterctl launch --device emulator-5554
```

iOS Simulators usually need the exact device id shown by `flutterctl devices`, such as a
CoreSimulator UUID. `--device ios` only works if Flutter reports a device whose name or id matches
`ios`.

Attach to an app that is already running from a host terminal, Xcode, or another Flutter tool:

```bash
flutterctl devices
flutterctl attach --device <ios-simulator-uuid>
flutterctl status
```

### Switching Targets

The bridge manages one Flutter app process at a time. Before launching or attaching to a different
device, detach from the current app:

```bash
flutterctl detach
flutterctl launch --device <new-device>
```

Screenshot example:

```bash
flutterctl screenshot -o .workcell/artifacts/screenshots/20260429-132400-before.png
flutterctl hot-reload
flutterctl wait --text "Updated Title"
flutterctl screenshot -o .workcell/artifacts/screenshots/20260429-132405-after.png
```

`flutterctl hot-reload` and `flutterctl hot-restart` send `r`/`R` to the host Flutter process and
return after the command is written. They do not wait for compilation or frame rendering to finish.
Before taking screenshots or running UI automation, wait briefly or poll for the expected UI state
with `flutterctl wait`.

The host bridge validates `.dart_tool/package_config.json` before `launch`,
`attach`, `hot-reload`, and `hot-restart`. If the file contains container-only
paths, the bridge runs host-side `flutter pub get` first so host Flutter uses
host-valid package metadata. Conversely, container `flutter` and `dart` wrappers
repair host-only metadata before local format, analyze, test, and pub workflows.

On macOS desktop, screenshots are app-window-only. If the bridge cannot identify the Flutter window or host privacy permissions block capture, the command fails instead of capturing the full screen.

Screenshot support is reported by the top-level `status.screenshot` object, not by
`status.ui_automation.actions`. `ui_automation` only describes interactive UI actions such as tap,
type, press, scroll, inspect, and wait. On macOS desktop, `status.screenshot.supported=true` means
the bridge uses host `screencapture` against the Flutter app window; it does not mean Flutter's own
`flutter screenshot` command supports macOS desktop.

Save temporary screenshots and other generated verification artifacts under `.workcell/artifacts/`. Use optional subdirectories such as `screenshots/`, `logs/`, and `mockups/` when they help organize related files. Prefer timestamped filenames so repeated runs do not overwrite useful evidence.

## UI Automation

Treat `flutterctl status` as authoritative before running UI automation. It includes a `ui_automation` object with backend, target, readiness, coordinate-space metadata, missing host tools, and per-action support.

Do not assume coordinate taps, selectors, scrolling, typing, or waits are available unless `status.ui_automation.actions` marks them as supported. Unsupported or unavailable actions return structured errors such as `UNSUPPORTED_TARGET`, `UI_NOT_READY`, or `NO_APP_RUNNING`.

Prefer this order for agent-driven interaction:

1. `flutterctl inspect` to discover visible text, automation ids, widget types, and rectangles.
2. `flutterctl inspect --key <key>` when a stable automation identifier should exist.
3. `flutterctl tap --key` or `flutterctl wait --key` when automation id selectors are supported.
4. Text selectors when inspect can resolve visible text to a rectangle.
5. Coordinate taps only when selectors are unavailable and coordinates are known.
6. Screenshots when visual layout is ambiguous or after UI changes need visual validation.

Stable `Semantics.identifier` values make automation reliable. Prefer identifiers on important controls and containers such as `login_button`, `email_field`, `settings_tab`, `todo_list`, and repeated row actions like `delete_item_0`.

When building or modifying Flutter UI, add `Semantics(identifier: '<automation_id>', child: ...)` to every element that should be selectable by `flutterctl inspect --key`, `wait --key`, or `tap --key`. A `ValueKey` alone is useful for Flutter widget tests, but it is not the bridge automation selector contract.

For macOS desktop automation, make sure Flutter is generating semantics. Desktop Flutter may skip semantics until assistive technology requests it; automation-ready debug builds can force generation after `WidgetsFlutterBinding.ensureInitialized()` with a retained `SemanticsBinding.instance.ensureSemantics()` handle.

Text selectors are not arbitrary Flutter selectors. They work only for elements whose bounds can be resolved through inspect, accessibility, or selected tooltip labels. Key selectors use Flutter semantics identifiers.

Current Flutter bridge UI automation scope is narrow: macOS hosts only, targeting iOS Simulator and macOS desktop apps. Android, Linux desktop, Windows desktop, physical iOS, Flutter web, and non-macOS hosts should be treated as unsupported by the Flutter bridge UI action API.

On iOS Simulator:

- Screenshots use `flutter screenshot` and capture the device screen.
- `inspect` and `wait` use Flutter VM-service semantics data for `--key` selectors and inspector data for `--text` selectors when the launched app exposes a VM service.
- `inspect` rectangles are reported in `flutter-logical-points`.
- `tap --x --y` uses `simulator-window-points`; `x=0,y=0` is the top-left of the visible host Simulator window reported in `status.ui_automation.screen.simulator_window`.
- Use `flutterctl ios-map` to inspect the current mapping estimate before converting inspected rectangles into coordinate taps.
- Coordinate taps require the host Simulator window to be visible and unminimized. If `status.ui_automation.screen` reports an error, coordinate taps should be treated as unavailable.
- `tap --key` uses Flutter VM-service semantics identifiers and defaults to the matched semantics rect center after mapping it into the visible host Simulator window.
- `tap --text` uses Flutter inspector selectors, widget screenshot matching when available, and the same mapped rectangle-center fallback.
- `type` sends host keystrokes to the currently focused control in the Simulator. Focus a text field first; the command does not choose a target by selector.
- After tapping a text field on iOS, wait briefly before typing so the keyboard and focused input are ready.
- The keystroke typing backend avoids the iOS paste permission prompt, but may be less suitable for long text or unusual characters than a future paste-based implementation.
- `press` sends a focused key event to the host Simulator process. This is intended for keys such as `enter`, `tab`, `backspace`, and arrow keys.
- `scroll` approximates vertical scrolling with focused key dispatch. `--move top` sends `home`, `--move up` sends `pageup`, and `--move down` sends `pagedown`. This is not pixel-accurate.
- With multiple booted iOS Simulators, launch or attach with an explicit device id. The bridge uses the selected device id for native screenshot probes and prefers the visible Simulator window whose title matches the selected Flutter device name.
- `flutterctl ios-map` is an iOS Simulator diagnostic. It reports native screenshot size, selected Simulator window bounds, host-window screenshot dimensions, sampled device-content match, host Simulator Accessibility frames when available, Flutter inspector root size, and coordinate estimates. On non-iOS-Simulator targets it returns `UNSUPPORTED_TARGET`.
- Current research points to XCTest/XCUI gestures as Apple's supported automation surface for precise swipes/drags; `simctl` exposes screenshot/video and simulator UI settings but no verified direct scroll primitive in the bridge probes.

On macOS desktop:

- Coordinate taps use `app-window-points`; `x=0,y=0` is the top-left of the Flutter app window reported in `status.ui_automation.screen`.
- `scroll` approximates scrolling with keyboard dispatch. `--move top` sends `home`, `--move up` sends `pageup`, and `--move down` sends `pagedown`; it is not pixel-accurate.
- Inspect, wait, and `tap --key` use Flutter VM-service semantics identifiers. If `inspect --key` returns no matches and the semantics dump says semantics are not generated, enable semantics in the app or turn on a host assistive technology before relying on key selectors.
- Text selectors use host Accessibility plus Flutter inspector previews and selected tooltip labels when a VM service is available.

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

Common first-run errors:

> **Error: Flutter app is already run/running/attached** - Run `flutterctl detach` before launching or attaching to a different device.
>
> **Flutter doctor shows missing SDKs** - This can be expected in the container. Native iOS and Android targets run through the host bridge; use the container Flutter SDK for tests, analysis, formatting, and package management.
