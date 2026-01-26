# Claude Code Sandbox Environment
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
    zsh \
    fzf \
    iptables \
    iproute2 \
    dnsutils \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for safety
RUN useradd -m -s /bin/bash claude \
    && mkdir -p /home/claude/.local/bin \
    && chown -R claude:claude /home/claude

# Switch to claude user for tool installation
USER claude
WORKDIR /home/claude

# Install Rust stable
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable

# Install Claude Code using the official native installer
RUN curl -fsSL https://claude.ai/install.sh | bash

# Add Claude and Cargo to PATH
ENV PATH="/home/claude/.cargo/bin:/home/claude/.local/bin:${PATH}"

# Create workspace and config directories
RUN mkdir -p /home/claude/workspace /home/claude/.claude

# Copy firewall and entrypoint scripts (after installs to preserve cache)
USER root
COPY init-firewall.sh /opt/init-firewall.sh
COPY entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/init-firewall.sh /opt/entrypoint.sh

USER claude
WORKDIR /home/claude/workspace

# Default command
CMD ["bash"]
