#!/usr/bin/env bash
#
# Launch DateTree.
#
#   ./start.sh              start the app
#   ./start.sh FILE...      print the date DateTree would file each file under
#
# Set DATETREE_PYTHON to force a particular interpreter.

set -euo pipefail

cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")")"

# Tk is the one hard requirement, and a Python without it fails at import time
# with a message that doesn't say how to fix it -- so check up front.
find_python() {
    local candidate
    for candidate in "${DATETREE_PYTHON:-}" python3 \
                     /opt/homebrew/bin/python3 /usr/local/bin/python3; do
        [ -n "$candidate" ] || continue
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import tkinter' >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

if ! PYTHON=$(find_python); then
    cat >&2 <<'EOF'
DateTree needs a Python 3 with Tk support, and none was found.

On macOS:
    brew install python-tk

Then run ./start.sh again, or set DATETREE_PYTHON to the interpreter to use.
EOF
    exit 1
fi

exec "$PYTHON" -m datetree "$@"
