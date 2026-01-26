#!/bin/bash
# Entrypoint script for Claude Code sandbox

# If ENABLE_FIREWALL is set, configure network restrictions
if [[ "$ENABLE_FIREWALL" == "1" ]]; then
  echo "Configuring firewall..."
  /opt/init-firewall.sh
fi

# Run claude as the claude user
exec su claude -c "cd /home/claude/workspace && claude $*"
