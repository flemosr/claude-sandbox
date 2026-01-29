#!/bin/bash
# Start Chrome with remote debugging enabled for Claude sandbox connection
#
# Run this script on your Mac BEFORE starting the Claude sandbox.
# The sandbox will connect to Chrome via CDP (Chrome DevTools Protocol).
#
# Configuration (REQUIRED):
#   Settings are loaded from config.sh. Command line args can override.
#
# Usage:
#   ./start-chrome-debug.sh                    # Use settings from config.sh
#   ./start-chrome-debug.sh --port 9333        # Override port
#   ./start-chrome-debug.sh --profile Default  # Override Chrome profile
#   ./start-chrome-debug.sh --restart          # Kill running Chrome and restart with debugging
#
# Profile names are folder names in ~/Library/Application Support/Google/Chrome/
# Common values: "Default", "Profile 1", "Profile 2", etc.
# To find your profile folder, check: chrome://version (Profile Path)

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Find config file
if [ -f "$REPO_ROOT/config.sh" ]; then
    CONFIG_FILE="$REPO_ROOT/config.sh"
else
    echo "Error: No config file found in $REPO_ROOT"
    echo ""
    echo "Please create config.sh from the template:"
    echo ""
    echo "  cd $REPO_ROOT"
    echo "  cp config.template.sh config.sh"
    echo ""
    echo "Then edit config.sh with your Chrome profile (check chrome://version)."
    echo ""
    exit 1
fi

# Load config
source "$CONFIG_FILE"

# Validate required config values
missing_config=()
[ -z "$CHROME_PATH" ] && missing_config+=("CHROME_PATH")
[ -z "$CHROME_USER_DATA" ] && missing_config+=("CHROME_USER_DATA")
[ -z "$CHROME_DEBUG_DATA" ] && missing_config+=("CHROME_DEBUG_DATA")
[ -z "$CHROME_PROFILE" ] || [ "$CHROME_PROFILE" = "CHANGE_ME" ] && missing_config+=("CHROME_PROFILE")
[ -z "$CHROME_DEBUG_PORT" ] && missing_config+=("CHROME_DEBUG_PORT")
[ -z "$CHROME_INTERNAL_PORT" ] && missing_config+=("CHROME_INTERNAL_PORT")
[ -z "$CHROME_LOG_FILE" ] && missing_config+=("CHROME_LOG_FILE")

if [ ${#missing_config[@]} -gt 0 ]; then
    echo "Error: Missing or invalid config in $CONFIG_FILE:"
    for key in "${missing_config[@]}"; do
        echo "  - $key"
    done
    exit 1
fi

RESTART=false

# Parse arguments (override config file settings)
while [[ $# -gt 0 ]]; do
    case $1 in
        --port|-p)
            CHROME_DEBUG_PORT="$2"
            shift 2
            ;;
        --profile)
            CHROME_PROFILE="$2"
            shift 2
            ;;
        --restart|-r)
            RESTART=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--port PORT] [--profile CHROME_PROFILE_DIR] [--restart]"
            exit 1
            ;;
    esac
done

if [ ! -f "$CHROME_PATH" ]; then
    echo "Error: Chrome not found at $CHROME_PATH"
    echo "Please install Google Chrome from https://www.google.com/chrome/"
    exit 1
fi

# Check if Chrome is already running (must be closed for remote debugging to work)
if pgrep -x "Google Chrome" >/dev/null 2>&1; then
    if $RESTART; then
        echo "Chrome is running. Restarting it with remote debugging..."
        pkill -x "Google Chrome"
        # Wait for Chrome to fully quit
        for i in {1..10}; do
            if ! pgrep -x "Google Chrome" >/dev/null 2>&1; then
                break
            fi
            sleep 0.5
        done
        if pgrep -x "Google Chrome" >/dev/null 2>&1; then
            echo "Error: Failed to quit Chrome. Please close it manually."
            exit 1
        fi
        sleep 1  # Brief pause to ensure clean shutdown
    else
        echo "Error: Chrome is already running."
        echo ""
        echo "Remote debugging requires Chrome to be started fresh with special flags."
        echo "Please use the --restart flag to auto-restart Chrome, or quit Chrome completely before running this script:"
        echo ""
        echo "  1. Click Chrome in menu bar → Quit Google Chrome"
        echo "     OR"
        echo "  2. Press Cmd+Q while Chrome is focused"
        echo "     OR"
        echo "  3. Run: pkill -x 'Google Chrome'"
        echo ""
        exit 1
    fi
fi

# Truncate log file for fresh start, then tee all output
: > "$CHROME_LOG_FILE"
exec > >(tee "$CHROME_LOG_FILE") 2>&1

# Check for socat (required for Docker connectivity)
if ! command -v socat &> /dev/null; then
    echo "Error: socat is required but not installed."
    echo "Install it with: brew install socat"
    exit 1
fi

# Check if the profile exists in main Chrome directory
if [ ! -d "$CHROME_USER_DATA/$CHROME_PROFILE" ]; then
    echo "Warning: Profile '$CHROME_PROFILE' not found in $CHROME_USER_DATA"
    echo ""
    echo "Available profiles:"
    ls -1 "$CHROME_USER_DATA" | grep -E "^(Default|Profile)" || echo "  (none found)"
    echo ""
    echo "To find your profile folder name, open Chrome and go to: chrome://version"
    echo "Look for 'Profile Path' - the last folder name is what you need."
    echo ""
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Set up debug directory with profile symlink
mkdir -p "$CHROME_DEBUG_DATA"
if [ ! -e "$CHROME_DEBUG_DATA/$CHROME_PROFILE" ] && [ -d "$CHROME_USER_DATA/$CHROME_PROFILE" ]; then
    echo "Linking profile to debug directory..."
    ln -sf "$CHROME_USER_DATA/$CHROME_PROFILE" "$CHROME_DEBUG_DATA/$CHROME_PROFILE"
fi
# Also link Local State file (contains profile metadata)
if [ ! -e "$CHROME_DEBUG_DATA/Local State" ] && [ -f "$CHROME_USER_DATA/Local State" ]; then
    ln -sf "$CHROME_USER_DATA/Local State" "$CHROME_DEBUG_DATA/Local State"
fi

# Check if ports are already in use
if lsof -i :$CHROME_DEBUG_PORT >/dev/null 2>&1; then
    echo "Port $CHROME_DEBUG_PORT is already in use."
    echo "If Chrome debug is already running, you're good to go!"
    echo "Otherwise, close the application using port $CHROME_DEBUG_PORT and try again."
    exit 1
fi

if lsof -i :$CHROME_INTERNAL_PORT >/dev/null 2>&1; then
    echo "Internal port $CHROME_INTERNAL_PORT is already in use."
    exit 1
fi

# Cleanup function
CLEANUP_DONE=false
cleanup() {
    $CLEANUP_DONE && return
    CLEANUP_DONE=true
    echo ""
    echo "Shutting down..."
    [ -n "$SOCAT_PID" ] && kill $SOCAT_PID 2>/dev/null
    [ -n "$CHROME_PID" ] && kill $CHROME_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

echo "Starting Chrome with remote debugging..."
echo "  External port: $CHROME_DEBUG_PORT (accessible from Docker)"
echo "  Profile: $CHROME_PROFILE"
echo ""

# Start Chrome in background
"$CHROME_PATH" \
    --remote-debugging-port=$CHROME_INTERNAL_PORT \
    --remote-allow-origins=* \
    --user-data-dir="$CHROME_DEBUG_DATA" \
    --profile-directory="$CHROME_PROFILE" \
    --no-first-run &
CHROME_PID=$!

# Wait for Chrome to start listening
echo "Waiting for Chrome to start..."
for i in {1..30}; do
    if lsof -i :$CHROME_INTERNAL_PORT >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

if ! lsof -i :$CHROME_INTERNAL_PORT >/dev/null 2>&1; then
    echo "Error: Chrome failed to start on port $CHROME_INTERNAL_PORT"
    exit 1
fi

# Start socat to forward from 0.0.0.0:CHROME_DEBUG_PORT to 127.0.0.1:CHROME_INTERNAL_PORT
echo "Starting port forwarder (socat)..."
socat TCP-LISTEN:$CHROME_DEBUG_PORT,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:$CHROME_INTERNAL_PORT &
SOCAT_PID=$!

sleep 1

if ! kill -0 $SOCAT_PID 2>/dev/null; then
    echo "Error: socat failed to start"
    exit 1
fi

echo ""
echo "Ready! Chrome is accessible from Docker at host.docker.internal:$CHROME_DEBUG_PORT"
echo "Press Ctrl+C to stop."
echo ""

# Wait for Chrome to exit
wait $CHROME_PID 2>/dev/null
