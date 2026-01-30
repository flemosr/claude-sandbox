#!/bin/bash
# Entrypoint script for Claude Code sandbox

# Always sync CLAUDE.md from image to persist volume (ensures freshness)
mkdir -p /home/claude/persist/.claude
cp /opt/agent-context.md /home/claude/persist/.claude/CLAUDE.md
chown -R claude:claude /home/claude/persist/.claude 2>/dev/null || true

# Initialize nvm in persistent volume if empty (first run)
if [ ! -d /home/claude/persist/.nvm/versions ]; then
  echo "Initializing nvm in persistent volume..."
  cp -a /opt/nvm-template /home/claude/persist/.nvm
  chown -R claude:claude /home/claude/persist/.nvm
fi

# Ensure nvm symlink exists (handles both first run and image updates)
if [ -d /home/claude/.nvm ] && [ ! -L /home/claude/.nvm ]; then
  rm -rf /home/claude/.nvm
fi
ln -sfn /home/claude/persist/.nvm /home/claude/.nvm

# Update the "current" symlink to point to the actual node version
if [ -d /home/claude/.nvm/versions/node ]; then
  latest_node=$(ls -1 /home/claude/.nvm/versions/node | tail -1)
  if [ -n "$latest_node" ]; then
    ln -sfn "/home/claude/.nvm/versions/node/$latest_node" /home/claude/.nvm/current
  fi
fi

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
