#!/bin/bash
# Flutter bridge control CLI wrapper (container-side)
# Usage: flutterctl <command> [args]
#
# Commands:
#   test                    - Test connection to Flutter bridge
#   status                  - Get bridge status (includes ui_automation capabilities)
#   devices                 - List available Flutter devices
#   launch [-d <device>]    - Launch Flutter app
#   attach [-d <device>]    - Attach to running Flutter app
#   detach                  - Detach/stop Flutter app
#   restart-bridge          - Restart the host bridge process
#   hot-reload              - Hot reload
#   hot-restart             - Hot restart
#   logs                    - Get recent Flutter logs
#   screenshot -o <path>    - Take screenshot (macOS captures app window only)
#   ios-probe               - Probe fixed host iOS Simulator input capabilities
#   tap                     - UI automation tap (coordinates or text/key selector)
#   type <text>             - Type text into current focus
#   press <key>             - Press a named key or combination (e.g. enter, command+r)
#   scroll                  - Scroll by named move (--move top|up|down)
#   inspect                 - Inspect UI state / semantics tree
#   wait                    - Wait for element matching text/key to appear

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
exec python3 "$SCRIPT_DIR/flutterctl.py" "$@"
