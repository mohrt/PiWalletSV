#!/usr/bin/env bash
# Fix sealed-image camera boot config offline (run on Mac with alpha SD inserted).
#
# The sealed provision script used to append camera_auto_detect=0 + dtoverlay=ov5647
# on top of Imager's camera_auto_detect=1. The firmware uses the *last* value — so
# forced overlay mode broke detection even though a stock SD works on the same hardware.
#
# Usage (SD boot partition mounted at /Volumes/bootfs):
#   ./deploy/scripts/fix-sealed-camera-boot.sh /Volumes/bootfs/config.txt
set -euo pipefail

CFG="${1:?usage: $0 /Volumes/bootfs/config.txt}"

if [[ ! -f "$CFG" ]]; then
  echo "config not found: $CFG" >&2
  exit 1
fi

cp "$CFG" "${CFG}.bak-piwallet-camera"

# Remove forced OV5647-only lines; set auto-detect (matches working stock SD).
sed -i '' '/^camera_auto_detect=/d' "$CFG"
sed -i '' '/^dtoverlay=ov5647$/d' "$CFG"
printf '\n# PiWalletSV — libcamera auto-detect (kit OV5647)\n' >> "$CFG"
printf 'camera_auto_detect=1\n' >> "$CFG"

echo "Patched $CFG (backup: ${CFG}.bak-piwallet-camera)"
echo "Eject SD, boot Pi, run: rpicam-hello --list-cameras"
echo "If bonnet Photo entropy still fails after that, apply the systemd camera drop-in too."
