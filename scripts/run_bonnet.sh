#!/usr/bin/env bash
# Launch the bonnet UI using the repo venv (no manual `source .venv/bin/activate`).
#
# Usage:
#   ./scripts/run_bonnet.sh
#   ./scripts/run_bonnet.sh --vault-path /home/pi/.piwallet/vault.bin
# Optional: ln -s /path/to/PiWallet/scripts/run_bonnet.sh ~/bin/piwallet-bonnet
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIWALLET="$ROOT/.venv/bin/piwallet"

if [[ ! -x "$PIWALLET" ]]; then
  echo "missing $PIWALLET — create the venv and pip install -e . first" >&2
  exit 1
fi

exec "$PIWALLET" bonnet "$@"
