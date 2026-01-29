#!/bin/bash
# Claude Code Sandbox CLI
#
# Usage:
#   claude-sandbox run [options]           Run the sandbox in current directory
#   claude-sandbox start-chrome [options]  Start Chrome with remote debugging
#   claude-sandbox help                    Show this help message
#
# For detailed help on each command:
#   claude-sandbox run --help
#   claude-sandbox start-chrome --help

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

show_help() {
    cat << 'EOF'
Claude Code Sandbox - Run Claude Code safely in Docker

Usage:
  claude-sandbox <command> [options]

Commands:
  run             Run the sandbox in current directory (default)
  start-chrome    Start Chrome with remote debugging (run on host)
  help            Show this help message

Examples:
  claude-sandbox run
  claude-sandbox run --yolo --with-chrome --port 3000
  claude-sandbox start-chrome
  claude-sandbox start-chrome --restart

For more information, see README.md
EOF
}

show_run_help() {
    cat << 'EOF'
Run the Claude Code sandbox in the current directory

Usage:
  claude-sandbox run [options] [-- claude-args]

Options:
  --yolo            Enable YOLO mode (no permission prompts)
  --firewalled      Restrict network to essential domains only
  --with-chrome     Start Chrome with remote debugging
  --port <port>     Expose a port for dev servers (can be repeated)

Examples:
  claude-sandbox run
  claude-sandbox run --yolo
  claude-sandbox run --yolo --with-chrome --port 3000
  claude-sandbox run --port 3000 --port 5173
  claude-sandbox run --yolo -p "fix the tests"
EOF
}

show_start_chrome_help() {
    cat << 'EOF'
Start Chrome with remote debugging for sandbox connection

Usage:
  claude-sandbox start-chrome [options]

Options:
  --port <port>       Override debug port from config
  --profile <name>    Override Chrome profile from config
  --restart, -r       Kill running Chrome and restart with debugging

Examples:
  claude-sandbox start-chrome
  claude-sandbox start-chrome --restart
  claude-sandbox start-chrome --port 9333 --profile "Profile 1"

Note: Chrome must not be running, or use --restart to auto-restart it.
EOF
}

# Parse command
command="${1:-}"

case "$command" in
    run|"")
        # Default command: run sandbox
        shift 2>/dev/null || true

        if [[ "$1" == "--help" || "$1" == "-h" ]]; then
            show_run_help
            exit 0
        fi

        exec "$SCRIPT_DIR/scripts/run_sandbox.sh" "$@"
        ;;

    start-chrome)
        shift

        if [[ "$1" == "--help" || "$1" == "-h" ]]; then
            show_start_chrome_help
            exit 0
        fi

        exec "$SCRIPT_DIR/scripts/start-chrome-debug.sh" "$@"
        ;;

    help|--help|-h)
        show_help
        exit 0
        ;;

    *)
        # Unknown command - could be flags for open-workspace (backwards compat)
        # Check if it looks like a flag
        if [[ "$command" == -* ]]; then
            exec "$SCRIPT_DIR/scripts/run_sandbox.sh" "$@"
        else
            echo "Unknown command: $command"
            echo ""
            show_help
            exit 1
        fi
        ;;
esac
