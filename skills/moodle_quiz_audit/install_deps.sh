#!/bin/bash
# Install Python dependencies for moodle_quiz_audit skill.
# Uses the Hermes venv (not system Python, which is PEP 668 locked).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HERMES_HOME="${HERMES_HOME:-/var/www/moodledata/.hermes}"
VENV="$HERMES_HOME/venv"

if [ ! -f "$VENV/bin/pip" ]; then
    echo "ERROR: Hermes venv not found at $VENV" >&2
    echo "Run 'Update & Bootstrap' from the plugin settings page first." >&2
    exit 1
fi

echo "Installing moodle_quiz_audit dependencies into Hermes venv..."
"$VENV/bin/pip" install --no-cache-dir -r "$SCRIPT_DIR/requirements.txt"
echo "Done."
