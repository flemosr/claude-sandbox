#!/bin/bash
# Claude Sandbox Configuration (for Chrome integration)
#
# This config is only needed if you want to use the Chrome integration.
# Copy this file to config.sh and edit to match your setup:
#
#   cp config.template.sh config.sh
#
# Your config.sh is gitignored, so your personal settings won't be committed.
#
# REQUIRED: Create a dedicated Chrome profile for Claude:
#   1. Open Chrome and click your profile icon (top-right)
#   2. Click "Add" to create a new profile named "Claude"
#   3. Go to chrome://version in the new profile
#   4. Look at "Profile Path" - the last folder name is your profile
#      (e.g., "Profile 3")
#   5. Set CHROME_PROFILE below to that folder name

# Path to Chrome executable
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Chrome user data directory (where profiles are stored)
CHROME_USER_DATA="$HOME/Library/Application Support/Google/Chrome"

# Separate directory for debug sessions (required for remote debugging)
CHROME_DEBUG_DATA="$HOME/Library/Application Support/Google/Chrome-Debug"

# Chrome profile directory name (create a dedicated "Claude" profile)
CHROME_PROFILE="CHANGE_ME"

# External port for CDP (accessible from Docker via host.docker.internal)
CHROME_DEBUG_PORT=9222

# Internal port Chrome listens on (socat forwards external port to this)
CHROME_INTERNAL_PORT=19222

# Chrome debug log file (mounted into container at /tmp/chrome-debug.log)
CHROME_LOG_FILE="/tmp/chrome-debug.log"

# Git identity (used inside the sandbox for commits)
# GIT_AUTHOR_NAME="Sandbox Agent Name"
# GIT_AUTHOR_EMAIL="agent@example.local"

# Enable GPG commit signing (generates a sandbox-specific key on first run)
# Requires GIT_AUTHOR_NAME and GIT_AUTHOR_EMAIL to be set
# GPG_SIGNING=true
