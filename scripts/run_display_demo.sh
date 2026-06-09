#!/usr/bin/env bash
# Bonnet display + buttons smoke test (uses repo venv — not system python3).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
DEMO="$ROOT/scripts/rgb_display_pillow_bonnet_buttons.py"

if [[ ! -x "$PY" ]]; then
    echo "missing $PY — run: bash scripts/bootstrap-pi-dev.sh" >&2
    exit 1
fi
if [[ ! -f "$DEMO" ]]; then
    echo "missing $DEMO" >&2
    exit 1
fi

exec "$PY" "$DEMO" "$@"
