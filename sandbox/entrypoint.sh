#!/bin/bash
# Entrypoint script for Claude Code sandbox

# Always sync CLAUDE.md from image to persist volume (ensures freshness)
mkdir -p /home/claude/persist/.claude
cp /opt/agent-context.md /home/claude/persist/.claude/CLAUDE.md
chown -R claude:claude /home/claude/persist/.claude 2>/dev/null || true

# If ENABLE_FIREWALL is set, configure network restrictions (requires root)
if [[ "$ENABLE_FIREWALL" == "1" ]]; then
  if [[ "$(id -u)" != "0" ]]; then
    echo "Error: Firewall requested but not running as root. Container must run as root to configure iptables." >&2
    exit 1
  fi
  echo "Configuring firewall..."
  /opt/init-firewall.sh
fi

# Run claude as the claude user in the current working directory
if [[ "$(id -u)" == "0" ]]; then
  # Build argument string for passing through bash -c
  args=""
  for arg in "$@"; do
    args="$args \"$arg\""
  done
  exec runuser -u claude -- bash -c "cd $(pwd) && exec claude $args"
else
  exec claude "$@"
fi
