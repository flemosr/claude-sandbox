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
  local firewalled=false
  local args=()

  for arg in "$@"; do
    case "$arg" in
      --yolo)
        yolo_flag="--dangerously-skip-permissions"
        ;;
      --firewalled)
        firewalled=true
        ;;
      *)
        args+=("$arg")
        ;;
    esac
  done

  local docker_args=(
    --rm -it
    -v "$(pwd):/home/claude/workspace"
    -v claude-sandbox-config:/home/claude/.claude
    -e TERM=xterm-256color
  )

  if $firewalled; then
    docker_args+=(--cap-add=NET_ADMIN -e ENABLE_FIREWALL=1 --user root)
    docker run "${docker_args[@]}" local/claude-sandbox \
      /opt/entrypoint.sh $yolo_flag "${args[@]}"
  else
    docker run "${docker_args[@]}" local/claude-sandbox \
      claude $yolo_flag "${args[@]}"
  fi
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

# Firewalled mode (restricted network access)
claude-sandbox --firewalled

# YOLO + firewalled (maximum isolation)
claude-sandbox --yolo --firewalled

# With a prompt
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

## Network restrictions

Use the `--firewalled` flag to restrict network access to essential domains only:

- Anthropic API (api.anthropic.com, claude.ai)
- JavaScript/TypeScript (npm, Yarn, nodejs.org)
- Rust (crates.io, docs.rs, rust-lang.org)
- GitHub

This prevents data exfiltration to unauthorized servers while still allowing Claude to fetch docs and install packages.
