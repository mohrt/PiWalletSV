#!/usr/bin/env bash
# Smoke-test USB backup on a Pi (or locally with a directory pretending to be a stick).
#
# Local (no hardware):
#   ./scripts/usb-backup-smoke.sh --local /tmp/piwallet-usb-test
#
# On the Pi (SSH), with a FAT32/exFAT stick already mounted at MOUNT:
#   ./scripts/usb-backup-smoke.sh --remote pi@piwallet-1.local /media/usb
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

LOCAL_DIR=""
REMOTE=""
MOUNT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local)
      LOCAL_DIR="${2:?}"
      shift 2
      ;;
    --remote)
      REMOTE="${2:?}"
      MOUNT="${3:?}"
      shift 3
      ;;
    *)
      echo "usage: $0 --local DIR"
      echo "       $0 --remote USER@HOST MOUNTPOINT"
      exit 1
      ;;
  esac
done

run_local() {
  cd "$ROOT"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  export PIWALLET_HOME="${TMPDIR:-/tmp}/piwallet-smoke-$$"
  mkdir -p "$PIWALLET_HOME"
  python - <<'PY'
import os
from pathlib import Path
from piwallet.backup.bundle import export_backup, import_backup, list_backup_summaries
from piwallet.core.vault import Vault

home = Path(os.environ["PIWALLET_HOME"])
vault_path = home / "vault.bin"
pin = "123456"
phrase = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)
vault = Vault(vault_path)
vault.create(pin=pin)
vault.add_wallet(pin=pin, mnemonic_phrase=phrase, label="smoke")
PY
  piwallet backup export --stick-root "$LOCAL_DIR" --vault-path "$PIWALLET_HOME/vault.bin"
  rm -f "$PIWALLET_HOME/vault.bin"
  BACKUP_DIR=$(find "$LOCAL_DIR/PiWalletSV/backups" -mindepth 1 -maxdepth 1 -type d | head -1)
  printf '123456\n' | piwallet backup import --backup-dir "$BACKUP_DIR" --vault-path "$PIWALLET_HOME/vault.bin" --import-settings
  piwallet vault --vault-path "$PIWALLET_HOME/vault.bin" list
  echo "local smoke OK"
}

CANONICAL="abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"

if [[ -n "$LOCAL_DIR" ]]; then
  mkdir -p "$LOCAL_DIR"
  run_local
  exit 0
fi

if [[ -n "$REMOTE" ]]; then
  ssh "$REMOTE" "bash -s" <<EOF
set -euo pipefail
cd ~/PiWallet || cd /opt/piwallet
source .venv/bin/activate 2>/dev/null || true
piwallet backup list-devices
piwallet backup export --stick-root "$MOUNT"
piwallet backup list-backups --stick-root "$MOUNT"
echo "remote export OK — verify on bonnet: Settings → Backup to USB / Restore from USB"
EOF
  exit 0
fi

echo "nothing to do"
exit 1
