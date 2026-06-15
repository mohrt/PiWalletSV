#!/usr/bin/env bash
# Apply camera hotfix from a USB stick (run on Pi as root).
set -euo pipefail

PATCH_ROOT="${1:?usage: $0 /path/to/camera-hotfix}"
OPT_PIWALLET="${PIWALLET_ROOT:-/opt/piwallet}"

if [[ ! -d "$PATCH_ROOT/piwallet/bonnet" ]]; then
  echo "invalid patch tree: $PATCH_ROOT" >&2
  exit 1
fi

echo "Stopping bonnet..."
systemctl stop piwallet-bonnet

echo "Installing Python files under $OPT_PIWALLET..."
install -m 0644 "$PATCH_ROOT/piwallet/bonnet/entropy_camera.py" \
  "$OPT_PIWALLET/piwallet/bonnet/entropy_camera.py"
install -m 0644 "$PATCH_ROOT/piwallet/bonnet/camera_still.py" \
  "$OPT_PIWALLET/piwallet/bonnet/camera_still.py"
install -m 0644 "$PATCH_ROOT/piwallet/bonnet/entropy_screens.py" \
  "$OPT_PIWALLET/piwallet/bonnet/entropy_screens.py"
install -m 0644 "$PATCH_ROOT/piwallet/cli.py" \
  "$OPT_PIWALLET/piwallet/cli.py"

if [[ -f "$PATCH_ROOT/deploy/scripts/test-camera-sandbox.sh" ]]; then
  install -m 0755 "$PATCH_ROOT/deploy/scripts/test-camera-sandbox.sh" \
    "$OPT_PIWALLET/deploy/scripts/test-camera-sandbox.sh"
fi

echo "Installing systemd unit..."
install -m 0644 "$PATCH_ROOT/deploy/systemd/piwallet-bonnet.service" \
  /etc/systemd/system/piwallet-bonnet.service

systemctl daemon-reload
systemctl start piwallet-bonnet

echo
echo "Hotfix applied. Test with:"
echo "  sudo -u pwsv $OPT_PIWALLET/.venv/bin/piwallet diag camera"
if [[ -x "$OPT_PIWALLET/deploy/scripts/test-camera-sandbox.sh" ]]; then
  echo "  sudo bash $OPT_PIWALLET/deploy/scripts/test-camera-sandbox.sh"
fi
