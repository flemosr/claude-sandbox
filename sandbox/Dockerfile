# Agent Sandbox Environment
# Based on official devcontainer: https://github.com/anthropics/claude-code/tree/main/.devcontainer
FROM debian:bookworm

# Install development tools and security packages
RUN apt-get update && apt-get install -y \
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
RUN useradd -m -s /bin/bash claude \
    && mkdir -p /home/claude/.local/bin \
    && chown -R claude:claude /home/claude

# Switch to claude user for tool installation
USER claude
WORKDIR /home/claude

# Install Rust stable
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable

# Install nvm and Node.js LTS
ENV NVM_DIR="/home/claude/.nvm"
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install --lts \
    && nvm use --lts \
    && nvm alias default lts/* \
    && ln -sf "$NVM_DIR/versions/node/$(nvm current)" "$NVM_DIR/current"

# Install Claude Code using the official native installer
RUN curl -fsSL https://claude.ai/install.sh | bash

# Add Claude, Cargo, and Node to PATH (using symlinked current node)
# Activate Python venv globally so all packages are available via `python3`
ENV PATH="/home/claude/.local/python-venv/bin:/home/claude/.nvm/current/bin:/home/claude/.cargo/bin:/home/claude/.local/bin:${PATH}"
ENV VIRTUAL_ENV="/home/claude/.local/python-venv"

# Install Python packages: browser tools (Playwright), linters (pyright, ruff),
# and data science libraries (matplotlib, numpy)
RUN python3 -m venv ~/.local/python-venv && \
    ~/.local/python-venv/bin/pip install playwright pyright ruff matplotlib numpy

# Copy browser tools
COPY --chown=claude:claude browser-tools/ /home/claude/.local/browser-tools/
RUN chmod +x /home/claude/.local/browser-tools/browser.sh && \
    ln -sf /home/claude/.local/browser-tools/browser.sh /home/claude/.local/bin/browser

# Create persistent volume directory structure
# All persistent data goes in persist which is mounted from a single Docker volume
RUN mkdir -p /home/claude/persist/.claude

# Move installer-created files to volume location
RUN mv /home/claude/.claude.json /home/claude/persist/.claude.json 2>/dev/null || true \
    && mv /home/claude/.claude/* /home/claude/persist/.claude/ 2>/dev/null || true

# Remove original directory and create symlinks to volume
RUN rm -rf /home/claude/.claude \
    && ln -sf /home/claude/persist/.claude /home/claude/.claude \
    && ln -sf /home/claude/persist/.claude.json /home/claude/.claude.json

# Set up persistence for Claude Code binary versions (~/.local/share/claude)
# This prevents re-downloading Claude Code updates on every container restart
RUN mv /home/claude/.local/share/claude /home/claude/persist/.claude-versions 2>/dev/null || true \
    && ln -sf /home/claude/persist/.claude-versions /home/claude/.local/share/claude

# Backup nvm, Rust, and Claude Code to template location for volume initialization
# This allows the entrypoint to seed the persistent volume on first run
USER root
RUN cp -a /home/claude/.nvm /opt/nvm-template \
    && cp -a /home/claude/.rustup /opt/rustup-template \
    && cp -a /home/claude/.cargo /opt/cargo-template \
    && cp -a /home/claude/persist/.claude-versions /opt/claude-versions-template
USER claude

# Copy firewall and entrypoint scripts (after installs to preserve cache)
USER root

# Create workspaces directory with proper permissions
RUN mkdir -p /workspaces && chown claude:claude /workspaces

COPY init-firewall.sh /opt/init-firewall.sh
COPY entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/init-firewall.sh /opt/entrypoint.sh

# Copy global context file to non-volume location (source of truth for entrypoint)
COPY agent-context.md /opt/agent-context.md

# Run as root by default so entrypoint can set up firewall if needed
# Entrypoint drops privileges to claude user for running claude
WORKDIR /workspaces

ENTRYPOINT ["/opt/entrypoint.sh"]
CMD []
