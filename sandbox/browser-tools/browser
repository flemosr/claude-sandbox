#!/bin/bash
# Browser control CLI wrapper
# Usage: browser <command> [args]
#
# Commands:
#   test                    - Test connection to Chrome
#   goto <url>              - Navigate to URL
#   screenshot [-o path]    - Take screenshot
#   click <selector>        - Click an element
#   fill <selector> <text>  - Fill a form field
#   console                 - Get console logs
#   info                    - Get page info

VENV_PATH="$HOME/.local/browser-venv"
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

source "$VENV_PATH/bin/activate"
python3 "$SCRIPT_DIR/browser.py" "$@"
