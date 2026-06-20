#!/usr/bin/env bash
# Build a FAT32/exFAT USB stick layout for the camera hotfix (no network on Pi).
#
# On your Mac:
#   ./deploy/scripts/make-camera-hotfix-stick.sh /Volumes/MYSTICK
#
# Then plug the stick into the Pi (OTG hub), log in on tty2, and run:
#   sudo bash /mnt/piwallet-usb/camera-hotfix/apply-camera-hotfix.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="${1:?usage: $0 /Volumes/YOUR_USB_STICK}"

if [[ ! -d "$DEST" ]]; then
  echo "destination not found: $DEST" >&2
  exit 1
fi

OUT="$DEST/camera-hotfix"
rm -rf "$OUT"
mkdir -p "$OUT/deploy/systemd" "$OUT/deploy/scripts" "$OUT/piwallet/bonnet"

copy() {
  local rel="$1"
  install -m 0644 "$REPO_ROOT/$rel" "$OUT/$rel"
}

copy deploy/systemd/piwallet-bonnet.service
copy deploy/scripts/test-camera-sandbox.sh
copy deploy/scripts/apply-camera-hotfix.sh
copy piwallet/bonnet/entropy_camera.py
copy piwallet/bonnet/camera_still.py
copy piwallet/bonnet/entropy_screens.py
copy piwallet/bonnet/create_wallet.py
copy piwallet/cli.py

chmod 0755 "$OUT/deploy/scripts/apply-camera-hotfix.sh"
chmod 0755 "$OUT/deploy/scripts/test-camera-sandbox.sh"

cat >"$OUT/README.txt" <<'EOF'
PiWalletSV camera hotfix (offline)

On the Pi (Ctrl+Alt+F2 → login as pisv):

1. Plug this USB stick into the Pi (via OTG hub if needed).
2. Find the partition, e.g. lsblk
3. Mount (if not already at /mnt/piwallet-usb):
     sudo /opt/piwallet/bin/usb-mount mount /dev/sda1
   Or manually:
     sudo mkdir -p /mnt/piwallet-usb
     sudo mount -t vfat -o uid=$(id -u pwsv),gid=$(id -g pwsv) /dev/sda1 /mnt/piwallet-usb
4. Apply:
     sudo bash /mnt/piwallet-usb/camera-hotfix/deploy/scripts/apply-camera-hotfix.sh \
       /mnt/piwallet-usb/camera-hotfix
5. Test:
     sudo -u pwsv /opt/piwallet/.venv/bin/piwallet diag camera
6. Unmount and remove stick:
     sudo /opt/piwallet/bin/usb-mount unmount

If diag camera passes but bonnet Photo entropy still fails, restart bonnet:
  sudo systemctl restart piwallet-bonnet

This hotfix includes photo-entropy OOM fixes (armv6 capture size, thumbnail decode).
EOF

echo "Wrote $OUT"
echo "Safely eject the stick, plug into Pi, follow $OUT/README.txt"
