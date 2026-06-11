#!/usr/bin/env bash
#
# Factory / post-provision smoke test for PiWalletSV sealed images.
#
# Run on the Pi after provision-pi.sh (with --keep-ssh during image build)
# and before capturing the SD image. Logs pass/fail for batch records.
#
# Usage:
#   sudo bash scripts/factory-smoke-test.sh [--serial SN] [--skip-camera] [--skip-display]
#
# Environment:
#   PIWALLET_REPO   repo root (default: parent of scripts/, or /opt/piwallet)
#   PIWALLET_VENV   venv path (default: $PIWALLET_REPO/.venv)
#
set -euo pipefail

readonly LOG_PREFIX="[factory-smoke]"

REPO_ROOT=""
VENV=""
SERIAL=""
SKIP_CAMERA=0
SKIP_DISPLAY=0
FAILURES=0

usage() {
    sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-2}"
}

log()  { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s WARN: %s\n' "$LOG_PREFIX" "$*" >&2; }
fail_step() {
    FAILURES=$((FAILURES + 1))
    printf '%s FAIL: %s\n' "$LOG_PREFIX" "$*" >&2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --serial)      SERIAL=${2:?--serial requires a value}; shift ;;
        --serial=*)    SERIAL=${1#--serial=} ;;
        --skip-camera) SKIP_CAMERA=1 ;;
        --skip-display) SKIP_DISPLAY=1 ;;
        -h|--help)     usage 0 ;;
        *)             echo "error: unknown arg '$1'" >&2; usage ;;
    esac
    shift
done

if [[ -z "${PIWALLET_REPO:-}" ]]; then
    if [[ -d /opt/piwallet/pyproject.toml ]]; then
        REPO_ROOT=/opt/piwallet
    else
        REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    fi
else
    REPO_ROOT=$PIWALLET_REPO
fi

if [[ -n "${PIWALLET_VENV:-}" ]]; then
    VENV=$PIWALLET_VENV
elif [[ -x /opt/piwallet/.venv/bin/python ]]; then
    VENV=/opt/piwallet/.venv
else
    VENV="$REPO_ROOT/.venv"
fi

PY="$VENV/bin/python"
PIWALLET="$VENV/bin/piwallet"

log "serial=${SERIAL:-n/a} repo=$REPO_ROOT venv=$VENV"

if [[ ! -x "$PY" ]]; then
    fail_step "venv python missing at $PY"
    exit 1
fi

log "== import smoke =="
if "$PY" -c "import piwallet; from bsv import PrivateKey; import coincurve; print('piwallet', piwallet.__version__)"; then
    log "PASS imports"
else
    fail_step "Python import smoke"
fi

if [[ -x "$PIWALLET" ]]; then
    log "== piwallet diag display =="
    if "$PIWALLET" diag display; then
        log "PASS diag display"
    else
        fail_step "piwallet diag display"
    fi

    log "== piwallet diag gpio =="
    if "$PIWALLET" diag gpio; then
        log "PASS diag gpio"
    else
        fail_step "piwallet diag gpio"
    fi
else
    warn "piwallet CLI missing — skipping diag subcommands"
fi

if [[ $SKIP_DISPLAY -eq 0 && -x "$REPO_ROOT/scripts/run_display_demo.sh" ]]; then
    log "== display demo (5s) =="
    if timeout 8 bash "$REPO_ROOT/scripts/run_display_demo.sh" --timeout 5 2>/dev/null; then
        log "PASS display demo"
    elif timeout 8 bash "$REPO_ROOT/scripts/run_display_demo.sh" 2>/dev/null; then
        log "PASS display demo (no --timeout flag)"
    else
        fail_step "display demo — run manually: bash scripts/run_display_demo.sh"
    fi
else
    log "SKIP display demo"
fi

if [[ $SKIP_CAMERA -eq 0 && -x "$REPO_ROOT/scripts/run_camera_qr_test.sh" ]]; then
    log "== camera QR smoke =="
    if timeout 20 bash "$REPO_ROOT/scripts/run_camera_qr_test.sh" --once 2>/dev/null; then
        log "PASS camera QR"
    elif timeout 20 bash "$REPO_ROOT/scripts/run_camera_qr_test.sh" 2>/dev/null; then
        log "PASS camera QR (default mode)"
    else
        fail_step "camera QR — run manually: bash scripts/run_camera_qr_test.sh"
    fi
else
    log "SKIP camera"
fi

if [[ -f /etc/piwalletsv-release ]]; then
    log "== release metadata =="
    log "  version=$(grep -E '^PIWALLETSV_VERSION=' /etc/piwalletsv-release | cut -d= -f2-)"
    log "  channel=$(grep -E '^PIWALLETSV_IMAGE_CHANNEL=' /etc/piwalletsv-release | cut -d= -f2-)"
    log "  image_id=$(grep -E '^PIWALLETSV_IMAGE_ID=' /etc/piwalletsv-release | cut -d= -f2-)"
else
    warn "missing /etc/piwalletsv-release"
fi

if [[ $FAILURES -eq 0 ]]; then
    log "ALL PASS${SERIAL:+ serial=$SERIAL}"
    exit 0
fi

log "FAILED ($FAILURES step(s))${SERIAL:+ serial=$SERIAL}"
exit 1
