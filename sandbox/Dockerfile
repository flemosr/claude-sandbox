# Agent Workcell Environment
# Based on official devcontainer: https://github.com/anthropics/claude-code/tree/main/.devcontainer
FROM debian:bookworm

# Install development tools and security packages
RUN apt-get update && apt-get install -y \
    bubblewrap \
    git \
    curl \
    wget \
    vim \
    jq \
    ripgrep \
    fd-find \
    build-essential \
    pkg-config \
    libssl-dev \
    zsh \
    fzf \
    iptables \
    iproute2 \
    dnsutils \
    ca-certificates \
    procps \
    psmisc \
    lsof \
    python3 \
    python3-pip \
    python3-venv \
    unzip \
    strace \
    gnupg \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install yq (YAML processor) - detect architecture
RUN ARCH=$(dpkg --print-architecture) && \
    curl -fsSL "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_${ARCH}" -o /usr/local/bin/yq && \
    chmod +x /usr/local/bin/yq

# Create a non-root user for safety
RUN useradd -m -s /bin/bash agent \
    && mkdir -p /home/agent/.local/bin \
    && chown -R agent:agent /home/agent

# Switch to agent user for tool installation
USER agent
WORKDIR /home/agent

# Install Rust stable
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable

# Install nvm and Node.js LTS
ENV NVM_DIR="/home/agent/.nvm"
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install --lts \
    && nvm use --lts \
    && nvm alias default lts/* \
    && ln -sf "$NVM_DIR/versions/node/$(nvm current)" "$NVM_DIR/current"

# Install Claude Code using the official native installer
RUN curl -fsSL https://claude.ai/install.sh | bash

# Prefer image-baked tools over volume-backed npm globals on PATH.
# Activate Python venv globally so all packages are available via `python3`.
ENV PATH="/home/agent/.local/python-venv/bin:/home/agent/.local/bin:/home/agent/.nvm/current/bin:/home/agent/.cargo/bin:${PATH}"
ENV VIRTUAL_ENV="/home/agent/.local/python-venv"

# Install Python packages: browser tools (Playwright), linters (pyright, ruff),
# and data science libraries (matplotlib, numpy)
RUN python3 -m venv ~/.local/python-venv && \
    ~/.local/python-venv/bin/pip install playwright pyright ruff matplotlib numpy

# Copy browser tools
COPY --chown=agent:agent browser-tools/ /home/agent/.local/browser-tools/
RUN chmod +x /home/agent/.local/browser-tools/browser.sh && \
    ln -sf /home/agent/.local/browser-tools/browser.sh /home/agent/.local/bin/browser

# Copy flutter tools
COPY --chown=agent:agent flutter-tools/ /home/agent/.local/flutter-tools/
RUN chmod +x /home/agent/.local/flutter-tools/flutterctl.sh && \
    ln -sf /home/agent/.local/flutter-tools/flutterctl.sh /home/agent/.local/bin/flutterctl

# Install opencode using the official installer.
# Placed after the Python venv so frequent opencode releases don't invalidate
# the heavier venv layer's cache.
# The installer ignores XDG_BIN_DIR and always drops the binary at
# ~/.opencode/bin/opencode, so we symlink it into ~/.local/bin (alongside claude).
RUN curl -fsSL https://opencode.ai/install | bash \
    && ln -sf /home/agent/.opencode/bin/opencode /home/agent/.local/bin/opencode

# Install Codex CLI from the official GitHub release (standalone musl binary).
# The ADD URL below acts as the layer's cache key: its response changes when a
# new release is published, so `docker compose build` picks up new Codex
# versions automatically without --no-cache or a version bump.
ADD --chown=agent:agent https://api.github.com/repos/openai/codex/releases/latest /tmp/codex-release.json
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
        amd64) CODEX_ARCH="x86_64-unknown-linux-musl" ;; \
        arm64) CODEX_ARCH="aarch64-unknown-linux-musl" ;; \
        *) echo "Unsupported architecture for codex: $ARCH" >&2; exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/openai/codex/releases/latest/download/codex-${CODEX_ARCH}.tar.gz" \
        -o /tmp/codex.tar.gz && \
    tar -xzf /tmp/codex.tar.gz -C /tmp && \
    install -m 0755 "/tmp/codex-${CODEX_ARCH}" /home/agent/.local/bin/codex && \
    rm -f /tmp/codex.tar.gz /tmp/codex-release.json "/tmp/codex-${CODEX_ARCH}"

# Create persistent volume directory structure
# All persistent data goes in persist which is mounted from a single Docker volume
RUN mkdir -p /home/agent/persist/.claude

# Move installer-created files to volume location
RUN mv /home/agent/.claude.json /home/agent/persist/.claude.json 2>/dev/null || true \
    && mv /home/agent/.claude/* /home/agent/persist/.claude/ 2>/dev/null || true

# Remove original directory and create symlinks to volume
RUN rm -rf /home/agent/.claude \
    && ln -sf /home/agent/persist/.claude /home/agent/.claude \
    && ln -sf /home/agent/persist/.claude.json /home/agent/.claude.json

# Set up persistence for Claude Code binary versions (~/.local/share/claude)
# This prevents re-downloading Claude Code updates on every container restart
RUN mv /home/agent/.local/share/claude /home/agent/persist/.claude-versions 2>/dev/null || true \
    && ln -sf /home/agent/persist/.claude-versions /home/agent/.local/share/claude

# Set up persistence for opencode data (~/.local/share/opencode), config
# (~/.config/opencode), and local UI state (~/.local/state/opencode).
# Mirrors the claude pattern: move any installer-created content into the persist tree,
# then symlink the expected locations into it.
RUN mkdir -p /home/agent/persist/.local/share /home/agent/persist/.local/state /home/agent/persist/.config \
    && mv /home/agent/.local/share/opencode /home/agent/persist/.local/share/opencode 2>/dev/null || true \
    && mv /home/agent/.config/opencode /home/agent/persist/.config/opencode 2>/dev/null || true \
    && mv /home/agent/.local/state/opencode /home/agent/persist/.local/state/opencode 2>/dev/null || true \
    && mkdir -p /home/agent/persist/.local/share/opencode /home/agent/persist/.local/state/opencode /home/agent/persist/.config/opencode \
    && mkdir -p /home/agent/.local/share /home/agent/.local/state /home/agent/.config \
    && rm -rf /home/agent/.local/share/opencode /home/agent/.local/state/opencode /home/agent/.config/opencode \
    && ln -sf /home/agent/persist/.local/share/opencode /home/agent/.local/share/opencode \
    && ln -sf /home/agent/persist/.local/state/opencode /home/agent/.local/state/opencode \
    && ln -sf /home/agent/persist/.config/opencode /home/agent/.config/opencode

# Set up persistence for Codex data (~/.codex).
# Codex stores config, auth, sessions, history, and logs under its home
# directory, but it only creates that directory on first use — nothing is
# baked in at build time. We bake in the symlink so the agent user has
# ~/.codex -> ~/persist/.codex ready before the entrypoint runs; the
# entrypoint remains authoritative and re-applies this idempotently.
RUN mkdir -p /home/agent/persist/.codex \
    && ln -sf /home/agent/persist/.codex /home/agent/.codex

# Backup nvm, Rust, Claude Code, and OpenCode install data to template
# locations for volume initialization.
# This allows the entrypoint to seed the persistent volume on first run
USER root
RUN cp -a /home/agent/.nvm /opt/nvm-template \
    && cp -a /home/agent/.rustup /opt/rustup-template \
    && cp -a /home/agent/.cargo /opt/cargo-template \
    && cp -a /home/agent/persist/.claude-versions /opt/claude-versions-template \
    && cp -a /home/agent/.opencode /opt/opencode-template
USER agent

# Copy firewall and entrypoint scripts (after installs to preserve cache)
USER root

# Create workspaces directory with proper permissions
RUN mkdir -p /workspaces && chown agent:agent /workspaces

COPY init-firewall.sh /opt/init-firewall.sh
COPY entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/init-firewall.sh /opt/entrypoint.sh

# Copy global context files to non-volume locations (source of truth for entrypoint)
COPY agent-context.md /opt/agent-context.md
COPY agent-context-web.md /opt/agent-context-web.md
COPY agent-context-flutter.md /opt/agent-context-flutter.md

# Run as root by default so entrypoint can set up firewall if needed
# Entrypoint drops privileges to the agent user for running the agent CLI
WORKDIR /workspaces

ENTRYPOINT ["/opt/entrypoint.sh"]
CMD []
