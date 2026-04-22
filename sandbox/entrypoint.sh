#!/bin/bash
# Entrypoint script for Agent Sandbox

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

# Initialize Rust toolchain in persistent volume if empty (first run)
if [ ! -d /home/claude/persist/.rustup/toolchains ]; then
  echo "Initializing Rust toolchain in persistent volume..."
  cp -a /opt/rustup-template /home/claude/persist/.rustup
  cp -a /opt/cargo-template /home/claude/persist/.cargo
  chown -R claude:claude /home/claude/persist/.rustup /home/claude/persist/.cargo
fi

# Ensure rustup symlink exists (handles both first run and image updates)
if [ -d /home/claude/.rustup ] && [ ! -L /home/claude/.rustup ]; then
  rm -rf /home/claude/.rustup
fi
ln -sfn /home/claude/persist/.rustup /home/claude/.rustup

# Ensure cargo symlink exists
if [ -d /home/claude/.cargo ] && [ ! -L /home/claude/.cargo ]; then
  rm -rf /home/claude/.cargo
fi
ln -sfn /home/claude/persist/.cargo /home/claude/.cargo

# Initialize Claude Code versions in persistent volume if empty (first run)
# This prevents re-downloading Claude Code updates on every container restart
if [ ! -d /home/claude/persist/.claude-versions/versions ]; then
  echo "Initializing Claude Code versions in persistent volume..."
  cp -a /opt/claude-versions-template /home/claude/persist/.claude-versions
  chown -R claude:claude /home/claude/persist/.claude-versions
fi

# Ensure Claude Code versions symlink exists (handles both first run and image updates)
mkdir -p /home/claude/.local/share
if [ -d /home/claude/.local/share/claude ] && [ ! -L /home/claude/.local/share/claude ]; then
  rm -rf /home/claude/.local/share/claude
fi
ln -sfn /home/claude/persist/.claude-versions /home/claude/.local/share/claude

# Update claude binary symlink to point to the persisted version
# (handles image rebuild where baked-in version differs from persisted version)
if [ -d /home/claude/.local/share/claude/versions ]; then
  latest_claude=$(ls -1 /home/claude/.local/share/claude/versions | sort -V | tail -1)
  if [ -n "$latest_claude" ]; then
    ln -sfn "/home/claude/.local/share/claude/versions/$latest_claude" /home/claude/.local/bin/claude
  fi
fi

# Initialize .gnupg in persistent volume if missing (first run)
if [ ! -d /home/claude/persist/.gnupg ]; then
  mkdir -p /home/claude/persist/.gnupg
  chmod 700 /home/claude/persist/.gnupg
  chown claude:claude /home/claude/persist/.gnupg
fi

# Ensure gnupg symlink exists
if [ -d /home/claude/.gnupg ] && [ ! -L /home/claude/.gnupg ]; then
  rm -rf /home/claude/.gnupg
fi
ln -sfn /home/claude/persist/.gnupg /home/claude/.gnupg

# GPG commit signing setup
if [ "$GPG_SIGNING" = "true" ] && [ -n "$GIT_AUTHOR_NAME" ] && [ -n "$GIT_AUTHOR_EMAIL" ]; then
  # Check if a key already exists
  existing_email=$(runuser -u claude -- gpg --list-keys --with-colons 2>/dev/null | grep '^uid' | head -1 | cut -d: -f10 | grep -oP '<\K[^>]+')

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
        rm -rf /home/claude/persist/.gnupg/*
        ;;
      *)
        echo "Aborting."
        exit 1
        ;;
    esac
  fi

  # Generate key if none exists
  if ! runuser -u claude -- gpg --list-keys "$GIT_AUTHOR_EMAIL" &>/dev/null; then
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
    runuser -u claude -- gpg --batch --gen-key <<GPGEOF
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
    runuser -u claude -- gpg --armor --export "$GIT_AUTHOR_EMAIL"
    echo "==================================================================="
    echo ""
  fi

  # Configure git to sign commits
  key_id=$(runuser -u claude -- gpg --list-keys --keyid-format long "$GIT_AUTHOR_EMAIL" 2>/dev/null | grep -oP '(?<=ed25519/)[A-F0-9]+' | head -1)
  if [ -n "$key_id" ]; then
    runuser -u claude -- git config --global user.signingKey "$key_id"
    runuser -u claude -- git config --global commit.gpgSign true
    runuser -u claude -- git config --global tag.gpgSign true
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

# Blank line to separate init logs from the Claude Code TUI
echo

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
