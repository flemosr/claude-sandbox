#!/bin/bash
# Entrypoint script for Agent Sandbox

# Always sync CLAUDE.md from image to persist volume (ensures freshness).
# Also write AGENTS.md for opencode (same content, opencode's native convention).
mkdir -p /home/agent/persist/.claude
cp /opt/agent-context.md /home/agent/persist/.claude/CLAUDE.md
chown -R agent:agent /home/agent/persist/.claude 2>/dev/null || true

mkdir -p /home/agent/persist/.config/opencode
cp /opt/agent-context.md /home/agent/persist/.config/opencode/AGENTS.md
chown -R agent:agent /home/agent/persist/.config/opencode 2>/dev/null || true

# Initialize nvm in persistent volume if empty (first run)
if [ ! -d /home/agent/persist/.nvm/versions ]; then
  echo "Initializing nvm in persistent volume..."
  cp -a --no-target-directory /opt/nvm-template /home/agent/persist/.nvm
  chown -R agent:agent /home/agent/persist/.nvm
fi

# Ensure nvm symlink exists (handles both first run and image updates)
if [ -d /home/agent/.nvm ] && [ ! -L /home/agent/.nvm ]; then
  rm -rf /home/agent/.nvm
fi
ln -sfn /home/agent/persist/.nvm /home/agent/.nvm

# Update the "current" symlink to point to the actual node version
if [ -d /home/agent/.nvm/versions/node ]; then
  latest_node=$(ls -1 /home/agent/.nvm/versions/node | tail -1)
  if [ -n "$latest_node" ]; then
    ln -sfn "/home/agent/.nvm/versions/node/$latest_node" /home/agent/.nvm/current
  fi
fi

# Initialize Rust toolchain in persistent volume if empty (first run)
if [ ! -d /home/agent/persist/.rustup/toolchains ]; then
  echo "Initializing Rust toolchain in persistent volume..."
  cp -a --no-target-directory /opt/rustup-template /home/agent/persist/.rustup
  cp -a --no-target-directory /opt/cargo-template /home/agent/persist/.cargo
  chown -R agent:agent /home/agent/persist/.rustup /home/agent/persist/.cargo
fi

# Ensure rustup symlink exists (handles both first run and image updates)
if [ -d /home/agent/.rustup ] && [ ! -L /home/agent/.rustup ]; then
  rm -rf /home/agent/.rustup
fi
ln -sfn /home/agent/persist/.rustup /home/agent/.rustup

# Ensure cargo symlink exists
if [ -d /home/agent/.cargo ] && [ ! -L /home/agent/.cargo ]; then
  rm -rf /home/agent/.cargo
fi
ln -sfn /home/agent/persist/.cargo /home/agent/.cargo

# Initialize Claude Code versions in persistent volume if empty (first run)
# This prevents re-downloading Claude Code updates on every container restart
if [ ! -d /home/agent/persist/.claude-versions/versions ]; then
  echo "Initializing Claude Code versions in persistent volume..."
  # Use cp --no-target-directory so that if .claude-versions already exists
  # (e.g. after a volume cleanup) the contents are merged instead of creating
  # a nested subdirectory.
  cp -a --no-target-directory /opt/claude-versions-template /home/agent/persist/.claude-versions
  chown -R agent:agent /home/agent/persist/.claude-versions
fi

# Ensure Claude Code versions symlink exists (handles both first run and image updates)
mkdir -p /home/agent/.local/share
if [ -d /home/agent/.local/share/claude ] && [ ! -L /home/agent/.local/share/claude ]; then
  rm -rf /home/agent/.local/share/claude
fi
ln -sfn /home/agent/persist/.claude-versions /home/agent/.local/share/claude

# Update claude binary symlink to point to the persisted version
# (handles image rebuild where baked-in version differs from persisted version)
if [ -d /home/agent/.local/share/claude/versions ]; then
  latest_claude=$(ls -1 /home/agent/.local/share/claude/versions | sort -V | tail -1)
  if [ -n "$latest_claude" ]; then
    ln -sfn "/home/agent/.local/share/claude/versions/$latest_claude" /home/agent/.local/bin/claude
  fi
fi

# Initialize opencode install home in persistent volume if missing (first run)
# This preserves the installer-managed binary and any upgrades across restarts.
if [ ! -d /home/agent/persist/.opencode ]; then
  echo "Initializing opencode install in persistent volume..."
  cp -a --no-target-directory /opt/opencode-template /home/agent/persist/.opencode
  chown -R agent:agent /home/agent/persist/.opencode
fi

# Initialize opencode persist dirs if missing (first run only — avoids a wasteful
# chown -R over accumulated session data on every container start)
for opencode_dir in \
    /home/agent/persist/.local/share/opencode \
    /home/agent/persist/.local/state/opencode \
    /home/agent/persist/.config/opencode; do
  if [ ! -d "$opencode_dir" ]; then
    mkdir -p "$opencode_dir"
    chown agent:agent "$opencode_dir"
  fi
done

# Ensure opencode symlinks exist (idempotent; handles first run and image rebuilds)
if [ -d /home/agent/.opencode ] && [ ! -L /home/agent/.opencode ]; then
  rm -rf /home/agent/.opencode
fi
ln -sfn /home/agent/persist/.opencode /home/agent/.opencode

mkdir -p /home/agent/.local/share /home/agent/.local/state /home/agent/.config
if [ -d /home/agent/.local/share/opencode ] && [ ! -L /home/agent/.local/share/opencode ]; then
  rm -rf /home/agent/.local/share/opencode
fi
ln -sfn /home/agent/persist/.local/share/opencode /home/agent/.local/share/opencode

if [ -d /home/agent/.local/state/opencode ] && [ ! -L /home/agent/.local/state/opencode ]; then
  rm -rf /home/agent/.local/state/opencode
fi
ln -sfn /home/agent/persist/.local/state/opencode /home/agent/.local/state/opencode

if [ -d /home/agent/.config/opencode ] && [ ! -L /home/agent/.config/opencode ]; then
  rm -rf /home/agent/.config/opencode
fi
ln -sfn /home/agent/persist/.config/opencode /home/agent/.config/opencode

# Initialize .gnupg in persistent volume if missing (first run)
if [ ! -d /home/agent/persist/.gnupg ]; then
  mkdir -p /home/agent/persist/.gnupg
  chmod 700 /home/agent/persist/.gnupg
  chown agent:agent /home/agent/persist/.gnupg
fi

# Ensure gnupg symlink exists
if [ -d /home/agent/.gnupg ] && [ ! -L /home/agent/.gnupg ]; then
  rm -rf /home/agent/.gnupg
fi
ln -sfn /home/agent/persist/.gnupg /home/agent/.gnupg

# GPG commit signing setup
if [ "$GPG_SIGNING" = "true" ] && [ -n "$GIT_AUTHOR_NAME" ] && [ -n "$GIT_AUTHOR_EMAIL" ]; then
  # Check if a key already exists
  existing_email=$(runuser -u agent -- gpg --list-keys --with-colons 2>/dev/null | grep '^uid' | head -1 | cut -d: -f10 | grep -oP '<\K[^>]+')

  if [ -n "$existing_email" ] && [ "$existing_email" != "$GIT_AUTHOR_EMAIL" ]; then
    # Identity mismatch — stop and let user decide
    echo ""
    echo "ERROR: GPG key identity mismatch!"
    echo "  Existing key: $existing_email"
    echo "  Config email:  $GIT_AUTHOR_EMAIL"
    echo ""
    echo "The existing GPG key does not match your configured identity."
    echo "To back up your current key, run on the host:"
    echo "  agent-sandbox gpg-export --file gpg-key-backup.asc"
    echo ""
    echo "This creates the specified file in your current directory."
    echo "WARNING: This file contains your PRIVATE key. Do not commit or share it."
    echo ""
    echo "Options:"
    echo "  [r] Regenerate key (deletes existing key)"
    echo "  [a] Abort"
    echo ""
    read -r -p "Choice [r/a]: " choice
    case "$choice" in
      r|R)
        echo "Deleting existing GPG keys..."
        rm -rf /home/agent/persist/.gnupg/*
        ;;
      *)
        echo "Aborting."
        exit 1
        ;;
    esac
  fi

  # Generate key if none exists
  if ! runuser -u agent -- gpg --list-keys "$GIT_AUTHOR_EMAIL" &>/dev/null; then
    echo ""
    echo "GPG_SIGNING is enabled but no key was found for $GIT_AUTHOR_NAME <$GIT_AUTHOR_EMAIL>."
    echo "A new ed25519 signing key will be generated (passphrase-less)."
    echo ""
    echo "Options:"
    echo "  [g] Generate new key"
    echo "  [a] Abort"
    echo ""
    read -r -p "Choice [g/a]: " choice
    case "$choice" in
      g|G) ;;
      *)
        echo "Aborting."
        exit 1
        ;;
    esac

    echo "Generating GPG signing key..."
    runuser -u agent -- gpg --batch --gen-key <<GPGEOF
%no-protection
Key-Type: eddsa
Key-Curve: ed25519
Name-Real: $GIT_AUTHOR_NAME
Name-Email: $GIT_AUTHOR_EMAIL
Expire-Date: 0
%commit
GPGEOF
    # Print public key for GitHub registration
    echo ""
    echo "=== GPG Public Key (add to GitHub → Settings → SSH and GPG keys) ==="
    runuser -u agent -- gpg --armor --export "$GIT_AUTHOR_EMAIL"
    echo "==================================================================="
    echo ""
  fi

  # Configure git to sign commits
  key_id=$(runuser -u agent -- gpg --list-keys --keyid-format long "$GIT_AUTHOR_EMAIL" 2>/dev/null | grep -oP '(?<=ed25519/)[A-F0-9]+' | head -1)
  if [ -n "$key_id" ]; then
    runuser -u agent -- git config --global user.signingKey "$key_id"
    runuser -u agent -- git config --global commit.gpgSign true
    runuser -u agent -- git config --global tag.gpgSign true
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

# Blank line to separate init logs from the agent TUI
echo

# Dispatch to the selected agent CLI.
# AGENT_CLI is set by the host runner (run_sandbox.sh); defaults to claude.
agent_cli="${AGENT_CLI:-claude}"
case "$agent_cli" in
  claude|opencode) ;;
  *)
    echo "Error: unknown AGENT_CLI '$agent_cli' (expected 'claude' or 'opencode')" >&2
    exit 1
    ;;
esac

# Run the agent as the agent user in the current working directory.
# `runuser -m` preserves the environment so vars like OPENCODE_CONFIG_CONTENT
# (used to inject opencode's "permission: allow" for --yolo) cross the boundary.
# `env …` re-sets HOME/USER/LOGNAME because -m also preserves those from root,
# which would make the agent look up config under the wrong user.
# cwd is inherited naturally (runuser doesn't chdir unless --login is passed).
if [[ "$(id -u)" == "0" ]]; then
  exec runuser -m -u agent -- \
    env HOME=/home/agent USER=agent LOGNAME=agent "$agent_cli" "$@"
else
  exec "$agent_cli" "$@"
fi
