# Claude Code Sandbox

A Docker-based sandbox environment for running Claude Code safely in YOLO mode.

## Prerequisites

- Docker installed and running
- macOS (or Linux/WSL2)

## Setup

### 1. Build the sandbox image

```bash
docker compose build
```

### 2. Add the shell alias

Add this function to your `~/.zshrc`:

```bash
# Claude Code Sandbox - runs in Docker with current directory mounted
claude-sandbox() {
  local yolo_flag=""
  local args=()

  for arg in "$@"; do
    if [[ "$arg" == "--yolo" ]]; then
      yolo_flag="--dangerously-skip-permissions"
    else
      args+=("$arg")
    fi
  done

  docker run --rm -it \
    -v "$(pwd):/home/claude/workspace" \
    -v claude-sandbox-config:/home/claude/.claude \
    -e TERM=xterm-256color \
    local/claude-sandbox \
    claude $yolo_flag "${args[@]}"
}
```

Then reload your shell:

```bash
source ~/.zshrc
```

### 3. Authenticate (first time only)

Run the sandbox once to authenticate with your Anthropic account:

```bash
claude-sandbox
```

## Usage

Navigate to any project directory and run:

```bash
# Normal mode
claude-sandbox

# YOLO mode (no permission prompts)
claude-sandbox --yolo

# YOLO mode with a prompt
claude-sandbox --yolo -p "fix the tests"

# Pass any claude arguments
claude-sandbox --resume
```

## How it works

- Your current directory is mounted at `/home/claude/workspace` inside the container
- Claude Code settings persist between sessions via Docker volumes
- The container runs as non-root user `claude` for safety
- Full network access is available (for web searches, docs, git, etc.)
- Filesystem access is isolated to the mounted directory

## Optional: Network restrictions

If you want to restrict network access to only essential domains, uncomment the `cap_add` section in `docker-compose.yml` and run `init-firewall.sh` on container startup.
