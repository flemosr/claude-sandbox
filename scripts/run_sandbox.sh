#!/bin/bash
# Claude Code Sandbox - runs in Docker with current directory mounted

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

yolo_flag=""
firewalled=false
chrome_enabled=false
ports=()
args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yolo)
      yolo_flag="--dangerously-skip-permissions"
      shift
      ;;
    --firewalled)
      firewalled=true
      shift
      ;;
    --with-chrome)
      chrome_enabled=true
      shift
      ;;
    --port)
      ports+=("$2")
      shift 2
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

mkdir -p "$(pwd)/.claude/sessions"

project_name="${PWD##*/}"
container_name="claude-sandbox-$$"

# Source config.sh if it exists (required for Chrome integration)
if [ -f "$REPO_ROOT/config.sh" ]; then
  source "$REPO_ROOT/config.sh"
fi

# Cleanup function for Chrome process
cleanup() {
  docker stop "$container_name" 2>/dev/null || true
  if [ -n "$CHROME_PID" ]; then
    echo "Stopping Chrome debug session..."
    kill $CHROME_PID 2>/dev/null || true
    wait $CHROME_PID 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM HUP

# Start Chrome with remote debugging if enabled
if $chrome_enabled; then
  # Validate config.sh exists and has required Chrome settings
  if [ ! -f "$REPO_ROOT/config.sh" ]; then
    echo "Error: Chrome integration requires config.sh"
    echo ""
    echo "Please create config.sh from the template:"
    echo ""
    echo "  cd $REPO_ROOT"
    echo "  cp config.template.sh config.sh"
    echo ""
    echo "Then edit config.sh with your Chrome profile (check chrome://version)."
    exit 1
  fi

  if [ -z "$CHROME_DEBUG_PORT" ]; then
    echo "Error: CHROME_DEBUG_PORT not set in $REPO_ROOT/config.sh"
    exit 1
  fi

  if [ -z "$CHROME_LOG_FILE" ]; then
    echo "Error: CHROME_LOG_FILE not set in $REPO_ROOT/config.sh"
    exit 1
  fi

  if [ ! -f "$SCRIPT_DIR/start-chrome-debug.sh" ]; then
    echo "Error: start-chrome-debug.sh not found in $SCRIPT_DIR"
    exit 1
  fi

  # Check for socat
  if ! command -v socat &> /dev/null; then
    echo "Error: socat is required for Chrome integration."
    echo "Install it with: brew install socat"
    exit 1
  fi

  echo "Starting Chrome with remote debugging..."
  echo "Chrome logs: $CHROME_LOG_FILE"
  # Use --quiet to log to file only (no stdout mixing with Docker output)
  "$SCRIPT_DIR/start-chrome-debug.sh" --quiet &
  CHROME_PID=$!

  # Wait for Chrome to be ready (up to 15s)
  echo "Waiting for Chrome to be ready..."
  chrome_ready=false
  for _ in {1..30}; do
    if lsof -i :$CHROME_DEBUG_PORT >/dev/null 2>&1; then
      chrome_ready=true
      echo "Chrome is ready!"
      break
    fi
    if ! kill -0 $CHROME_PID 2>/dev/null; then break; fi
    sleep 0.5
  done

  if ! $chrome_ready; then
    echo "Error: Chrome failed to start on port $CHROME_DEBUG_PORT"
    echo "Check logs: $CHROME_LOG_FILE"
    tail -20 "$CHROME_LOG_FILE"
    exit 1
  fi
fi

docker_args=(
  --rm -it --init
  --name "$container_name"
  -v "$(pwd):/workspaces/${project_name}"
  -w "/workspaces/${project_name}"
  -v claude-sandbox:/home/claude/persist
  -v "$(pwd)/.claude/sessions:/home/claude/persist/.claude/projects/-workspaces-${project_name}"
  -e TERM=xterm-256color
  --add-host=host.docker.internal:host-gateway
)

# Pass git identity env vars if configured
if [ -n "$GIT_AUTHOR_NAME" ]; then
  docker_args+=(-e "GIT_AUTHOR_NAME=$GIT_AUTHOR_NAME")
  docker_args+=(-e "GIT_COMMITTER_NAME=$GIT_AUTHOR_NAME")
fi
if [ -n "$GIT_AUTHOR_EMAIL" ]; then
  docker_args+=(-e "GIT_AUTHOR_EMAIL=$GIT_AUTHOR_EMAIL")
  docker_args+=(-e "GIT_COMMITTER_EMAIL=$GIT_AUTHOR_EMAIL")
fi
if [ "$GPG_SIGNING" = "true" ]; then
  docker_args+=(-e "GPG_SIGNING=true")
fi

# Mount Chrome log if configured (allows agent to access logs even if Chrome started later)
if [ -n "$CHROME_LOG_FILE" ]; then
  touch "$CHROME_LOG_FILE"
  docker_args+=(
    -e CHROME_LOG=/tmp/chrome-debug.log
    -v "$CHROME_LOG_FILE:/tmp/chrome-debug.log:ro"
  )
fi

# Add port mappings if specified
for port in "${ports[@]}"; do
  docker_args+=(-p "$port:$port")
done
if [ ${#ports[@]} -gt 0 ]; then
  port_list=$(IFS=,; echo "${ports[*]}")
  docker_args+=(-e "EXPOSED_PORTS=$port_list")
fi

if $firewalled; then
  docker_args+=(--cap-add=NET_ADMIN -e ENABLE_FIREWALL=1)
fi

# Run container detached, then attach interactively.
# A watchdog process monitors this script's PID and stops the container if the
# script dies (e.g., terminal window closed). This is necessary because closing
# a terminal kills the shell before traps can fire, leaving the container orphaned.
#
# The watchdog ignores SIGHUP and is disowned from bash's job table, so it
# survives terminal close on both macOS and Linux.

docker run -d "${docker_args[@]}" local/claude-sandbox $yolo_flag "${args[@]}" >/dev/null

# Spawn watchdog immune to SIGHUP
( trap '' HUP
  while kill -0 $$ 2>/dev/null; do sleep 1; done
  docker stop "$container_name" 2>/dev/null || true
) &
disown $!

docker attach "$container_name" || true
docker stop "$container_name" 2>/dev/null || true
