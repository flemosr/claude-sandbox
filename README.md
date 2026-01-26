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

Add this to your `~/.zshrc`:

```bash
alias claude-sandbox="/path/to/claude-sandbox/run_sandbox.sh"
```

Replace `/path/to/claude-sandbox` with the actual path to this repository.

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

- Your current directory is mounted at `/workspaces/<project-name>` inside the container
- Each project gets a unique path so Claude Code keeps chat histories separate
- Claude Code settings persist between sessions via Docker volumes
- The container runs as non-root user `claude` for safety
- Full network access is available (for web searches, docs, git, etc.)
- Filesystem access is isolated to the mounted directory
- Host services are accessible via `host.docker.internal` (e.g., `host.docker.internal:5432` for a local PostgreSQL)

## Network restrictions

Use the `--firewalled` flag to restrict network access to essential domains only:

- Anthropic API (api.anthropic.com, claude.ai)
- JavaScript/TypeScript (npm, Yarn, nodejs.org)
- Rust (crates.io, docs.rs, rust-lang.org)
- GitHub

This prevents data exfiltration to unauthorized servers while still allowing Claude to fetch docs and install packages.

## Project structure

```
claude-sandbox/
├── README.md
├── docker-compose.yml
├── run_sandbox.sh          # Main entry point script
└── sandbox/
    ├── Dockerfile
    ├── entrypoint.sh
    └── init-firewall.sh
```
