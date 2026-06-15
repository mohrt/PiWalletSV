#!/usr/bin/env bash
# Camera triage on a provisioned Pi (no network). Run as root on tty2 or over SSH.
#
# Tests the same pwsv + Picamera2 path as factory smoke and bonnet Photo entropy.
# Does NOT run root rpicam before pwsv — that monopolizes the sensor on Pi Zero W
# and makes later pwsv checks fail with dmaHeap / EBUSY (-12).
#
# Usage:
#   sudo bash deploy/scripts/diag-camera-offline.sh
#
# Exit 0 when all production-path checks pass; non-zero otherwise.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=camera-exclusive-access.sh
source "$SCRIPT_DIR/camera-exclusive-access.sh"

PIWALLET="${PIWALLET:-/opt/piwallet/.venv/bin/piwallet}"
REPO="${PIWALLET_REPO:-/opt/piwallet}"
CAMERA_QR="${REPO}/scripts/camera_qr_test.py"

FAILURES=0

section() {
    echo
    echo "========== $* =========="
}

pass() {
    echo "PASS  $*"
}

fail() {
    echo "FAIL  $*"
    FAILURES=$((FAILURES + 1))
}

info() {
    echo "INFO  $*"
}

trap restore_camera_exclusive_access EXIT

section "boot config (camera)"
CFG=""
for p in /boot/firmware/config.txt /boot/config.txt; do
    if [[ -f "$p" ]]; then
        CFG="$p"
        break
    fi
done
if [[ -n "$CFG" ]]; then
    grep -E '^(camera_auto_detect|start_x|gpu_mem|dtoverlay=ov5647)' "$CFG" 2>/dev/null || true
    if grep -q '^camera_auto_detect=1' "$CFG" 2>/dev/null; then
        info "sealed default: camera_auto_detect=1 (libcamera auto-detects OV5647)"
    elif grep -q '^camera_auto_detect=0' "$CFG" 2>/dev/null && grep -q 'dtoverlay=ov5647' "$CFG" 2>/dev/null; then
        info "manual OV5647 overlay mode (dev/bootstrap)"
    fi
else
    fail "no config.txt under /boot"
fi

section "device nodes"
ls -l /dev/video* /dev/media* 2>/dev/null || fail "no /dev/video* or /dev/media*"

section "pwsv groups (need video for libcamera)"
if id pwsv &>/dev/null; then
    groups pwsv
    if groups pwsv | grep -qw video; then
        pass "pwsv is in video group"
    else
        fail "pwsv not in video group — re-run provision-pi.sh"
    fi
else
    fail "pwsv user missing"
fi

section "exclusive camera access (stop bonnet)"
prepare_camera_exclusive_access
if [[ "${CAMERA_BONNET_WAS_ACTIVE:-0}" -eq 1 ]]; then
    info "stopped piwallet-bonnet for sensor access"
else
    info "bonnet was already stopped"
fi

section "picamera2 camera count (pwsv)"
PY_BIN="${REPO}/.venv/bin/python"
[[ -x "$PY_BIN" ]] || PY_BIN="python3"
if id pwsv &>/dev/null; then
    # Redirect libcamera INFO/WARN to /dev/null; capture only stdout (the count).
    count_out="$(sudo -u pwsv env LIBCAMERA_LOG_LEVELS='*:ERROR' "$PY_BIN" -c "
from picamera2 import Picamera2
print(len(Picamera2.global_camera_info()))
" 2>/dev/null)" || count_out="error"
    echo "$count_out"
    if [[ "$count_out" == "1" ]]; then
        pass "libcamera sees 1 camera as pwsv"
    else
        fail "expected 1 camera as pwsv, got: $count_out"
    fi
else
    fail "skipped — no pwsv"
fi

section "piwallet diag camera (pwsv)"
if [[ -x "$PIWALLET" ]] && id pwsv &>/dev/null; then
    if out="$(sudo -u pwsv "$PIWALLET" diag camera 2>&1)"; then
        echo "$out"
        pass "piwallet diag camera"
    else
        echo "$out"
        fail "piwallet diag camera"
    fi
else
    fail "missing $PIWALLET or pwsv"
fi

section "camera QR smoke (pwsv, same as factory-smoke)"
if [[ -f "$CAMERA_QR" ]] && id pwsv &>/dev/null; then
    if out="$(timeout 30 sudo -u pwsv env LIBCAMERA_LOG_LEVELS='*:ERROR' "$PY_BIN" "$CAMERA_QR" --once 2>&1)"; then
        echo "$out" | head -20
        pass "camera_qr_test.py --once"
    else
        echo "$out" | tail -30
        fail "camera_qr_test.py --once"
    fi
else
    fail "missing $CAMERA_QR or pwsv"
fi

section "root rpicam list (informational only, after pwsv)"
if command -v rpicam-hello &>/dev/null; then
    rpicam-hello --list-cameras 2>&1 | head -20 || true
    info "root listing is informational; production path is pwsv Picamera2 above"
else
    info "rpicam-hello not installed — skip"
fi

section "interpret"
if [[ $FAILURES -eq 0 ]]; then
    pass "all production-path camera checks passed"
    echo "  Bonnet Photo entropy should work. Bonnet will be restarted if it was running."
else
    echo "  $FAILURES check(s) failed."
    echo "  - Re-seat ribbon cable (contacts toward HDMI on Pi Zero W)."
    echo "  - Reboot once, then re-run this script."
    echo "  - Sealed images use camera_auto_detect=1; only add dtoverlay=ov5647 if auto-detect fails."
    echo "  - Do not run root rpicam-hello before pwsv tests on Pi Zero W."
fi

exit "$FAILURES"
