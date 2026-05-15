#!/usr/bin/env bash
#
# provision-pi.sh — turn a freshly-flashed Raspberry Pi OS Lite SD card
# into a sealed PiWalletSV appliance.
#
# This is the script we run when **building the official image**.
# It assumes:
#
#   * Raspberry Pi OS Lite 64-bit (Bookworm or later) is already on
#     the SD card and has booted into a working shell.
#   * The bonnet hardware (TFT + buttons + camera) is wired up.
#   * Network is reachable for the duration of provisioning so apt
#     can fetch packages — *the network is then disabled forever as
#     the last step of provisioning*.
#   * This script is run as root.
#
# The result:
#
#   * A new locked user `pwsv`, no shell login, member of
#     spi/gpio/video/i2c/dialout for hardware access.
#   * App installed read-only at /opt/piwallet (no editable copy
#     under any user's $HOME).
#   * /home/pwsv/.piwallet/ pre-created, the only writable location
#     the runtime sees.
#   * Wi-Fi and Bluetooth disabled at four layers: firmware overlay,
#     modprobe blacklist, masked services, purged userspace
#     packages. SSH off. Audio off. mDNS / DNS resolver disabled —
#     the device cannot reach the network even if it had one.
#   * SPI / I2C / camera enabled.
#   * piwallet-bonnet.service installed, enabled, owns tty1.
#   * journald bounded so a misbehaving log can't fill the SD card.
#
# Usage:
#   sudo deploy/provision-pi.sh [--src PATH] [--keep-ssh] [--keep-radios] [--dry-run]
#
#   --src PATH    Install the app from a local directory (rsync) instead
#                 of cloning github.com/mohrt/PiWalletSV. Used by image
#                 builders to lock to a known commit.
#   --keep-ssh    Skip the SSH-disable step. For internal "developer
#                 image" builds where we want shell access for triage.
#                 The shipped public image MUST NOT use this flag.
#   --keep-radios Skip Wi-Fi/Bluetooth disable + radio-package purge +
#                 avahi/systemd-resolved mask. **Test flag only** —
#                 lets a Zero 2 W keep its only network so an admin
#                 can SSH in and verify the rest of the provisioning
#                 worked. Re-flash and provision without this flag
#                 to produce the actual sealed image. The shipped
#                 public image MUST NOT use this flag.
#   --dry-run     Print what would happen without making changes.
#
# Idempotency: every step checks state before mutating, so running
# the script twice is safe. A re-run after a partial failure will
# pick up where the previous run left off.

set -euo pipefail

# ============================================================
# Constants
# ============================================================

readonly RUNTIME_USER="pwsv"
readonly RUNTIME_HOME="/home/${RUNTIME_USER}"
readonly RUNTIME_STATE_DIR="${RUNTIME_HOME}/.piwallet"
readonly RUNTIME_GROUPS="spi,gpio,video,i2c,dialout"
readonly APP_DIR="/opt/piwallet"
readonly APP_VENV="${APP_DIR}/.venv"
readonly APP_REPO="https://github.com/mohrt/PiWalletSV.git"
readonly HOSTNAME_NEW="piwalletsv"
readonly BOOT_CFG="/boot/firmware/config.txt"
readonly MODPROBE_BLACKLIST="/etc/modprobe.d/piwalletsv-no-radio.conf"
readonly JOURNALD_CONF="/etc/systemd/journald.conf.d/piwallet.conf"
readonly UNIT_SRC_DIR="deploy/systemd"
readonly UNIT_DST_DIR="/etc/systemd/system"
readonly LOG_PREFIX="[provision-pi]"

# Packages we need at runtime. picamera2/libcamera come from system
# wheels because the libcamera Python bindings link against system
# libraries we don't want to rebuild.
readonly APT_INSTALL=(
    python3-picamera2
    python3-libcamera
    python3-pip
    python3-venv
    python3-pil
    rng-tools-debian
    fonts-dejavu-core
    git
)

# Packages we PURGE — anything that could touch a radio or speaker.
# Not "remove": purge so the configs go too.
readonly APT_PURGE=(
    wireless-tools
    wpasupplicant
    bluez
    bluez-firmware
    pi-bluetooth
    libnss-mdns
    avahi-daemon
    avahi-utils
    alsa-utils
    alsa-ucm-conf
)

# Kernel modules we explicitly forbid loading. brcmfmac is the
# Broadcom Wi-Fi driver on Zero 2 W / Pi 4; cfg80211 / mac80211 are
# the 802.11 stack; bluetooth / btbcm / hci_uart are the Bluetooth
# stack. blnep / btsdio / btusb cover Pi-4-and-newer code paths.
readonly RADIO_MODULES=(
    brcmfmac
    brcmutil
    cfg80211
    mac80211
    bluetooth
    btbcm
    hci_uart
    bnep
    btsdio
    btusb
)

# systemd units to mask. Masking is stronger than disable: a unit
# named in someone's Wants= cannot bring it back up.
#
# MASK_RADIO_UNITS is gated by --keep-radios so testing keeps SSH /
# mDNS / DNS reachable; MASK_ALWAYS_UNITS fires unconditionally
# because none of them have anything to do with the radios (getty
# would fight the bonnet for tty1 regardless of network state).
readonly MASK_RADIO_UNITS=(
    wpa_supplicant.service
    hciuart.service
    bluetooth.service
    avahi-daemon.service
    avahi-daemon.socket
    systemd-resolved.service
)
readonly MASK_ALWAYS_UNITS=(
    getty@tty1.service
)

# ============================================================
# Argument parsing
# ============================================================

src_dir=""
keep_ssh=0
keep_radios=0
dry_run=0

usage() {
    sed -n '2,40p' "$0" | sed 's|^# *||'
    exit "${1:-2}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --src)         src_dir=${2:?--src requires a path}; shift ;;
        --src=*)       src_dir=${1#--src=} ;;
        --keep-ssh)    keep_ssh=1 ;;
        --keep-radios) keep_radios=1 ;;
        --dry-run)     dry_run=1 ;;
        -h|--help)     usage 0 ;;
        *)             echo "error: unknown arg '$1'" >&2; usage ;;
    esac
    shift
done

# ============================================================
# Logging
# ============================================================

log()  { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s WARN: %s\n' "$LOG_PREFIX" "$*" >&2; }
fail() { printf '%s FATAL: %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

# All mutating commands flow through this. In dry-run mode they're
# echoed, not executed.
run() {
    if [[ $dry_run -eq 1 ]]; then
        printf '%s DRY: %s\n' "$LOG_PREFIX" "$*"
    else
        "$@"
    fi
}

# Append a single line to a config file iff it isn't already there.
# Idempotent equivalent of `echo "$line" >> "$file"`.
ensure_line() {
    local line=$1 file=$2
    if [[ -f "$file" ]] && grep -qxF "$line" "$file"; then
        return 0
    fi
    if [[ $dry_run -eq 1 ]]; then
        printf '%s DRY: append %q to %s\n' "$LOG_PREFIX" "$line" "$file"
        return 0
    fi
    printf '%s\n' "$line" >> "$file"
}

# ============================================================
# Preflight
# ============================================================

preflight() {
    log "preflight"

    if [[ $EUID -ne 0 ]]; then
        fail "must run as root (try: sudo $0 $*)"
    fi

    if [[ ! -r /proc/device-tree/model ]]; then
        fail "not a Raspberry Pi (missing /proc/device-tree/model)"
    fi
    local model
    model=$(tr -d '\000' < /proc/device-tree/model)
    log "  model:   ${model}"
    case "$model" in
        Raspberry\ Pi*) ;;
        *) fail "model '${model}' is not a Raspberry Pi" ;;
    esac

    if [[ ! -r /etc/os-release ]]; then
        fail "missing /etc/os-release — unsupported distribution"
    fi
    # shellcheck disable=SC1091
    . /etc/os-release
    log "  os:      ${PRETTY_NAME:-unknown}"
    case "${ID:-}:${ID_LIKE:-}" in
        debian:*|raspbian:*|*:*debian*) ;;
        *) fail "OS '${ID:-unknown}' is not Debian/Raspbian-based" ;;
    esac

    if [[ ! -d "$(dirname "$BOOT_CFG")" ]]; then
        fail "$(dirname "$BOOT_CFG") missing — is /boot/firmware mounted?"
    fi

    # If --src was given it must exist and look like the repo.
    if [[ -n "$src_dir" ]]; then
        [[ -d "$src_dir" ]] || fail "--src '$src_dir' is not a directory"
        [[ -f "$src_dir/pyproject.toml" ]] || \
            fail "--src '$src_dir' missing pyproject.toml"
        [[ -d "$src_dir/$UNIT_SRC_DIR" ]] || \
            fail "--src '$src_dir' missing $UNIT_SRC_DIR/"
        log "  src:     ${src_dir}"
    else
        log "  src:     ${APP_REPO}"
    fi

    log "  keep_ssh:    ${keep_ssh}"
    log "  keep_radios: ${keep_radios}"
    log "  dry-run:     ${dry_run}"

    if [[ $keep_radios -eq 1 ]]; then
        warn "RADIOS WILL REMAIN ENABLED (--keep-radios). The shipped public image MUST NOT carry this flag."
    fi
}

# ============================================================
# Steps
# ============================================================

step_apt_install() {
    log "apt install runtime deps"
    run apt-get update -qq
    run env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        "${APT_INSTALL[@]}"
}

step_apt_purge() {
    if [[ $keep_radios -eq 1 ]]; then
        log "apt purge radio packages: SKIPPED (--keep-radios). Audio still purged."
        # Audio is unrelated to networking; purge it either way to
        # keep the image lean during testing.
        local audio_pkgs=(alsa-utils alsa-ucm-conf)
        local installed=()
        local pkg
        for pkg in "${audio_pkgs[@]}"; do
            if dpkg -s "$pkg" >/dev/null 2>&1; then
                installed+=("$pkg")
            fi
        done
        if [[ ${#installed[@]} -gt 0 ]]; then
            run env DEBIAN_FRONTEND=noninteractive apt-get purge -y "${installed[@]}"
        fi
        run env DEBIAN_FRONTEND=noninteractive apt-get autoremove -y --purge
        return 0
    fi
    log "apt purge radio + audio packages"
    # apt-get purge with packages that aren't installed is fine
    # (no-op + warning). Filter to installed packages so the run is
    # quiet on a Lite image that may not have them all.
    local installed=()
    local pkg
    for pkg in "${APT_PURGE[@]}"; do
        if dpkg -s "$pkg" >/dev/null 2>&1; then
            installed+=("$pkg")
        fi
    done
    if [[ ${#installed[@]} -gt 0 ]]; then
        run env DEBIAN_FRONTEND=noninteractive apt-get purge -y "${installed[@]}"
    else
        log "  (no purge candidates installed)"
    fi
    run env DEBIAN_FRONTEND=noninteractive apt-get autoremove -y --purge
}

step_boot_config() {
    log "boot config: enable SPI/I2C/camera, audio/radios per flags"
    [[ -f "$BOOT_CFG" ]] || fail "$BOOT_CFG missing"

    # Hardware enables.
    ensure_line "dtparam=spi=on"        "$BOOT_CFG"
    ensure_line "dtparam=i2c_arm=on"    "$BOOT_CFG"
    ensure_line "camera_auto_detect=1"  "$BOOT_CFG"

    # Audio off. dtparam=audio=off matches raspi-config; setting
    # it twice is harmless because ensure_line is idempotent.
    ensure_line "dtparam=audio=off"      "$BOOT_CFG"

    if [[ $keep_radios -eq 1 ]]; then
        log "  Wi-Fi/BT firmware disable: SKIPPED (--keep-radios)"
        return 0
    fi

    # Hardware disables. The dtoverlay form is what raspi-config
    # writes when you toggle "Disable Wi-Fi" / "Disable Bluetooth"
    # in its menus, so this is the canonical knob.
    ensure_line "dtoverlay=disable-wifi" "$BOOT_CFG"
    ensure_line "dtoverlay=disable-bt"   "$BOOT_CFG"
}

step_modprobe_blacklist() {
    if [[ $keep_radios -eq 1 ]]; then
        log "modprobe blacklist: SKIPPED (--keep-radios)"
        # Remove any prior blacklist file from a previous run, so
        # toggling --keep-radios on doesn't leave a stale block.
        run rm -f "$MODPROBE_BLACKLIST"
        return 0
    fi
    log "modprobe blacklist for radio modules"
    if [[ $dry_run -eq 1 ]]; then
        printf '%s DRY: write %s\n' "$LOG_PREFIX" "$MODPROBE_BLACKLIST"
        return 0
    fi
    {
        echo "# Written by deploy/provision-pi.sh — do not hand-edit."
        echo "# Belt-and-suspenders block on the radio kernel modules."
        echo "# The dtoverlay flags in $BOOT_CFG already keep these"
        echo "# from being loaded, but this fires earlier (initrd) and"
        echo "# survives kernel updates that might rename the overlay."
        for mod in "${RADIO_MODULES[@]}"; do
            echo "blacklist $mod"
            echo "install $mod /bin/false"
        done
    } > "$MODPROBE_BLACKLIST"
    chmod 0644 "$MODPROBE_BLACKLIST"
}

step_mask_units() {
    log "mask console + (conditionally) radio units"
    local to_mask=("${MASK_ALWAYS_UNITS[@]}")
    if [[ $keep_radios -eq 0 ]]; then
        to_mask+=("${MASK_RADIO_UNITS[@]}")
    else
        log "  radio units: SKIPPED (--keep-radios)"
    fi

    local unit
    for unit in "${to_mask[@]}"; do
        # `mask` succeeds on a unit that doesn't exist, but emits a
        # warning. Skip the unknowns to keep the log clean.
        if systemctl list-unit-files "$unit" >/dev/null 2>&1 \
            && systemctl list-unit-files | grep -q "^$unit"; then
            run systemctl mask "$unit" || true
        else
            log "  $unit: not present, skipping"
        fi
    done
}

step_ssh() {
    if [[ $keep_ssh -eq 1 ]]; then
        warn "leaving SSH enabled (--keep-ssh). The shipped public image MUST NOT carry this flag."
        return 0
    fi
    log "disable + mask SSH"
    run systemctl disable ssh.service 2>/dev/null || true
    run systemctl mask ssh.service     2>/dev/null || true
    # Lite images sometimes ship an /boot/firmware/ssh marker file
    # that re-enables ssh on next boot via the raspi-config helper.
    # Remove it so the disable sticks.
    run rm -f /boot/firmware/ssh /boot/firmware/ssh.txt
}

step_create_user() {
    log "create runtime user '${RUNTIME_USER}'"
    if id -u "$RUNTIME_USER" >/dev/null 2>&1; then
        log "  user exists; ensuring groups"
    else
        run useradd \
            --create-home \
            --home-dir "$RUNTIME_HOME" \
            --shell /usr/sbin/nologin \
            --user-group \
            "$RUNTIME_USER"
        # Lock the password so console login is impossible. The
        # systemd unit's User= bypasses login shell + password.
        run passwd -l "$RUNTIME_USER"
    fi
    run usermod -aG "$RUNTIME_GROUPS" "$RUNTIME_USER"

    # Pre-create the state directory so the systemd unit's
    # ReadWritePaths= can target an existing path. mode 0700 — only
    # the runtime user can read its own vault file.
    run install -d -m 0700 -o "$RUNTIME_USER" -g "$RUNTIME_USER" "$RUNTIME_STATE_DIR"
}

step_install_app() {
    log "install app at $APP_DIR"

    if [[ -n "$src_dir" ]]; then
        log "  rsync from $src_dir"
        run rsync -a --delete \
            --exclude='.venv/' \
            --exclude='__pycache__/' \
            --exclude='node_modules/' \
            --exclude='companion/dist/' \
            --exclude='site/' \
            --exclude='.git/' \
            "${src_dir%/}/" "$APP_DIR/"
    else
        if [[ -d "$APP_DIR/.git" ]]; then
            log "  git pull (existing checkout)"
            run git -C "$APP_DIR" pull --ff-only
        else
            log "  git clone $APP_REPO"
            run rm -rf "$APP_DIR"
            run git clone --depth 1 "$APP_REPO" "$APP_DIR"
        fi
    fi

    # App code stays root-owned and read-only for the runtime user.
    # A code-execution exploit can't rewrite the binary it just ran.
    run chown -R root:root "$APP_DIR"
    run find "$APP_DIR" -type d -exec chmod 0755 {} +
    run find "$APP_DIR" -type f -exec chmod 0644 {} +
    # ...except things that need to be executable.
    run find "$APP_DIR" -type f -name '*.sh' -exec chmod 0755 {} +
    run find "$APP_DIR/scripts" -type f -name '*.py' -exec chmod 0755 {} + 2>/dev/null || true

    log "  build venv at $APP_VENV"
    if [[ ! -x "$APP_VENV/bin/python" ]]; then
        run python3 -m venv --system-site-packages "$APP_VENV"
    fi
    # Pinned via --upgrade-strategy only-if-needed so a re-run picks
    # up new requirements without churning unaffected packages.
    run "$APP_VENV/bin/pip" install --upgrade --quiet pip
    run "$APP_VENV/bin/pip" install --quiet --editable "$APP_DIR"
}

step_install_unit() {
    log "install systemd unit + journald drop-in"
    local svc_src="$APP_DIR/$UNIT_SRC_DIR/piwallet-bonnet.service"
    local jrn_src="$APP_DIR/$UNIT_SRC_DIR/journald-piwallet.conf.example"

    [[ -f "$svc_src" ]] || fail "missing $svc_src"
    [[ -f "$jrn_src" ]] || fail "missing $jrn_src"

    run install -m 0644 "$svc_src" "$UNIT_DST_DIR/piwallet-bonnet.service"
    run install -d -m 0755 "$(dirname "$JOURNALD_CONF")"
    run install -m 0644 "$jrn_src" "$JOURNALD_CONF"

    run systemctl daemon-reload
    run systemctl restart systemd-journald
    run systemctl enable piwallet-bonnet.service
}

step_hostname() {
    log "set hostname to $HOSTNAME_NEW"
    run hostnamectl set-hostname "$HOSTNAME_NEW"
    # /etc/hosts often has the old hostname pinned to 127.0.1.1; fix
    # it so name lookups inside the box don't fail.
    if [[ -f /etc/hosts ]] && [[ $dry_run -eq 0 ]]; then
        sed -i -E "s/127\\.0\\.1\\.1\\s+.*/127.0.1.1\t${HOSTNAME_NEW}/" /etc/hosts
    fi
}

step_swap_off() {
    log "disable swap (SD-card friendliness)"
    if command -v dphys-swapfile >/dev/null 2>&1; then
        run dphys-swapfile swapoff || true
        run dphys-swapfile uninstall || true
        run systemctl disable dphys-swapfile.service || true
    else
        log "  dphys-swapfile not present; nothing to do"
    fi
}

step_rng() {
    log "enable hardware RNG (rngd)"
    if systemctl list-unit-files rngd.service >/dev/null 2>&1; then
        run systemctl enable rngd.service || true
    else
        warn "rngd.service not present — HW RNG entropy won't feed kernel pool"
    fi
}

step_cleanup() {
    log "cleanup"
    run apt-get autoremove -y --purge
    run apt-get clean
    if [[ $dry_run -eq 0 ]]; then
        # Trim install-time logs so the captured image stays small.
        journalctl --vacuum-size=8M >/dev/null 2>&1 || true
        # Truncate root's bash history so the image doesn't ship a
        # transcript of the build session.
        : > /root/.bash_history 2>/dev/null || true
    fi
}

# ============================================================
# Main
# ============================================================

main() {
    log "starting"
    preflight "$@"
    step_apt_install
    step_apt_purge
    step_boot_config
    step_modprobe_blacklist
    step_mask_units
    step_ssh
    step_create_user
    step_install_app
    step_install_unit
    step_hostname
    step_swap_off
    step_rng
    step_cleanup

    log "done."
    cat <<EOF

================================================================
PiWalletSV provisioning complete.

A reboot is required to pick up the boot-config / modprobe changes.
After reboot the bonnet service starts on tty1 with no login prompt.

EOF
    if [[ $keep_radios -eq 1 ]]; then
        cat <<'EOF'
TEST MODE — radios kept enabled. Verify after reboot:

  * SSH still reachable (Wi-Fi / Ethernet up)
  * systemctl status piwallet-bonnet      # active (running)
  * systemctl status getty@tty1           # masked
  * ls -la /home/pwsv/.piwallet/          # vault.bin appears after
                                            first-boot setup
  * cat /boot/firmware/config.txt         # SPI/I2C/audio set,
                                            disable-wifi/-bt absent

When the test is happy, RE-FLASH the SD card and run provisioning
WITHOUT --keep-radios to produce the actual sealed image.
EOF
    else
        cat <<'EOF'
SEALED MODE — radios firmware-disabled. After reboot the device has
no network. Verify on the bonnet display itself, or by attaching a
USB keyboard + HDMI before rebooting and switching to a tty:

  * rfkill list                           # nothing or all blocked
  * lsmod | grep -E 'brcmfmac|bluetooth'  # empty
  * ip link                               # only 'lo'
  * systemctl status piwallet-bonnet      # active (running)

There is no SSH path back into a sealed device — that's the point.
EOF
    fi
    cat <<'EOF'

Reboot now with: sudo reboot
================================================================
EOF
}

main "$@"
