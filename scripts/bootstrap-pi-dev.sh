#!/usr/bin/env bash
#
# bootstrap-pi-dev.sh — bring up a Raspberry Pi for PiWalletSV development,
# hardware checkpoint tests, or experimental 32-bit Pi Zero WH images.
#
# Run ON THE PI after syncing the repo from your workstation (rsync/scp).
# Idempotent where practical. Expect 1–3 reboots on a fresh SD card:
#   1) boot config (SPI + spidev buffer + camera overlay)
#   2) Adafruit raspi-blinka.py (if it asks)
#   3) raspi-spi-reassign.py (CE0/CE1 disabled for bonnet)
#
# Production sealed images use deploy/provision-pi.sh (32-bit Pi Zero W).
#
# Typical workflow (Mac → Pi):
#   rsync -av --delete \
#     --exclude .git --exclude .venv --exclude node_modules \
#     --exclude companion --exclude site --exclude hardware \
#     ./ pisv@piwalletsv32.local:~/PiWallet/
#   ssh pisv@piwalletsv32.local 'cd ~/PiWallet && bash scripts/bootstrap-pi-dev.sh'
#
# After the first reboot (or any time pip is already installed):
#   bash scripts/bootstrap-pi-dev.sh --resume
#
# Usage:
#   bash scripts/bootstrap-pi-dev.sh [options]
#
# Options:
#   --repo PATH            repo root (default: parent of scripts/)
#   --resume               skip apt, boot config, and venv (hardware + verify only)
#   --skip-apt             skip apt update/install
#   --skip-boot            skip config.txt / cmdline.txt edits
#   --skip-venv            skip venv + pip install
#   --skip-blinka          skip Adafruit raspi-blinka.py
#   --skip-spi-reassign    skip CE0/CE1 disable for bonnet SPI
#   --no-reboot            never reboot (print reminder instead)
#   --dry-run              print actions only
#
# Platform notes (Pi Zero WH 32-bit / armv6l):
#   * Pi OS Lite Trixie: apt package libzbar0t64 (not libzbar0).
#   * Venv uses --system-site-packages for apt picamera2/numpy.
#   * pip install -e ".[display,camera]" fails on armv6l — use install-piwallet-deps.sh.
#   * Include scripts/ in rsync; chmod is applied automatically here.
#   * Bonnet needs /dev/spidev0.0 — run this script (or enable SPI) before run_bonnet.sh.
set -euo pipefail

readonly LOG_PREFIX="[bootstrap-pi-dev]"
readonly BOOT_CFG="/boot/firmware/config.txt"
readonly CMDLINE="/boot/firmware/cmdline.txt"
readonly CMDLINE_LEGACY="/boot/cmdline.txt"
readonly SPI_BUFSIZ="spidev.bufsiz=131072"
readonly STATE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/piwallet-bootstrap"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_ROOT/.venv"
SKIP_APT=0
SKIP_BOOT=0
SKIP_VENV=0
SKIP_BLINKA=0
SKIP_SPI_REASSIGN=0
NO_REBOOT=0
DRY_RUN=0
NEEDS_REBOOT=0
RESUME=0

readonly APT_PACKAGES=(
    python3-pip
    python3-venv
    python3-dev
    build-essential
    pkg-config
    libffi-dev
    libsecp256k1-dev
    python3-picamera2
    python3-libcamera
    python3-pil
    python3-numpy
    libzbar0t64
    fonts-dejavu-core
    rpicam-apps
    curl
)

usage() {
    sed -n '2,44p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-2}"
}

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

mark_reboot() {
    NEEDS_REBOOT=1
}

login_user() {
    printf '%s' "${SUDO_USER:-$USER}"
}

venv_python() {
    printf '%s/bin/python' "$VENV"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)              REPO_ROOT=${2:?--repo requires a path}; shift ;;
        --repo=*)            REPO_ROOT=${1#--repo=} ;;
        --resume)            RESUME=1; SKIP_APT=1; SKIP_BOOT=1; SKIP_VENV=1 ;;
        --skip-apt)          SKIP_APT=1 ;;
        --skip-boot)         SKIP_BOOT=1 ;;
        --skip-venv)         SKIP_VENV=1 ;;
        --skip-blinka)       SKIP_BLINKA=1 ;;
        --skip-spi-reassign) SKIP_SPI_REASSIGN=1 ;;
        --no-reboot)         NO_REBOOT=1 ;;
        --dry-run)           DRY_RUN=1 ;;
        -h|--help)           usage 0 ;;
        *)                   echo "error: unknown arg '$1'" >&2; usage ;;
    esac
    shift
done

VENV="$REPO_ROOT/.venv"

[[ -f "$REPO_ROOT/pyproject.toml" ]] || fail "missing $REPO_ROOT/pyproject.toml"
[[ -f "$REPO_ROOT/scripts/install-piwallet-deps.sh" ]] || fail "missing install-piwallet-deps.sh"

preflight() {
    log "preflight"
    if [[ ! -r /proc/device-tree/model ]]; then
        fail "not a Raspberry Pi (missing /proc/device-tree/model)"
    fi
    local model user
    model="$(tr -d '\000' < /proc/device-tree/model)"
    user="$(login_user)"
    log "  model: $(uname -m) — $model"
    log "  user:  ${user:-unknown}"
    log "  repo:  $REPO_ROOT"
    log "  venv:  $VENV"
}

ensure_line() {
    local line=$1 file=$2
    if [[ -f "$file" ]] && grep -qxF "$line" "$file"; then
        return 0
    fi
    if [[ $DRY_RUN -eq 1 ]]; then
        log "DRY: append $(printf %q "$line") to $file"
        mark_reboot
        return 0
    fi
    printf '%s\n' "$line" | sudo_run tee -a "$file" >/dev/null
    mark_reboot
}

ensure_cmdline_flag() {
    local flag=$1
    local file=""
    if [[ -f "$CMDLINE" ]]; then
        file="$CMDLINE"
    elif [[ -f "$CMDLINE_LEGACY" ]]; then
        file="$CMDLINE_LEGACY"
    else
        fail "no cmdline.txt under /boot/firmware or /boot"
    fi
    if grep -q "$flag" "$file" 2>/dev/null; then
        log "cmdline already has $flag ($file)"
        return 0
    fi
    log "append $flag to $file (must stay one line)"
    if [[ $DRY_RUN -eq 1 ]]; then
        log "DRY: sed append to $file"
        mark_reboot
        return 0
    fi
    sudo_run sed -i "s|\$| ${flag}|" "$file"
    mark_reboot
}

spidev_present() {
    [[ -e /dev/spidev0.0 ]]
}

spidev_bufsiz_ok() {
    local bufsiz
    bufsiz="$(cat /sys/module/spidev/parameters/bufsiz 2>/dev/null || echo 0)"
    [[ "$bufsiz" == "131072" ]]
}

blinka_ready() {
    [[ -x "$(venv_python)" ]] || return 1
    "$(venv_python)" -c "import board" 2>/dev/null
}

spi_reassign_done() {
    [[ -f "$STATE_DIR/spi-reassign.done" ]]
}

print_status() {
    log "status"
    if spidev_present; then
        log "  SPI device:     /dev/spidev0.0 ok"
    else
        warn "  SPI device:     /dev/spidev0.0 MISSING"
    fi
    if spidev_bufsiz_ok; then
        log "  spidev bufsiz:  131072 ok"
    else
        local bufsiz
        bufsiz="$(cat /sys/module/spidev/parameters/bufsiz 2>/dev/null || echo unknown)"
        warn "  spidev bufsiz:  $bufsiz (want 131072)"
    fi
    if blinka_ready; then
        log "  Blinka:         board module ok"
    else
        warn "  Blinka:         not ready (run raspi-blinka.py)"
    fi
    if spi_reassign_done; then
        log "  SPI reassign:   done ($(cat "$STATE_DIR/spi-reassign.done" 2>/dev/null || echo marker))"
    else
        warn "  SPI reassign:   not done (CE0/CE1 still kernel-managed)"
    fi
    if [[ -x "$VENV/bin/piwallet" ]]; then
        log "  piwallet CLI:   installed"
    else
        warn "  piwallet CLI:   missing (run without --skip-venv)"
    fi
}

print_resume_hint() {
    cat <<EOF

Re-run after reboot:
  cd $REPO_ROOT
  bash scripts/bootstrap-pi-dev.sh --resume

Or step by step:
  bash scripts/bootstrap-pi-dev.sh --resume --skip-spi-reassign   # Blinka only
  bash scripts/bootstrap-pi-dev.sh --resume --skip-blinka       # SPI reassign only

EOF
}

reboot_now() {
    if [[ $NO_REBOOT -eq 1 || $DRY_RUN -eq 1 ]]; then
        warn "reboot required — run: sudo reboot"
        print_resume_hint
        return 0
    fi
    log "rebooting..."
    sudo_run reboot
}

# Stop before bonnet hardware steps if SPI nodes are not up yet but boot
# config changed this run (or buffer/cmdline still wrong).
gate_hardware_steps() {
    if spidev_present && spidev_bufsiz_ok; then
        return 0
    fi
    if [[ $NEEDS_REBOOT -eq 1 ]]; then
        log "boot config changed — reboot before Blinka / bonnet steps"
        print_resume_hint
        reboot_now
        exit 0
    fi
    if ! spidev_present; then
        fail "/dev/spidev0.0 missing. Enable SPI: sudo raspi-config nonint do_spi 0 ; grep dtparam=spi=on $BOOT_CFG ; sudo reboot"
    fi
    if ! spidev_bufsiz_ok; then
        fail "spidev buffer not 131072 — add $SPI_BUFSIZ to cmdline.txt and reboot"
    fi
}

step_apt() {
    if [[ $SKIP_APT -eq 1 ]]; then
        log "apt: SKIPPED"
        return 0
    fi
    log "apt install runtime packages"
    sudo_run apt-get update -qq
    sudo_run env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        "${APT_PACKAGES[@]}"
}

step_spi_enable() {
    if [[ $SKIP_BOOT -eq 1 ]]; then
        return 0
    fi
    log "enable SPI (raspi-config)"
    if [[ $DRY_RUN -eq 1 ]]; then
        log "DRY: raspi-config nonint do_spi 0"
        mark_reboot
        return 0
    fi
    if command -v raspi-config >/dev/null 2>&1; then
        sudo_run raspi-config nonint do_spi 0
        mark_reboot
    else
        warn "raspi-config not found; ensure dtparam=spi=on in $BOOT_CFG"
    fi
}

step_boot_config() {
    if [[ $SKIP_BOOT -eq 1 ]]; then
        log "boot config: SKIPPED"
        return 0
    fi
    log "boot config: SPI, buffer, OV5647 camera overlay"
    [[ -f "$BOOT_CFG" ]] || fail "$BOOT_CFG missing"

    ensure_cmdline_flag "$SPI_BUFSIZ"
    ensure_line "dtparam=spi=on" "$BOOT_CFG"
    ensure_line "dtparam=i2c_arm=on" "$BOOT_CFG"
    ensure_line "camera_auto_detect=0" "$BOOT_CFG"
    ensure_line "dtoverlay=ov5647" "$BOOT_CFG"
}

step_user_groups() {
    log "ensure user is in spi,gpio,video,i2c,dialout"
    local user
    user="$(login_user)"
    if [[ -z "$user" || "$user" == root ]]; then
        warn "could not determine login user — run: sudo usermod -aG spi,gpio,video,i2c,dialout \$USER"
        return 0
    fi
    if [[ $DRY_RUN -eq 1 ]]; then
        log "DRY: usermod -aG spi,gpio,video,i2c,dialout $user"
        return 0
    fi
    sudo_run usermod -aG spi,gpio,video,i2c,dialout "$user"
    if ! id -nG "$user" | tr ' ' '\n' | grep -qx spi; then
        warn "log out and back in (or reboot) for group membership to apply"
    fi
}

step_script_perms() {
    log "make scripts/*.sh and scripts/*.py executable"
    if [[ $DRY_RUN -eq 1 ]]; then
        return 0
    fi
    run chmod +x "$REPO_ROOT"/scripts/*.sh 2>/dev/null || true
    run chmod +x "$REPO_ROOT"/scripts/*.py 2>/dev/null || true
    run chmod +x "$REPO_ROOT"/scripts/setup-bonnet-hardware.sh 2>/dev/null || true
}

step_venv() {
    if [[ $SKIP_VENV -eq 1 ]]; then
        log "venv/pip: SKIPPED"
        return 0
    fi
    log "venv + pip install"
    if [[ $DRY_RUN -eq 1 ]]; then
        log "DRY: install-piwallet-deps.sh --create-venv"
        return 0
    fi
    bash "$REPO_ROOT/scripts/install-piwallet-deps.sh" \
        --repo "$REPO_ROOT" \
        --venv "$VENV" \
        --create-venv
}

step_bonnet_hardware() {
    if [[ $SKIP_BLINKA -eq 1 && $SKIP_SPI_REASSIGN -eq 1 ]]; then
        log "bonnet hardware setup: SKIPPED"
        return 0
    fi
    [[ -x "$(venv_python)" ]] || fail "venv missing at $VENV — run without --skip-venv first"

    local hw_args=(--repo "$REPO_ROOT" --venv "$VENV")
    [[ $SKIP_BLINKA -eq 1 ]] && hw_args+=(--skip-blinka)
    [[ $SKIP_SPI_REASSIGN -eq 1 ]] && hw_args+=(--skip-spi-reassign)
    [[ $DRY_RUN -eq 1 ]] && hw_args+=(--dry-run)

    log "bonnet hardware (Blinka + SPI CE reassign)"
    set +e
    bash "$REPO_ROOT/scripts/setup-bonnet-hardware.sh" "${hw_args[@]}"
    local hw_rc=$?
    set -e
    if [[ $hw_rc -eq 2 ]]; then
        mark_reboot
    elif [[ $hw_rc -ne 0 ]]; then
        fail "setup-bonnet-hardware.sh failed (exit $hw_rc)"
    fi
}

mark_bootstrap_complete() {
    if [[ $DRY_RUN -eq 1 ]]; then
        return 0
    fi
    if spidev_present && spidev_bufsiz_ok && blinka_ready && spi_reassign_done \
        && [[ -x "$VENV/bin/piwallet" ]]; then
        run mkdir -p "$STATE_DIR"
        run date -Iseconds > "$STATE_DIR/complete.done"
        log "bootstrap complete ($(cat "$STATE_DIR/complete.done"))"
    fi
}

step_verify() {
    log "verify"
    if [[ $DRY_RUN -eq 1 ]]; then
        return 0
    fi

    print_status

    if [[ -x "$VENV/bin/piwallet" ]]; then
        "$VENV/bin/piwallet" --help >/dev/null
    fi

    if command -v rpicam-hello >/dev/null 2>&1; then
        if rpicam-hello --list-cameras 2>/dev/null | grep -qi ov5647; then
            log "  camera: ov5647 listed by rpicam-hello"
        else
            warn "  camera: ov5647 not listed — check CSI cable and boot overlay"
        fi
    fi

    if spidev_present && blinka_ready && spi_reassign_done; then
        log "bonnet hardware path: ready for display demo / run_bonnet.sh"
    elif spidev_present && blinka_ready; then
        warn "bonnet: run SPI reassign (bootstrap without --skip-spi-reassign) then reboot"
    elif spidev_present; then
        warn "bonnet: run Blinka step (bootstrap --resume --skip-spi-reassign)"
    fi
}

print_next_steps() {
    cat <<EOF

Smoke tests (use venv wrappers — do not use system python3):
  ./scripts/run_display_demo.sh
  ./scripts/run_camera_qr_test.sh --once
  .venv/bin/piwallet vault init
  ./scripts/run_bonnet.sh

Always activate the venv for ad-hoc commands:
  source .venv/bin/activate

EOF
}

main() {
    log "starting${RESUME:+ (resume mode)}"
    preflight
    print_status
    step_apt
    step_spi_enable
    step_boot_config
    step_user_groups
    step_venv
    step_script_perms
    gate_hardware_steps
    step_bonnet_hardware
    step_verify
    mark_bootstrap_complete
    log "done"
    print_next_steps

    if [[ $NEEDS_REBOOT -eq 1 ]]; then
        warn "changes need a reboot"
        print_resume_hint
        reboot_now
    fi
}

main "$@"
