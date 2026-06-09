#!/usr/bin/env bash
# Install PiWalletSV Python dependencies into a venv on Raspberry Pi OS.
#
# Handles the coincurve>=21 vs armv6l workaround: bsv-sdk declares
# coincurve>=21.0.0, but 21.0.0's sdist fails to build on armv6l
# (Pi Zero WH) with "Expected exactly one LICENSE file in cffi
# distribution". piwheels ships coincurve 20.0.0 wheels for armv6l;
# we pin 20 and install bsv-sdk with --no-deps (runtime-compatible).
#
# Usage (on the Pi, from a synced repo):
#   ./scripts/install-piwallet-deps.sh
#   ./scripts/install-piwallet-deps.sh --venv /opt/piwallet/.venv --repo /opt/piwallet
#   ./scripts/install-piwallet-deps.sh --create-venv
#
# Environment:
#   PIWALLET_FORCE_COINCURVE_PIN=1   always use the coincurve 20 workaround
#   PIWALLET_SKIP_VERIFY=1           skip the import smoke test at the end
set -euo pipefail

readonly LOG_PREFIX="[install-piwallet-deps]"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$REPO_ROOT/.venv}"
EXTRAS="${EXTRAS:-display,camera}"
CREATE_VENV=0
DRY_RUN=0

usage() {
    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-2}"
}

log()  { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s WARN: %s\n' "$LOG_PREFIX" "$*" >&2; }

run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '%s DRY: %s\n' "$LOG_PREFIX" "$*"
    else
        "$@"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)        REPO_ROOT=${2:?--repo requires a path}; shift ;;
        --repo=*)      REPO_ROOT=${1#--repo=} ;;
        --venv)        VENV=${2:?--venv requires a path}; shift ;;
        --venv=*)      VENV=${1#--venv=} ;;
        --extras)      EXTRAS=${2:?--extras requires a value}; shift ;;
        --extras=*)    EXTRAS=${1#--extras=} ;;
        --create-venv) CREATE_VENV=1 ;;
        --dry-run)     DRY_RUN=1 ;;
        -h|--help)     usage 0 ;;
        *)             echo "error: unknown arg '$1'" >&2; usage ;;
    esac
    shift
done

[[ -f "$REPO_ROOT/pyproject.toml" ]] || {
    echo "error: $REPO_ROOT/pyproject.toml missing — is --repo correct?" >&2
    exit 1
}

PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

machine_needs_coincurve_pin() {
    local arch
    arch="$(uname -m)"
    case "$arch" in
        armv6l|armv6) return 0 ;;
    esac
    return 1
}

coincurve_pin_required() {
    if [[ "${PIWALLET_FORCE_COINCURVE_PIN:-0}" == 1 ]]; then
        return 0
    fi
    machine_needs_coincurve_pin
}

create_venv_if_needed() {
    if [[ -x "$PYTHON" ]]; then
        return 0
    fi
    if [[ $CREATE_VENV -eq 0 ]]; then
        echo "error: venv missing at $VENV (pass --create-venv to create it)" >&2
        exit 1
    fi
    log "create venv at $VENV (--system-site-packages for apt picamera2/numpy)"
    run python3 -m venv --system-site-packages "$VENV"
}

upgrade_pip_tooling() {
    log "upgrade pip / setuptools / wheel"
    run "$PIP" install --upgrade pip setuptools wheel
}

install_standard() {
    log "pip install -e ${REPO_ROOT}[${EXTRAS}]"
    run "$PIP" install -e "${REPO_ROOT}[${EXTRAS}]"
}

install_with_coincurve_pin() {
    local bsv_version="${PIWALLET_BSV_SDK_VERSION:-2.1.3}"
    log "armv6l / forced pin: coincurve==20.0.0 + bsv-sdk==${bsv_version} --no-deps"
    warn "bsv-sdk declares coincurve>=21; coincurve 21.0.0 does not build on armv6l."
    warn "Using coincurve 20.0.0 (piwheels wheel). pip may warn about the version skew."

    run "$PIP" install "coincurve==20.0.0"

    # Core runtime deps (everything bsv-sdk + piwallet need except coincurve).
    run "$PIP" install \
        cbor2 cryptography click Pillow segno pyzbar \
        pycryptodomex requests aiohttp typing_extensions

    if [[ "$EXTRAS" == *display* ]]; then
        run "$PIP" install \
            adafruit-blinka adafruit-circuitpython-rgb-display
    fi

    run "$PIP" install "bsv-sdk==${bsv_version}" --no-deps
    run "$PIP" install -e "$REPO_ROOT" --no-deps
}

verify_install() {
    if [[ "${PIWALLET_SKIP_VERIFY:-0}" == 1 ]]; then
        return 0
    fi
    log "verify imports"
    if [[ $DRY_RUN -eq 1 ]]; then
        log "  DRY: would run import smoke test"
        return 0
    fi
    "$PYTHON" - <<'PY'
import importlib.metadata

import coincurve
from bsv import PrivateKey
import piwallet

cc_ver = importlib.metadata.version("coincurve")
print(f"coincurve {cc_ver}, bsv-sdk ok, piwallet {piwallet.__version__}")
PY
}

main() {
    log "repo=$REPO_ROOT venv=$VENV extras=$EXTRAS"
    create_venv_if_needed
    upgrade_pip_tooling

    if coincurve_pin_required; then
        install_with_coincurve_pin
    else
        install_standard
    fi

    verify_install
    log "done"
}

main "$@"
