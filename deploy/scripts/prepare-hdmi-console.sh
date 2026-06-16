#!/usr/bin/env bash
# Prepare a fresh Pi OS Lite image for HDMI + USB keyboard console on tty2.
#
# Pi Zero W with stock Bookworm/Trixie config uses full KMS (vc4-kms-v3d) and
# disable_fw_kms_setup=1. Without a monitor at DRM init that leaves no /dev/fb0
# and HDMI stays black. This script applies the same fix baked into provision-pi.sh.
#
# Usage (on the Pi, as root):
#   sudo bash deploy/scripts/prepare-hdmi-console.sh
#
# Then reboot. After reboot:
#   ls -la /dev/fb*          # expect /dev/fb0
#   Ctrl+Alt+F2              # Mac: Ctrl+Fn+Option+F2 → tty2 login
#   sudo bash ~/PiWallet/deploy/provision-pi.sh --src ~/PiWallet
set -euo pipefail

readonly LOG_PREFIX="[prepare-hdmi]"
BOOT_CFG="/boot/firmware/config.txt"
[[ -f "$BOOT_CFG" ]] || BOOT_CFG="/boot/config.txt"
[[ -f "$BOOT_CFG" ]] || { echo "$LOG_PREFIX config.txt not found" >&2; exit 1; }

log() { printf '%s %s\n' "$LOG_PREFIX" "$*"; }

if [[ $(id -u) -ne 0 ]]; then
    echo "$LOG_PREFIX must run as root" >&2
    exit 1
fi

log "config: $BOOT_CFG"

if ! grep -q '^hdmi_force_hotplug=1' "$BOOT_CFG"; then
    echo 'hdmi_force_hotplug=1' >> "$BOOT_CFG"
    log "added hdmi_force_hotplug=1"
else
    log "hdmi_force_hotplug=1 already set"
fi

if grep -q 'dtoverlay=vc4-kms-v3d' "$BOOT_CFG"; then
    sed -i 's/dtoverlay=vc4-kms-v3d/dtoverlay=vc4-fkms-v3d/' "$BOOT_CFG"
    log "switched vc4-kms-v3d → vc4-fkms-v3d"
elif grep -q 'dtoverlay=vc4-fkms-v3d' "$BOOT_CFG"; then
    log "vc4-fkms-v3d already set"
else
    log "WARN: no vc4 overlay found — HDMI may still be blank"
fi

if grep -q '^disable_fw_kms_setup=1' "$BOOT_CFG"; then
    sed -i '/^disable_fw_kms_setup=1/d' "$BOOT_CFG"
    log "removed disable_fw_kms_setup=1"
else
    log "disable_fw_kms_setup=1 not present"
fi

log "effective video settings:"
grep -E '^(dtoverlay=vc4|disable_fw_kms|hdmi_)' "$BOOT_CFG" || true

systemctl enable getty@tty2.service
systemctl start getty@tty2.service || true
log "getty@tty2 enabled and started"

log "done — reboot required"
echo
echo "  sudo reboot"
echo
echo "After reboot, verify:"
echo "  ls -la /dev/fb*     # expect /dev/fb0"
echo "  Ctrl+Alt+F2         # tty2 login (Mac: Ctrl+Fn+Option+F2)"
