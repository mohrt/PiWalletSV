#!/usr/bin/env bash
# Offline camera triage on the Pi (tty2). No network required.
# Log in as your console user (e.g. pisv), then: sudo bash deploy/scripts/diag-camera-offline.sh
#
# Note: the bonnet systemd unit runs as pwsv (no login shell). Tests below
# include both your login user and pwsv to match factory vs production paths.
set -euo pipefail

OPT_PIWALLET="${PIWALLET_ROOT:-/opt/piwallet}"
PY="${OPT_PIWALLET}/.venv/bin/python"
PIWALLET="${OPT_PIWALLET}/.venv/bin/piwallet"

section() { echo; echo "=== $* ==="; }

section "bonnet service (stop for exclusive camera access)"
systemctl stop piwallet-bonnet.service 2>/dev/null || true

section "boot config (OV5647 kit expects explicit overlay)"
for cfg in /boot/firmware/config.txt /boot/config.txt; do
  if [[ -f "$cfg" ]]; then
    echo "--- $cfg ---"
    grep -E '^(camera_auto_detect|dtoverlay=ov5647|start_x|gpu_mem)' "$cfg" || echo "(no camera lines)"
  fi
done

section "device nodes"
ls -l /dev/video* /dev/media* /dev/v4l-subdev* /dev/vchiq 2>/dev/null || echo "(some nodes missing)"

section "login user groups (pisv / pi — Imager account on tty2)"
for u in pisv pi; do
  if id "$u" &>/dev/null; then
    echo "--- id $u ---"
    id "$u"
  fi
done

section "bonnet runtime user pwsv (systemd User=)"
if id pwsv &>/dev/null; then
  id pwsv
else
  echo "pwsv missing — bonnet unit may not match this image"
fi

section "rpicam / libcamera list (root)"
if command -v rpicam-hello >/dev/null; then
  rpicam-hello --list-cameras 2>&1 || true
elif command -v libcamera-hello >/dev/null; then
  libcamera-hello --list-cameras 2>&1 || true
else
  echo "rpicam-hello not installed"
fi

section "rpicam list as login user (pisv)"
if id pisv &>/dev/null && command -v rpicam-hello >/dev/null; then
  sudo -u pisv rpicam-hello --list-cameras 2>&1 || true
fi

section "rpicam list as bonnet user (pwsv)"
if command -v rpicam-hello >/dev/null; then
  sudo -u pwsv rpicam-hello --list-cameras 2>&1 || true
fi

section "Picamera2.global_camera_info() as pwsv"
if [[ -x "$PY" ]]; then
  sudo -u pwsv "$PY" - <<'PY' || true
from picamera2 import Picamera2
info = Picamera2.global_camera_info()
print("global_camera_info:", info)
print("count:", len(info))
PY
else
  echo "missing $PY"
fi

section "piwallet diag camera as pwsv (full capture)"
if [[ -x "$PIWALLET" ]]; then
  sudo -u pwsv "$PIWALLET" diag camera 2>&1 || true
else
  echo "missing $PIWALLET"
fi

section "systemd unit camera-related settings"
systemctl show piwallet-bonnet.service -p User,SupplementaryGroups,DevicePolicy,DeviceAllow,RestrictAddressFamilies,MemoryDenyWriteExecute,ProtectHome,ProtectSystem,ReadWritePaths,Environment 2>/dev/null || true
if [[ -d /etc/systemd/system/piwallet-bonnet.service.d ]]; then
  echo "--- drop-ins ---"
  ls -la /etc/systemd/system/piwallet-bonnet.service.d/
fi

section "kernel camera messages"
dmesg 2>/dev/null | grep -iE 'ov5647|unicam|camera|libcamera' | tail -20 || echo "(no dmesg or no matches)"

echo
echo "Interpret:"
echo "  * rpicam lists 0 cameras -> hardware/config (ribbon, config.txt, reboot)"
echo "  * rpicam OK as pisv but empty as pwsv -> pwsv missing video group"
echo "  * pwsv shell OK but bonnet fails -> systemd sandbox (apply camera drop-in)"
echo
echo "Restart bonnet when done: sudo systemctl start piwallet-bonnet"
