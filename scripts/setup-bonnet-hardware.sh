#!/usr/bin/env bash
# Adafruit Blinka + SPI CE reassign for the 1.3" TFT bonnet (ST7789).
# Called by bootstrap-pi-dev.sh and deploy/provision-pi.sh.
#
# Usage:
#   bash scripts/setup-bonnet-hardware.sh --repo ~/PiWallet --venv ~/PiWallet/.venv
#   bash scripts/setup-bonnet-hardware.sh --skip-blinka --skip-spi-reassign
set -euo pipefail

readonly LOG_PREFIX="[setup-bonnet-hardware]"
readonly ADAFRUIT_SCRIPTS="https://raw.githubusercontent.com/adafruit/Raspberry-Pi-Installer-Scripts/main"
readonly STATE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/piwallet-bootstrap"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV=""
SKIP_BLINKA=0
SKIP_SPI_REASSIGN=0
DRY_RUN=0
NEEDS_REBOOT=0

log()  { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s WARN: %s\n' "$LOG_PREFIX" "$*" >&2; }
fail() { printf '%s FATAL: %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '%s DRY: %s\n' "$LOG_PREFIX" "$*"
    else
        "$@"
    fi
}

sudo_run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '%s DRY: sudo %s\n' "$LOG_PREFIX" "$*"
    else
        sudo "$@"
    fi
}

mark_reboot() { NEEDS_REBOOT=1; }

venv_python() { printf '%s/bin/python' "$VENV"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)              REPO_ROOT=${2:?}; shift ;;
        --repo=*)            REPO_ROOT=${1#--repo=} ;;
        --venv)              VENV=${2:?}; shift ;;
        --venv=*)            VENV=${1#--venv=} ;;
        --skip-blinka)       SKIP_BLINKA=1 ;;
        --skip-spi-reassign) SKIP_SPI_REASSIGN=1 ;;
        --dry-run)           DRY_RUN=1 ;;
        -h|--help)
            sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) fail "unknown arg: $1" ;;
    esac
    shift
done

[[ -n "$VENV" ]] || VENV="$REPO_ROOT/.venv"
[[ -x "$(venv_python)" ]] || fail "venv missing at $VENV"

blinka_ready() {
    "$(venv_python)" -c "import board" 2>/dev/null
}

spi_reassign_done() {
    [[ -f "$STATE_DIR/spi-reassign.done" ]]
}

mark_spi_reassign_done() {
    [[ $DRY_RUN -eq 1 ]] && return 0
    run mkdir -p "$STATE_DIR"
    run date -Iseconds > "$STATE_DIR/spi-reassign.done"
}

mark_blinka_done() {
    [[ $DRY_RUN -eq 1 ]] && return 0
    run mkdir -p "$STATE_DIR"
    run date -Iseconds > "$STATE_DIR/blinka.done"
}

fetch_adafruit_script() {
    local name=$1 dest=$2
    run mkdir -p "$(dirname "$dest")"
    run curl -fsSL -o "$dest" "$ADAFRUIT_SCRIPTS/$name"
}

step_blinka() {
    if [[ $SKIP_BLINKA -eq 1 ]]; then
        log "Blinka: SKIPPED"
        return 0
    fi
    if blinka_ready; then
        log "Blinka: board module already importable"
        mark_blinka_done
        return 0
    fi

    log "run raspi-blinka.py"
    local script="$STATE_DIR/raspi-blinka.py"
    fetch_adafruit_script "raspi-blinka.py" "$script"
    run "$VENV/bin/pip" install -q adafruit-python-shell

    if [[ $DRY_RUN -eq 1 ]]; then
        log "DRY: sudo $VENV/bin/python $script"
        return 0
    fi

    if sudo_run env PATH="$PATH" "$VENV/bin/python" "$script"; then
        log "  raspi-blinka.py finished"
    else
        warn "raspi-blinka.py exited non-zero (may already be configured)"
    fi

    if blinka_ready; then
        mark_blinka_done
    else
        mark_reboot
        warn "Blinka not ready — reboot, then re-run this script or bootstrap --resume"
        return 2
    fi
}

step_spi_reassign() {
    if [[ $SKIP_SPI_REASSIGN -eq 1 ]]; then
        log "SPI reassign: SKIPPED"
        return 0
    fi
    if spi_reassign_done; then
        log "SPI reassign: already done"
        return 0
    fi
    blinka_ready || fail "Blinka not ready — run blinka step first"

    log "run raspi-spi-reassign.py (--ce0 disabled --ce1 disabled)"
    local script="$STATE_DIR/raspi-spi-reassign.py"
    fetch_adafruit_script "raspi-spi-reassign.py" "$script"
    run "$VENV/bin/pip" install -q adafruit-python-shell click

    if [[ $DRY_RUN -eq 1 ]]; then
        log "DRY: sudo $VENV/bin/python $script ..."
        mark_reboot
        return 0
    fi

    sudo_run env PATH="$PATH" "$VENV/bin/python" \
        "$script" --ce0 disabled --ce1 disabled
    mark_spi_reassign_done
    mark_reboot
    log "SPI reassign applied"
}

main() {
    local rc=0
    step_blinka || rc=$?
    if [[ $rc -eq 2 ]]; then
        exit 2
    elif [[ $rc -ne 0 ]]; then
        exit "$rc"
    fi
    step_spi_reassign
    if [[ $NEEDS_REBOOT -eq 1 ]]; then
        exit 2
    fi
}

main "$@"
