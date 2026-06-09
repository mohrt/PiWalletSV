#!/usr/bin/env bash
# Camera + pyzbar smoke test (uses repo venv).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
SCRIPT="$ROOT/scripts/camera_qr_test.py"

if [[ ! -x "$PY" ]]; then
    echo "missing $PY — run: bash scripts/bootstrap-pi-dev.sh" >&2
    exit 1
fi
if [[ ! -f "$SCRIPT" ]]; then
    echo "missing $SCRIPT" >&2
    exit 1
fi

exec "$PY" "$SCRIPT" "$@"
