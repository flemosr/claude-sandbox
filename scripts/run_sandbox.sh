#!/bin/bash
# Agent Workcell - runs in Docker with current directory mounted

set -e

WORKCELL_DIR_NAME=".workcell"
WORKCELL_VOLUME_NAME="agent-workcell"
WORKCELL_IMAGE_NAME="local/agent-workcell"

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# First positional arg selects the agent CLI. Defaults to `claude` for backwards compatibility.
agent_cli="claude"
if [[ $# -gt 0 ]] && [[ "$1" != -* ]]; then
  agent_cli="$1"
  shift
fi
case "$agent_cli" in
  claude|opencode|codex) ;;
  *)
    echo "Error: unknown agent '$agent_cli' (expected 'claude', 'opencode', or 'codex')" >&2
    exit 1
    ;;
esac

yolo=false
firewalled=false
chrome_enabled=false
flutter_enabled=false
ports=()
args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yolo)
      yolo=true
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
    --with-flutter)
      flutter_enabled=true
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

if $chrome_enabled && $flutter_enabled; then
  echo "Error: --with-chrome and --with-flutter are mutually exclusive."
  echo "Use --with-chrome for web targets or --with-flutter for native/device targets."
  exit 1
fi

if $flutter_enabled && [ ${#ports[@]} -gt 1 ]; then
  echo "Error: --with-flutter accepts at most one --port value for the bridge."
  exit 1
fi

# Per-agent yolo mapping.
# claude supports a CLI flag directly; opencode has no equivalent flag for its TUI, so we
# inject `{"permission": "allow"}` via OPENCODE_CONFIG_CONTENT (precedence slot #6 in
# opencode's config chain — won't clobber the user's project or global config).
# codex exposes --dangerously-bypass-approvals-and-sandbox for YOLO mode.
yolo_flag=""
yolo_env=()
if $yolo; then
  case "$agent_cli" in
    claude)   yolo_flag="--dangerously-skip-permissions" ;;
    opencode) yolo_env+=(-e 'OPENCODE_CONFIG_CONTENT={"permission":"allow"}') ;;
    codex)    yolo_flag="--dangerously-bypass-approvals-and-sandbox" ;;
  esac
fi

project_name="${PWD##*/}"
workspace_root="$(pwd)"
workspace_workcell_dir="${workspace_root}/${WORKCELL_DIR_NAME}"
artifacts_dir="${workspace_workcell_dir}/artifacts"
tasks_dir="${workspace_workcell_dir}/tasks"
workcell_gitignore="${workspace_workcell_dir}/.gitignore"
session_mount_args=()

mkdir -p "$workspace_workcell_dir" "$artifacts_dir" "$tasks_dir"
# Seed project-local ignores once for generated workcell artifacts and runtime config.
# Do not overwrite the file because users may intentionally version task notes or sessions.
if [ ! -e "$workcell_gitignore" ]; then
  printf '.DS_Store\nflutter-config.json\nartifacts/\n' > "$workcell_gitignore"
fi

case "$agent_cli" in
  claude)
    legacy_session_host_dir="${workspace_root}/.agent-sessions/claude"
    session_host_dir="${workspace_workcell_dir}/claude-sessions"
    if [ ! -e "$session_host_dir" ] && [ -d "$legacy_session_host_dir" ]; then
      mv "$legacy_session_host_dir" "$session_host_dir"
    fi
    mkdir -p "$session_host_dir"
    session_mount_args=(
      -v "${session_host_dir}:/home/agent/persist/.claude/projects/-workspaces-${project_name}"
    )
    ;;
  opencode)
    mkdir -p "${workspace_workcell_dir}/opencode-sessions"
    ;;
  codex)
    codex_session_dir="${workspace_workcell_dir}/codex-sessions"
    mkdir -p "${codex_session_dir}/sessions" "${codex_session_dir}/archived_sessions"
    # Codex's Linux sandbox protects a missing project-root `.codex` path by
    # masking it, which can leave behind a zero-byte read-only file on the host.
    # Pre-create the directory so the protected path already has the expected
    # shape and project-local Codex config remains possible.
    project_codex_dir="$(pwd)/.codex"
    if [ -f "$project_codex_dir" ] && [ ! -s "$project_codex_dir" ]; then
      rm -f "$project_codex_dir"
    fi
    if [ ! -e "$project_codex_dir" ]; then
      mkdir -p "$project_codex_dir"
    fi
    session_mount_args=(
      -v "${codex_session_dir}/sessions:/home/agent/persist/.codex/sessions"
      -v "${codex_session_dir}/archived_sessions:/home/agent/persist/.codex/archived_sessions"
    )
    ;;
esac

container_name="agent-workcell-$$"

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
  if $FLUTTER_BRIDGE_STARTED_BY_US && [ -n "$FLUTTER_BRIDGE_PID" ]; then
    echo "Stopping Flutter bridge..."
    kill $FLUTTER_BRIDGE_PID 2>/dev/null || true
    wait $FLUTTER_BRIDGE_PID 2>/dev/null || true
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

FLUTTER_BRIDGE_STARTED_BY_US=false
FLUTTER_BRIDGE_PID=""

# Start Flutter bridge if enabled
if $flutter_enabled; then
  # Validate config.sh exists and has required Flutter settings
  if [ ! -f "$REPO_ROOT/config.sh" ]; then
    echo "Error: Flutter integration requires config.sh"
    echo ""
    echo "Please create config.sh from the template:"
    echo ""
    echo "  cd $REPO_ROOT"
    echo "  cp config.template.sh config.sh"
    echo ""
    echo "Then edit config.sh with your Flutter settings."
    exit 1
  fi

  flutter_project_dir="$PWD"
  FLUTTER_BRIDGE_CONFIG_FILE="${workspace_workcell_dir}/flutter-config.json"
  flutter_config_port=$(python3 - "$FLUTTER_BRIDGE_CONFIG_FILE" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path) as f:
        config = json.load(f)
    port = config.get("port") if isinstance(config, dict) else None
except (FileNotFoundError, json.JSONDecodeError, OSError):
    port = None
if port:
    print(port)
PY
)
  if [ ${#ports[@]} -gt 0 ]; then
    FLUTTER_BRIDGE_PORT="${ports[0]}"
  elif [ -n "$flutter_config_port" ]; then
    FLUTTER_BRIDGE_PORT="$flutter_config_port"
  else
    FLUTTER_BRIDGE_PORT="${FLUTTER_DEFAULT_BRIDGE_PORT:-${FLUTTER_BRIDGE_PORT:-8765}}"
  fi
  flutter_target=$(python3 - "$FLUTTER_BRIDGE_CONFIG_FILE" <<'PY'
import json
import sys

path = sys.argv[1]
target = "lib/main.dart"
try:
    with open(path) as f:
        config = json.load(f)
    if isinstance(config, dict) and isinstance(config.get("target"), str) and config["target"]:
        target = config["target"]
except (FileNotFoundError, json.JSONDecodeError, OSError):
    pass
print(target)
PY
)
  flutter_run_args=$(python3 - "$FLUTTER_BRIDGE_CONFIG_FILE" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path) as f:
        config = json.load(f)
    run_args = config.get("run_args", []) if isinstance(config, dict) else []
except (FileNotFoundError, json.JSONDecodeError, OSError):
    run_args = []
if isinstance(run_args, list) and run_args:
    print(json.dumps([str(item) for item in run_args], separators=(",", ":")))
elif isinstance(run_args, str) and run_args:
    print(run_args)
PY
)

  if [ ! -f "$SCRIPT_DIR/start-flutter-bridge.sh" ]; then
    echo "Error: start-flutter-bridge.sh not found in $SCRIPT_DIR"
    exit 1
  fi

  # Generate a per-session token for this sandbox's bridge.
  if [ -z "$FLUTTER_BRIDGE_TOKEN" ]; then
    FLUTTER_BRIDGE_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || \
                           openssl rand -hex 16 2>/dev/null || \
                           od -vAn -N16 -tx1 /dev/urandom | tr -d ' \n')
  fi

  FLUTTER_BRIDGE_URL="http://host.docker.internal:${FLUTTER_BRIDGE_PORT}"

  # Check if port is in use
  if lsof -i :$FLUTTER_BRIDGE_PORT >/dev/null 2>&1; then
    echo "Error: Flutter bridge port $FLUTTER_BRIDGE_PORT is already in use."
    echo "If a bridge is already running, omit --with-flutter; flutterctl can read .workcell/flutter-config.json."
    exit 1
  fi

  echo "Starting Flutter bridge..."
  echo "  Project: $flutter_project_dir"
  echo "  Port: $FLUTTER_BRIDGE_PORT"
  echo "  Log: ${FLUTTER_BRIDGE_LOG_FILE:-/tmp/flutter-bridge.log}"

  # Start bridge as a background process with the per-session token.
  FLUTTER_BRIDGE_LOG_FILE="${FLUTTER_BRIDGE_LOG_FILE:-/tmp/flutter-bridge.log}"
  : > "$FLUTTER_BRIDGE_LOG_FILE"
  python3 "$SCRIPT_DIR/flutter-bridge.py" \
    --port "$FLUTTER_BRIDGE_PORT" \
    --host "0.0.0.0" \
    --project-dir "$flutter_project_dir" \
    --target "$flutter_target" \
    --flutter-path "${FLUTTER_PATH:-flutter}" \
    --token "$FLUTTER_BRIDGE_TOKEN" \
    --log-file "$FLUTTER_BRIDGE_LOG_FILE" \
    ${flutter_run_args:+--run-args "$flutter_run_args"} \
    >> "$FLUTTER_BRIDGE_LOG_FILE" 2>&1 &
  FLUTTER_BRIDGE_PID=$!
  FLUTTER_BRIDGE_STARTED_BY_US=true

  # Wait for bridge to be ready (up to 10s)
  echo "Waiting for Flutter bridge to be ready..."
  bridge_ready=false
  for _ in {1..20}; do
    if lsof -i :$FLUTTER_BRIDGE_PORT >/dev/null 2>&1; then
      bridge_ready=true
      echo "Flutter bridge is ready!"
      break
    fi
    if ! kill -0 $FLUTTER_BRIDGE_PID 2>/dev/null; then break; fi
    sleep 0.5
  done

  if ! $bridge_ready; then
    echo "Error: Flutter bridge failed to start on port $FLUTTER_BRIDGE_PORT"
    echo "Check logs: $FLUTTER_BRIDGE_LOG_FILE"
    tail -20 "$FLUTTER_BRIDGE_LOG_FILE"
    exit 1
  fi

  # Write bridge config to workspace .workcell/ so agents can discover it
  # without requiring the user to manually copy tokens/URLs. Writing on the
  # host side means it is immediately visible inside the mounted workspace.
  mkdir -p "${workspace_workcell_dir}"
  python3 - "$FLUTTER_BRIDGE_CONFIG_FILE" "$FLUTTER_BRIDGE_TOKEN" "$FLUTTER_BRIDGE_PORT" <<'PY'
import json
import sys

path, token, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
try:
    with open(path) as f:
        config = json.load(f)
    if not isinstance(config, dict):
        config = {}
except (FileNotFoundError, json.JSONDecodeError, OSError):
    config = {}
config["token"] = token
config["port"] = port
with open(path, "w") as f:
    json.dump(config, f, indent=4)
    f.write("\n")
PY
fi

docker_args=(
  --rm -it --init
  --name "$container_name"
  -v "${workspace_root}:/workspaces/${project_name}"
  -w "/workspaces/${project_name}"
  -v "${WORKCELL_VOLUME_NAME}:/home/agent/persist"
  -e TERM=xterm-256color
  -e "AGENT_CLI=${agent_cli}"
  --add-host=host.docker.internal:host-gateway
)

if [ ${#session_mount_args[@]} -gt 0 ]; then
  docker_args+=("${session_mount_args[@]}")
fi

if [ ${#yolo_env[@]} -gt 0 ]; then
  docker_args+=("${yolo_env[@]}")
fi

# Pass host timezone so git commits use local time instead of UTC
host_tz=""
if [ -L /etc/localtime ]; then
  host_tz=$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')
elif [ -f /etc/timezone ]; then
  host_tz=$(cat /etc/timezone)
fi
if [ -n "$host_tz" ]; then
  docker_args+=(-e "TZ=$host_tz")
fi

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

# Pass Flutter bridge env vars and mount log if enabled
if $flutter_enabled; then
  touch "${FLUTTER_BRIDGE_LOG_FILE:-/tmp/flutter-bridge.log}"
  docker_args+=(
    -e "FLUTTER_BRIDGE_URL=$FLUTTER_BRIDGE_URL"
    -e "FLUTTER_BRIDGE_TOKEN=$FLUTTER_BRIDGE_TOKEN"
    -e "FLUTTER_BRIDGE_LOG_FILE=/tmp/flutter-bridge.log"
    -v "${FLUTTER_BRIDGE_LOG_FILE:-/tmp/flutter-bridge.log}:/tmp/flutter-bridge.log:ro"
  )
fi

# Add port mappings if specified. In Flutter mode, --port selects the host
# bridge port and must not also bind a container port on the host.
if ! $flutter_enabled; then
  for port in "${ports[@]}"; do
    docker_args+=(-p "$port:$port")
  done
fi
if [ ${#ports[@]} -gt 0 ] && ! $flutter_enabled; then
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

docker run -d "${docker_args[@]}" "$WORKCELL_IMAGE_NAME" $yolo_flag "${args[@]}" >/dev/null

# Spawn watchdog immune to SIGHUP
( trap '' HUP
  while kill -0 $$ 2>/dev/null; do sleep 1; done
  docker stop "$container_name" 2>/dev/null || true
) &
disown $!

docker attach "$container_name" || true
docker stop "$container_name" 2>/dev/null || true
