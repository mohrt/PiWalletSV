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
    demo_seconds=5
    demo_timeout=$((demo_seconds + 20))
    bonnet_was=0
    if systemctl is-active -q piwallet-bonnet.service 2>/dev/null; then
        bonnet_was=1
        systemctl stop piwallet-bonnet.service
    fi
    demo_rc=0
    demo_err=""
    if id pwsv &>/dev/null; then
        demo_err=$(mktemp)
        if ! timeout "$demo_timeout" sudo -u pwsv bash "$REPO_ROOT/scripts/run_display_demo.sh" \
                --timeout "$demo_seconds" >"$demo_err" 2>&1; then
            demo_rc=$?
        fi
    elif ! timeout "$demo_timeout" bash "$REPO_ROOT/scripts/run_display_demo.sh" \
            --timeout "$demo_seconds" >/dev/null 2>&1; then
        demo_rc=$?
    fi
    if [[ $bonnet_was -eq 1 ]]; then
        systemctl start piwallet-bonnet.service 2>/dev/null || \
            warn "failed to restart piwallet-bonnet"
    fi
    if [[ $demo_rc -eq 0 ]]; then
        [[ -n "$demo_err" ]] && rm -f "$demo_err"
        log "PASS display demo"
    else
        if [[ -n "$demo_err" && -s "$demo_err" ]]; then
            warn "display demo output: $(tail -3 "$demo_err" | tr '\n' ' ')"
            rm -f "$demo_err"
        fi
        fail_step "display demo — run manually: sudo systemctl stop piwallet-bonnet && bash scripts/run_display_demo.sh --timeout 5"
    fi
else
    log "SKIP display demo"
fi

if [[ $SKIP_CAMERA -eq 0 ]]; then
    log "== camera (pwsv path via diag-camera-offline.sh) =="
    if [[ -f "$REPO_ROOT/deploy/scripts/diag-camera-offline.sh" ]]; then
        if bash "$REPO_ROOT/deploy/scripts/diag-camera-offline.sh"; then
            log "PASS camera (diag-camera-offline)"
        else
            fail_step "camera — see deploy/scripts/diag-camera-offline.sh output above"
        fi
    elif [[ -x "$REPO_ROOT/scripts/run_camera_qr_test.sh" ]]; then
        # shellcheck source=../deploy/scripts/camera-exclusive-access.sh
        source "$REPO_ROOT/deploy/scripts/camera-exclusive-access.sh"
        prepare_camera_exclusive_access
        cam_err="$(mktemp)"
        cam_rc=0
        if id pwsv &>/dev/null; then
            if ! timeout 30 sudo -u pwsv bash "$REPO_ROOT/scripts/run_camera_qr_test.sh" --once 2>"$cam_err"; then
                cam_rc=$?
            fi
        elif ! timeout 30 bash "$REPO_ROOT/scripts/run_camera_qr_test.sh" --once 2>"$cam_err"; then
            cam_rc=$?
            warn "pwsv missing — camera smoke ran as root (not production-like)"
        fi
        if [[ $cam_rc -ne 0 && -s "$cam_err" ]]; then
            warn "camera output: $(tail -5 "$cam_err" | tr '\n' ' ')"
        fi
        rm -f "$cam_err"
        restore_camera_exclusive_access
        if [[ $cam_rc -eq 0 ]]; then
            log "PASS camera QR (pwsv)"
        else
            fail_step "camera QR"
        fi
    else
        fail_step "camera — missing deploy/scripts/diag-camera-offline.sh"
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
