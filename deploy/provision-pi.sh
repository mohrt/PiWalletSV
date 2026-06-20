#!/usr/bin/env bash
#
# provision-pi.sh — turn a freshly-flashed Raspberry Pi OS Lite SD card
# into a sealed PiWalletSV appliance.
#
# This is the script we run when **building the official image**.
# It assumes:
#
#   * Raspberry Pi OS Lite **32-bit** (Bookworm or Trixie) on the SD
#     card, booted into a working shell. Primary target: **Pi Zero W /
#     Zero WH** (ARMv6). Pi Zero 2 W (64-bit) is also supported.
#   * The bonnet hardware (TFT + buttons + camera) is wired up.
#   * Network is reachable for the duration of provisioning so apt
#     can fetch packages. Radio *packages* are purged on first boot
#     after seal (not over a live Wi-Fi SSH session — see
#     deploy/purge-radio-packages.sh).
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
#     modprobe blacklist, masked services, and (on first boot after
#     seal) purged userspace packages. SSH off. Audio off.
#   * SPI / I2C / camera enabled.
#   * piwallet-bonnet.service installed, enabled, owns tty1.
#   * journald bounded so a misbehaving log can't fill the SD card.
#   * Sealed builds (no --keep-ssh / --keep-radios) scrub Imager
#     Wi-Fi/cloud-init network artifacts from the boot partition and
#     rootfs. The Imager login user (e.g. pisv) is kept for local
#     HDMI/keyboard troubleshooting; SSH stays off and radios stay off.
#
# Usage:
#   sudo deploy/provision-pi.sh [--src PATH] [--release-version VER]
#                 [--image-channel CH] [--keep-ssh] [--keep-radios]
#                 [--local] [--dry-run]
#
#   --release-version VER   Baked into /etc/piwalletsv-release (default:
#                           PIWALLETSV_RELEASE_VERSION or 0.1.0-r3).
#   --image-channel CH      Image channel label (default:
#                           PIWALLETSV_IMAGE_CHANNEL or round1-zero-w).
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
#   --local       Force radio package purge to run inline now even when
#                 SSH_CONNECTION is set in the environment. Use this when
#                 provisioning from tty2/HDMI on a Pi that was previously
#                 accessed via SSH (sudo can inherit SSH_CONNECTION). For
#                 image-capture builds where first-boot radio purge would
#                 add 30–120 s to the end-user boot experience.
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
readonly RUNTIME_GROUPS="spi,gpio,video,i2c,dialout,render"
readonly APP_DIR="/opt/piwallet"
readonly APP_VENV="${APP_DIR}/.venv"
readonly APP_REPO="https://github.com/mohrt/PiWalletSV.git"
readonly HOSTNAME_NEW="piwalletsv"
readonly BOOT_CFG="/boot/firmware/config.txt"
readonly CMDLINE="/boot/firmware/cmdline.txt"
readonly CMDLINE_LEGACY="/boot/cmdline.txt"
readonly SPI_BUFSIZ="spidev.bufsiz=131072"
readonly MODPROBE_BLACKLIST="/etc/modprobe.d/piwalletsv-no-radio.conf"
readonly JOURNALD_CONF="/etc/systemd/journald.conf.d/piwallet.conf"
readonly UNIT_SRC_DIR="deploy/systemd"
readonly UNIT_DST_DIR="/etc/systemd/system"
readonly RELEASE_FILE="/etc/piwalletsv-release"
readonly RELEASE_JSON="${APP_DIR}/RELEASE.json"

# Packages we need at runtime. picamera2/libcamera come from system
# wheels because the libcamera Python bindings link against system
# libraries we don't want to rebuild.
readonly APT_INSTALL=(
    python3-picamera2
    python3-libcamera
    python3-pip
    python3-venv
    python3-pil
    python3-numpy
    libzbar0t64
    rng-tools-debian
    fonts-dejavu-core
    dosfstools
    exfatprogs
    git
    curl
    pkg-config
    libffi-dev
    libsecp256k1-dev
    # Build toolchain for C extensions pulled in by adafruit-blinka:
    # RPi.GPIO and rpi-ws281x ship sdists only (no Python 3.13 wheels
    # for aarch64 yet), so pip needs python3-dev headers + a compiler.
    # Without these, `pip install '.[display]'` fails with "Failed
    # building wheel for RPi.GPIO" and the bonnet silently falls back
    # to HeadlessDisplay at boot (panel stays blank, no error visible).
    python3-dev
    build-essential
    # lgpio bindings so Blinka uses gpiochip nodes instead of /dev/mem.
    python3-rpi-lgpio
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
    NetworkManager.service
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
release_version="${PIWALLETSV_RELEASE_VERSION:-0.1.0-r3}"
image_channel="${PIWALLETSV_IMAGE_CHANNEL:-round1-zero-w}"
keep_ssh=0
keep_radios=0
dry_run=0
local_provision=0  # force inline radio purge even when SSH_CONNECTION is set

usage() {
    sed -n '2,40p' "$0" | sed 's|^# *||'
    exit "${1:-2}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --src)         src_dir=${2:?--src requires a path}; shift ;;
        --src=*)       src_dir=${1#--src=} ;;
        --release-version) release_version=${2:?--release-version requires a value}; shift ;;
        --release-version=*) release_version=${1#--release-version=} ;;
        --image-channel) image_channel=${2:?--image-channel requires a value}; shift ;;
        --image-channel=*) image_channel=${1#--image-channel=} ;;
        --keep-ssh)    keep_ssh=1 ;;
        --keep-radios) keep_radios=1 ;;
        --local)       local_provision=1 ;;
        --dry-run)     dry_run=1 ;;
        -h|--help)     usage 0 ;;
        *)             echo "error: unknown arg '$1'" >&2; usage ;;
    esac
    shift
done

# ============================================================
# Logging
# ============================================================

readonly LOG_PREFIX="[provision-pi]"

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

# Set or replace a single key=value line in config.txt (last key wins in
# firmware parser — do not leave duplicate camera_auto_detect= entries).
set_boot_config_key() {
    local key=$1 value=$2 file=$3
    if [[ ! -f "$file" ]]; then
        return 0
    fi
    if [[ $dry_run -eq 1 ]]; then
        printf '%s DRY: set %s=%s in %s\n' "$LOG_PREFIX" "$key" "$value" "$file"
        return 0
    fi
    sed -i "/^${key}=/d" "$file"
    printf '%s=%s\n' "$key" "$value" >> "$file"
}

# Remove an exact line from config.txt if present (idempotent).
remove_boot_config_line() {
    local line=$1 file=$2
    if [[ ! -f "$file" ]]; then
        return 0
    fi
    if [[ $dry_run -eq 1 ]]; then
        printf '%s DRY: remove %q from %s\n' "$LOG_PREFIX" "$line" "$file"
        return 0
    fi
    sed -i "/^$(printf '%s' "$line" | sed 's/[[\.*^$()+?{|]/\\&/g')$/d" "$file"
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
    log "  local:       ${local_provision}"
    log "  release:     ${release_version} (${image_channel})"
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
    local zbar_pkg=libzbar0t64
    if ! apt-cache show "$zbar_pkg" >/dev/null 2>&1; then
        zbar_pkg=libzbar0
    fi
    log "  zbar package: ${zbar_pkg}"
    run apt-get update -qq
    local pkgs=()
    local pkg
    for pkg in "${APT_INSTALL[@]}"; do
        if [[ "$pkg" == libzbar0t64 ]]; then
            pkgs+=("$zbar_pkg")
        else
            pkgs+=("$pkg")
        fi
    done
    run env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        "${pkgs[@]}"
}

step_apt_purge_audio() {
    log "apt purge audio packages"
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
    else
        log "  (no audio packages installed)"
    fi
}

step_purge_radio_packages() {
    # Purge radio userspace packages. If running over SSH (SSH_CONNECTION is
    # set), deferring is unsafe because dpkg stops wpa_supplicant synchronously
    # and will drop the connection mid-run. Instead, schedule a one-shot service
    # to run on the next boot when no live SSH association exists.
    # If running from a local console (tty2/HDMI or serial), purge inline now
    # so first boot is clean — no extra service, no wait.
    local script_src="${APP_DIR}/deploy/purge-radio-packages.sh"
    local unit_src="${APP_DIR}/deploy/systemd/piwallet-purge-radios.service"
    [[ -f "$script_src" ]] || fail "missing $script_src"
    [[ -f "$unit_src" ]] || fail "missing $unit_src"

    if [[ $dry_run -eq 1 ]]; then
        log "  DRY: purge radio packages (inline or scheduled)"
        return 0
    fi

    run install -d -m 0755 /var/lib/piwallet
    run chmod 0755 "$script_src"

    # Purge inline if: on a local console (no SSH_CONNECTION), OR --local
    # flag was passed. When provisioning from tty2/HDMI, sudo can inherit
    # SSH_CONNECTION from an earlier login session — use --local to force
    # inline purge in that case (important for image-capture builds).
    if [[ -n "${SSH_CONNECTION:-}" && $local_provision -eq 0 ]]; then
        log "radio package purge: over SSH — scheduling for first boot"
        run install -m 0644 "$unit_src" "$UNIT_DST_DIR/piwallet-purge-radios.service"
        run touch /var/lib/piwallet/radio-purge.pending
        run rm -f /var/lib/piwallet/radio-purge.done
        run systemctl daemon-reload
        run systemctl enable piwallet-purge-radios.service
    else
        log "radio package purge: local console — purging inline now"
        # The purge script requires the pending flag to be present even when
        # called directly; create it so the script proceeds, then call it.
        run touch /var/lib/piwallet/radio-purge.pending
        run bash "$script_src"
        # Install the unit anyway (idempotent guard) but do NOT enable it.
        run install -m 0644 "$unit_src" "$UNIT_DST_DIR/piwallet-purge-radios.service"
        run systemctl daemon-reload
    fi
}

step_apt_purge() {
    step_apt_purge_audio
    if [[ $keep_radios -eq 1 ]]; then
        log "apt purge radio packages: SKIPPED (--keep-radios)"
        return 0
    fi
    log "apt purge radio packages: deferred until after app install (network still up)"
}

step_cmdline_spidev() {
    log "cmdline: raise spidev transfer buffer to 128 KiB"
    local file=""
    if [[ -f "$CMDLINE" ]]; then
        file="$CMDLINE"
    elif [[ -f "$CMDLINE_LEGACY" ]]; then
        file="$CMDLINE_LEGACY"
    else
        warn "no cmdline.txt — skipping spidev.bufsiz (bonnet may show banding)"
        return 0
    fi
    if grep -q "$SPI_BUFSIZ" "$file" 2>/dev/null; then
        log "  already set in $file"
        return 0
    fi
    if [[ $dry_run -eq 1 ]]; then
        log "  DRY: append $SPI_BUFSIZ to $file"
        return 0
    fi
    sed -i "s|\$| ${SPI_BUFSIZ}|" "$file"
}

step_boot_config() {
    log "boot config: enable SPI/I2C/camera, audio/radios per flags"
    [[ -f "$BOOT_CFG" ]] || fail "$BOOT_CFG missing"

    step_cmdline_spidev

    # Hardware enables.
    ensure_line "dtparam=spi=on"        "$BOOT_CFG"
    ensure_line "dtparam=i2c_arm=on"    "$BOOT_CFG"
    # Camera: use libcamera auto-detect (matches a stock Imager SD and the
    # kit OV5647 on Pi Zero W in practice). Do NOT append camera_auto_detect=0
    # on top of Imager's camera_auto_detect=1 — the last line wins and forced
    # ov5647-only mode has produced "No cameras available" on sealed images.
    # DIY no-EEPROM sensors: see docs/build.md for manual dtoverlay=ov5647.
    set_boot_config_key "camera_auto_detect" "1" "$BOOT_CFG"
    remove_boot_config_line "dtoverlay=ov5647" "$BOOT_CFG"

    # Audio off. dtparam=audio=off matches raspi-config; setting
    # it twice is harmless because ensure_line is idempotent.
    ensure_line "dtparam=audio=off"      "$BOOT_CFG"

    if [[ $keep_radios -eq 1 ]]; then
        log "  Wi-Fi/BT firmware disable: SKIPPED (--keep-radios)"
        return 0
    fi
    log "  Wi-Fi/BT firmware disable: deferred until after app install"
}

step_disable_radios_firmware() {
    log "boot config: disable Wi-Fi / Bluetooth firmware"
    [[ -f "$BOOT_CFG" ]] || fail "$BOOT_CFG missing"
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

step_mask_console_units() {
    log "mask console units (bonnet owns tty1)"
    local unit
    for unit in "${MASK_ALWAYS_UNITS[@]}"; do
        if systemctl cat "$unit" >/dev/null 2>&1; then
            run systemctl mask "$unit" || true
        else
            log "  $unit: not present, skipping"
        fi
    done
}

step_enable_tty2_getty() {
    log "enable getty@tty2 for HDMI/keyboard console (tty1 is bonnet-only)"
    # Pi OS Lite normally logs in on tty1. We mask that so piwallet-bonnet
    # owns tty1 without fighting a login prompt. Without an explicit
    # getty@tty2, Ctrl+Alt+F2 lands on an empty VT — black HDMI even
    # though the cable is connected.
    if systemctl cat getty@tty2.service >/dev/null 2>&1; then
        run systemctl enable getty@tty2.service
        run systemctl start getty@tty2.service || true
    else
        warn "getty@tty2.service not present — skip HDMI console enable"
    fi
}

step_mask_radio_units() {
    log "mask radio / mDNS units"
    local unit
    for unit in "${MASK_RADIO_UNITS[@]}"; do
        if systemctl cat "$unit" >/dev/null 2>&1; then
            run systemctl mask "$unit" || true
        else
            log "  $unit: not present, skipping"
        fi
    done
}

step_mask_units() {
    step_mask_console_units
    step_enable_tty2_getty
    if [[ $keep_radios -eq 1 ]]; then
        log "  radio units: SKIPPED (--keep-radios)"
    else
        log "  radio units: deferred until after app install"
    fi
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

step_seal_device() {
    if [[ $keep_radios -eq 1 && $keep_ssh -eq 1 ]]; then
        return 0
    fi
    log "seal device for shipping (disable network + SSH)"
    if [[ $keep_radios -eq 0 ]]; then
        step_disable_radios_firmware
        step_modprobe_blacklist
        step_mask_radio_units
        step_purge_radio_packages
    fi
    if [[ $keep_ssh -eq 0 ]]; then
        step_ssh
    fi
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
        local payload_rsync="${src_dir%/}/scripts/rsync-pi-payload.sh"
        [[ -x "$payload_rsync" ]] || \
            fail "missing $payload_rsync — sync with scripts/sync-to-pi.sh or copy the full scripts/ tree"
        log "  rsync from $src_dir (allowlist via scripts/rsync-pi-payload.sh)"
        run install -d "$APP_DIR"
        run bash "$payload_rsync" "${src_dir%/}" "$APP_DIR/"
        log "  prune stale non-runtime paths (allowlist rsync does not delete them)"
        run bash "$APP_DIR/scripts/prune-pi-payload.sh" "$APP_DIR"
    else
        if [[ -d "$APP_DIR/.git" ]]; then
            log "  git pull (existing checkout)"
            run git -C "$APP_DIR" pull --ff-only
        else
            log "  git clone $APP_REPO"
            run rm -rf "$APP_DIR"
            run git clone --depth 1 "$APP_REPO" "$APP_DIR"
        fi
        log "  prune non-runtime paths (git clone carries the full repo)"
        run bash "$APP_DIR/scripts/prune-pi-payload.sh" "$APP_DIR"
    fi

    [[ -x "$APP_DIR/scripts/rsync-pi-payload.sh" ]] || \
        chmod 0755 "$APP_DIR/scripts/rsync-pi-payload.sh" 2>/dev/null || true
    [[ -x "$APP_DIR/scripts/verify-pi-payload.sh" ]] || \
        chmod 0755 "$APP_DIR/scripts/verify-pi-payload.sh" 2>/dev/null || true
    [[ -x "$APP_DIR/scripts/prune-pi-payload.sh" ]] || \
        chmod 0755 "$APP_DIR/scripts/prune-pi-payload.sh" 2>/dev/null || true
    run bash "$APP_DIR/scripts/verify-pi-payload.sh" "$APP_DIR"

    # App code stays root-owned and read-only for the runtime user.
    # A code-execution exploit can't rewrite the binary it just ran.
    run chown -R root:root "$APP_DIR"
    run find "$APP_DIR" -type d -exec chmod 0755 {} +
    run find "$APP_DIR" -type f -exec chmod 0644 {} +
    # ...except things that need to be executable.
    run find "$APP_DIR" -type f -name '*.sh' -exec chmod 0755 {} +
    run find "$APP_DIR/scripts" -type f -name '*.py' -exec chmod 0755 {} + 2>/dev/null || true

    log "  build venv at $APP_VENV (pip install may take several minutes on Pi Zero W)"
    if [[ ! -x "$APP_VENV/bin/python" ]]; then
        run python3 -m venv --system-site-packages "$APP_VENV"
    fi
    # Pinned via --upgrade-strategy only-if-needed so a re-run picks
    # up new requirements without churning unaffected packages.
    run "$APP_VENV/bin/pip" install --upgrade --quiet pip
    # Install with the [display,camera] extras: the bonnet binds
    # board/digitalio (adafruit-blinka) for SPI + GPIO on the ST7789
    # panel, and pyzbar for QR decode in the camera flow. Without
    # these, ST7789Display() raises ImportError -> open_display("auto")
    # silently falls back to HeadlessDisplay and the panel stays dark.
    # scripts/install-piwallet-deps.sh handles the armv6l coincurve pin
    # when experimental 32-bit images are provisioned with --src.
    run bash "$APP_DIR/scripts/install-piwallet-deps.sh" \
        --repo "$APP_DIR" \
        --venv "$APP_VENV"
}

step_bonnet_hardware() {
    log "bonnet hardware (Blinka + SPI CE reassign)"
    if [[ ! -x "$APP_VENV/bin/python" ]]; then
        fail "venv missing at $APP_VENV"
    fi
    set +e
    run bash "$APP_DIR/scripts/setup-bonnet-hardware.sh" \
        --repo "$APP_DIR" \
        --venv "$APP_VENV"
    local hw_rc=$?
    set -e
    if [[ $hw_rc -eq 2 ]]; then
        log "  bonnet hardware setup requested a reboot (expected on first image build)"
    elif [[ $hw_rc -ne 0 ]]; then
        warn "bonnet hardware setup exited $hw_rc — verify display after reboot"
    fi
}

step_usb_backup() {
    log "install USB backup mount helper + root mount daemon"
    local helper_src="$APP_DIR/piwallet/backup/usb_mount.sh"
    local helper_dst="/opt/piwallet/bin/usb-mount"
    local mount_svc_src="$APP_DIR/piwallet/backup/piwallet-usb-mount.service"
    if [[ ! -f "$mount_svc_src" ]]; then
        mount_svc_src="$APP_DIR/deploy/systemd/piwallet-usb-mount.service"
    fi
    [[ -f "$helper_src" ]] || fail "missing $helper_src"
    [[ -f "$mount_svc_src" ]] || fail "missing $mount_svc_src"
    run install -d -m 0755 /opt/piwallet/bin
    run install -m 0755 "$helper_src" "$helper_dst"
    run install -d -m 0755 /mnt/piwallet-usb
    run install -m 0644 "$mount_svc_src" "$UNIT_DST_DIR/piwallet-usb-mount.service"
    run systemctl daemon-reload
    run systemctl enable piwallet-usb-mount.service
    run systemctl restart piwallet-usb-mount.service
}

step_install_unit() {
    log "install systemd unit + journald drop-in"

    # Read the unit files straight from the source tree when --src
    # was given. This avoids a chicken-and-egg with dry-run, where
    # step_install_app's rsync hasn't actually populated /opt yet,
    # so /opt/piwallet/deploy/systemd/* doesn't exist. When --src
    # is empty we're on the git-clone path and step_install_app
    # has already cloned into /opt/piwallet, so reading from there
    # is fine.
    local unit_root
    if [[ -n "$src_dir" ]]; then
        unit_root="$src_dir/$UNIT_SRC_DIR"
    else
        unit_root="$APP_DIR/$UNIT_SRC_DIR"
    fi
    local svc_src="$unit_root/piwallet-bonnet.service"
    local jrn_src="$unit_root/journald-piwallet.conf.example"

    [[ -f "$svc_src" ]] || fail "missing $svc_src"
    [[ -f "$jrn_src" ]] || fail "missing $jrn_src"

    run install -m 0644 "$svc_src" "$UNIT_DST_DIR/piwallet-bonnet.service"
    run install -d -m 0755 "$(dirname "$JOURNALD_CONF")"
    run install -m 0644 "$jrn_src" "$JOURNALD_CONF"

    run systemctl disable piwallet-boot-status.service 2>/dev/null || true
    run rm -f "$UNIT_DST_DIR/piwallet-boot-status.service"

    run systemctl daemon-reload
    run systemctl restart systemd-journald
    run systemctl enable piwallet-bonnet.service
}

step_hostname() {
    log "set hostname to $HOSTNAME_NEW"
    # Imager writes hostname into cloud-init user-data on the boot
    # partition; without patching it, the next reboot reverts our change.
    local user_data="/boot/firmware/user-data"
    if [[ -f "$user_data" ]] && grep -q '^hostname:' "$user_data" 2>/dev/null; then
        if [[ $dry_run -eq 1 ]]; then
            log "  DRY: patch $user_data hostname -> $HOSTNAME_NEW"
        else
            sed -i -E "s/^hostname:.*/hostname: ${HOSTNAME_NEW}/" "$user_data"
            log "  patched $user_data"
        fi
    fi
    if [[ $dry_run -eq 1 ]]; then
        log "  DRY: hostnamectl set-hostname $HOSTNAME_NEW"
    else
        printf '%s\n' "$HOSTNAME_NEW" > /etc/hostname
        hostnamectl set-hostname "$HOSTNAME_NEW"
    fi
    # /etc/hosts often has the old hostname pinned to 127.0.1.1; fix
    # it so name lookups inside the box don't fail.
    if [[ -f /etc/hosts ]] && [[ $dry_run -eq 0 ]]; then
        sed -i -E "s/127\\.0\\.1\\.1\\s+.*/127.0.1.1\t${HOSTNAME_NEW}/" /etc/hosts
    fi
}

step_install_udev() {
    log "install udev rules for spi/gpio device access"
    local rules_src=""
    if [[ -n "$src_dir" && -f "$src_dir/deploy/udev/99-piwallet-hardware.rules" ]]; then
        rules_src="$src_dir/deploy/udev/99-piwallet-hardware.rules"
    elif [[ -f "$APP_DIR/deploy/udev/99-piwallet-hardware.rules" ]]; then
        rules_src="$APP_DIR/deploy/udev/99-piwallet-hardware.rules"
    else
        fail "missing deploy/udev/99-piwallet-hardware.rules"
    fi
    run install -m 0644 "$rules_src" /etc/udev/rules.d/99-piwallet-hardware.rules
    run udevadm control --reload-rules
    run udevadm trigger -c add -s spidev || true
    run udevadm trigger -c add -s gpio || true
    run udevadm trigger -c add -s dma_heap || true
    # Apply immediately when nodes already exist (builder images).
    if [[ -e /dev/spidev0.0 ]] && [[ $dry_run -eq 0 ]]; then
        chgrp spi /dev/spidev0.0 2>/dev/null || true
        chmod 0660 /dev/spidev0.0 2>/dev/null || true
    fi
    if [[ -e /dev/gpiomem ]] && [[ $dry_run -eq 0 ]]; then
        chgrp gpio /dev/gpiomem 2>/dev/null || true
        chmod 0660 /dev/gpiomem 2>/dev/null || true
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
    log "enable hardware RNG"
    # In dry-run we never `apt install rng-tools-debian` for real,
    # so the unit isn't there yet. Print the intent instead of
    # warning about a service that the real run will pull in.
    if [[ $dry_run -eq 1 ]]; then
        log "  DRY: would enable rng-tools-debian.service (or rng-tools / rngd)"
        return 0
    fi
    # The package landscape has shifted across releases: Bookworm
    # ships the unit as `rng-tools-debian.service`; older systems
    # call it `rng-tools.service`; ancient ones call it
    # `rngd.service`. Try each in turn — the package's postinst
    # may already have enabled the canonical one, but `systemctl
    # enable` is idempotent so re-running it is safe.
    local candidate
    for candidate in rng-tools-debian.service rng-tools.service rngd.service; do
        if systemctl cat "$candidate" >/dev/null 2>&1; then
            run systemctl enable "$candidate" || true
            log "  enabled $candidate"
            return 0
        fi
    done
    warn "no rng-tools service unit found — HW RNG entropy won't feed kernel pool"
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

# Remove Raspberry Pi Imager Wi-Fi / cloud-init network secrets before
# image capture. Login users (e.g. pisv) are kept for local console
# troubleshooting. Only runs in full sealed mode (no --keep-* flags).
step_scrub_builder_secrets() {
    if [[ $keep_ssh -eq 1 || $keep_radios -eq 1 ]]; then
        log "skip Imager network-secret scrub (--keep-ssh and/or --keep-radios)"
        return 0
    fi
    log "scrub Imager Wi-Fi/network secrets (login users retained)"

    local boot="/boot/firmware"
    local legacy_boot="/boot"

    for f in \
        "$boot/userconf" "$boot/userconf.txt" \
        "$legacy_boot/userconf" "$legacy_boot/userconf.txt" \
        "$boot/firstrun.sh" "$legacy_boot/firstrun.sh" \
        "$boot/wpa_supplicant.conf" "$legacy_boot/wpa_supplicant.conf"
    do
        if [[ -e "$f" ]]; then
            run rm -f "$f"
        fi
    done

    # Replace cloud-init boot files with minimal sealed content — no
    # Wi-Fi SSID/PSK, no chpasswd, no ssh_authorized_keys.
    if [[ $dry_run -eq 1 ]]; then
        log "  DRY: write sealed user-data / network-config / meta-data"
    else
        cat > "$boot/user-data" <<EOF
#cloud-config
# PiWalletSV sealed image — no builder Wi-Fi, passwords, or SSH keys.
hostname: ${HOSTNAME_NEW}
manage_etc_hosts: true
EOF
        chmod 0644 "$boot/user-data"

        cat > "$boot/network-config" <<'EOF'
version: 2
ethernets:
  eth0:
    optional: true
    dhcp4: true
EOF
        chmod 0644 "$boot/network-config"

        cat > "$boot/meta-data" <<EOF
instance-id: piwalletsv-sealed
local-hostname: ${HOSTNAME_NEW}
EOF
        chmod 0644 "$boot/meta-data"
    fi

    run rm -f /etc/NetworkManager/system-connections/*.nmconnection
    run rm -f /etc/netplan/*.yaml /etc/netplan/*.yml 2>/dev/null || true
    run rm -f /etc/wpa_supplicant/wpa_supplicant.conf

    if command -v cloud-init >/dev/null 2>&1; then
        run cloud-init clean --logs --seed 2>/dev/null || true
    fi
    if [[ $dry_run -eq 1 ]]; then
        log "  DRY: rm -rf /var/lib/cloud/{instances,instance,data}"
    else
        rm -rf /var/lib/cloud/instances /var/lib/cloud/instance /var/lib/cloud/data \
            2>/dev/null || true
    fi
    run rm -f /var/log/cloud-init*.log
    # Mask cloud-init units so they don't run on every boot and timeout
    # waiting for a network that will never exist on a sealed device.
    # Hostname and hosts file are already set by this script; cloud-init
    # provides no value on the shipped image. Mask unconditionally — if
    # the unit doesn't exist systemctl mask creates a stub symlink that
    # is harmless and prevents the unit from being added back by an upgrade.
    for _ci_unit in cloud-init-local.service cloud-init.service \
                    cloud-config.service cloud-final.service; do
        run systemctl mask "$_ci_unit" 2>/dev/null || true
    done
    unset _ci_unit

    # Drop dev checkout and remote-login keys; production runs from
    # /opt/piwallet only. Keep the login account for HDMI/keyboard access.
    if [[ $dry_run -eq 1 ]]; then
        log "  DRY: rm -rf /home/*/PiWallet and builder ~/.ssh"
    else
        for u in pisv pi ${SUDO_USER:-}; do
            [[ -z "$u" || "$u" == root || "$u" == "$RUNTIME_USER" ]] && continue
            if [[ -d "/home/$u/PiWallet" ]]; then
                log "  remove /home/$u/PiWallet (not used in production)"
                rm -rf "/home/$u/PiWallet"
            fi
            rm -rf "/home/$u/.ssh" 2>/dev/null || true
        done
    fi

    run rm -rf /root/.ssh
    if [[ $dry_run -eq 0 ]]; then
        : > /root/.bash_history 2>/dev/null || true
        journalctl --rotate >/dev/null 2>&1 || true
        journalctl --vacuum-time=1s >/dev/null 2>&1 || true
    fi

    step_verify_no_builder_secrets
}

step_verify_no_builder_secrets() {
    if [[ $keep_ssh -eq 1 || $keep_radios -eq 1 ]]; then
        return 0
    fi
    log "verify Imager network secrets scrubbed"
    local problems=()

    for f in \
        /boot/firmware/userconf /boot/firmware/userconf.txt \
        /boot/userconf /boot/userconf.txt
    do
        [[ -e "$f" ]] && problems+=("boot credential file still present: $f")
    done

    if [[ -f /boot/firmware/network-config ]] && \
       grep -qiE '(access-points:|password:|psk:)' /boot/firmware/network-config 2>/dev/null; then
        problems+=("network-config still contains Wi-Fi credentials")
    fi

    if [[ -f /boot/firmware/user-data ]] && \
       grep -qiE '(password:|passwd:|ssh_authorized_keys|chpasswd|access-points:)' \
           /boot/firmware/user-data 2>/dev/null; then
        problems+=("user-data still contains user or Wi-Fi secrets")
    fi

    if compgen -G '/etc/NetworkManager/system-connections/*.nmconnection' >/dev/null; then
        problems+=("NetworkManager connection profiles still present")
    fi

    if [[ -f /etc/wpa_supplicant/wpa_supplicant.conf ]] && \
       grep -q 'network=' /etc/wpa_supplicant/wpa_supplicant.conf 2>/dev/null; then
        problems+=("wpa_supplicant.conf still has networks configured")
    fi

    if [[ ${#problems[@]} -gt 0 ]]; then
        for p in "${problems[@]}"; do
            warn "$p"
        done
        fail "Imager network-secret verification failed — re-flash and re-provision"
    fi
    log "  OK — no Imager Wi-Fi/network credentials on boot or rootfs"
}

step_verify_sealed_for_capture() {
    if [[ $keep_radios -eq 1 ]]; then
        return 0
    fi
    log "verify sealed image is capture-ready (no first-boot apt purge)"
    local problems=()
    if [[ -f /var/lib/piwallet/radio-purge.pending ]]; then
        problems+=("radio-purge.pending still set — purge will run on buyer first boot")
    fi
    if [[ ! -f /var/lib/piwallet/radio-purge.done ]]; then
        problems+=("radio-purge.done missing — radio packages not purged inline")
    fi
    if systemctl is-enabled piwallet-purge-radios.service >/dev/null 2>&1; then
        problems+=("piwallet-purge-radios.service is enabled — defer purge to first boot")
    fi
    local cmdline=""
    if [[ -f "$CMDLINE" ]]; then
        cmdline="$CMDLINE"
    elif [[ -f "$CMDLINE_LEGACY" ]]; then
        cmdline="$CMDLINE_LEGACY"
    fi
    if [[ -n "$cmdline" ]] && ! grep -q "$SPI_BUFSIZ" "$cmdline" 2>/dev/null; then
        problems+=("spidev.bufsiz=131072 missing from $cmdline — bonnet display will garble")
    fi
    local bufsiz
    bufsiz="$(cat /sys/module/spidev/parameters/bufsiz 2>/dev/null || echo 0)"
    if [[ "$bufsiz" != "131072" ]]; then
        if [[ -n "$cmdline" ]] && grep -q "$SPI_BUFSIZ" "$cmdline" 2>/dev/null; then
            log "  note: kernel spidev bufsiz is ${bufsiz} until reboot (cmdline already has 131072)"
        else
            problems+=("kernel spidev bufsiz is ${bufsiz} (need 131072 in cmdline)")
        fi
    fi
    if [[ ${#problems[@]} -gt 0 ]]; then
        for p in "${problems[@]}"; do
            warn "$p"
        done
        fail "sealed image not capture-ready — provision from tty2 with --local (inline radio purge)"
    fi
    log "  OK — radio purge baked in; buyer first boot skips apt"
}

step_release_metadata() {
    log "write release metadata (${release_version}, ${image_channel})"
    [[ -d "$APP_DIR" ]] || fail "APP_DIR missing — run step_install_app first"

    local git_commit="" app_tree_sha256="" image_id="" built_at model os_pretty arch
    built_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    model=$(tr -d '\000' < /proc/device-tree/model 2>/dev/null || echo unknown)
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        os_pretty="${PRETTY_NAME:-unknown}"
    else
        os_pretty=unknown
    fi
    arch=$(uname -m)

    if [[ -d "$APP_DIR/.git" ]]; then
        git_commit=$(git -C "$APP_DIR" rev-parse HEAD 2>/dev/null || true)
    elif [[ -n "$src_dir" && -d "$src_dir/.git" ]]; then
        git_commit=$(git -C "$src_dir" rev-parse HEAD 2>/dev/null || true)
    fi

    if [[ $dry_run -eq 1 ]]; then
        log "  DRY: would compute app_tree_sha256 and write ${RELEASE_FILE}"
        return 0
    fi

    # Hash only runtime firmware paths (matches pi-payload excludes).
    app_tree_sha256=$(
        find "$APP_DIR" -type f \
            \( -path "$APP_DIR/piwallet/*" \
               -o -path "$APP_DIR/scripts/*" \
               -o -path "$APP_DIR/deploy/*" \
               -o -path "$APP_DIR/pyproject.toml" \) \
            ! -path '*/.venv/*' \
            ! -path '*/__pycache__/*' \
            ! -name '*.pyc' \
            -print0 \
        | sort -z \
        | xargs -0 sha256sum \
        | sha256sum \
        | awk '{print $1}'
    )
    image_id=${app_tree_sha256:0:8}

    cat > "$RELEASE_FILE" <<EOF
# Written by deploy/provision-pi.sh — do not hand-edit.
PIWALLETSV_VERSION=${release_version}
PIWALLETSV_IMAGE_CHANNEL=${image_channel}
PIWALLETSV_IMAGE_ID=${image_id}
PIWALLETSV_APP_TREE_SHA256=${app_tree_sha256}
PIWALLETSV_GIT_COMMIT=${git_commit}
PIWALLETSV_BUILT_AT=${built_at}
PIWALLETSV_BOARD_MODEL="${model}"
PIWALLETSV_OS="${os_pretty}"
PIWALLETSV_ARCH=${arch}
EOF
    chmod 0644 "$RELEASE_FILE"

    export PIWALLETSV_VERSION="$release_version"
    export PIWALLETSV_IMAGE_CHANNEL="$image_channel"
    export PIWALLETSV_IMAGE_ID="$image_id"
    export PIWALLETSV_APP_TREE_SHA256="$app_tree_sha256"
    export PIWALLETSV_GIT_COMMIT="$git_commit"
    export PIWALLETSV_BUILT_AT="$built_at"
    export PIWALLETSV_BOARD_MODEL="$model"
    export PIWALLETSV_OS="$os_pretty"
    export PIWALLETSV_ARCH="$arch"
    export PIWALLETSV_RELEASE_JSON="$RELEASE_JSON"

    python3 <<'PY'
import json
import os
from pathlib import Path

payload = {
    "piwalletsv_version": os.environ["PIWALLETSV_VERSION"],
    "image_channel": os.environ["PIWALLETSV_IMAGE_CHANNEL"],
    "image_id": os.environ["PIWALLETSV_IMAGE_ID"],
    "app_tree_sha256": os.environ["PIWALLETSV_APP_TREE_SHA256"],
    "git_commit": os.environ["PIWALLETSV_GIT_COMMIT"],
    "built_at": os.environ["PIWALLETSV_BUILT_AT"],
    "board_model": os.environ["PIWALLETSV_BOARD_MODEL"],
    "os": os.environ["PIWALLETSV_OS"],
    "arch": os.environ["PIWALLETSV_ARCH"],
}
Path(os.environ["PIWALLETSV_RELEASE_JSON"]).write_text(
    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
)
PY
    chmod 0644 "$RELEASE_JSON"
    log "  image_id=${image_id} app_tree_sha256=${app_tree_sha256:0:16}…"
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
    if [[ $keep_radios -eq 1 ]]; then
        step_modprobe_blacklist
    fi
    step_mask_units
    if [[ $keep_ssh -eq 0 && $keep_radios -eq 1 ]]; then
        step_ssh
    fi
    step_create_user
    step_install_app
    step_install_udev
    step_release_metadata
    step_bonnet_hardware
    step_usb_backup
    step_install_unit
    step_seal_device
    step_hostname
    step_swap_off
    step_rng
    step_cleanup
    step_scrub_builder_secrets
    step_verify_sealed_for_capture

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
  * systemctl status piwallet-usb-mount   # active (running)
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
SEALED MODE — radios firmware-disabled.
Radio packages were purged inline (local console) or will purge on next
boot (piwallet-purge-radios.service, SSH path). After reboot verify:

  * systemctl status piwallet-bonnet        # active (running)
  * cat /var/lib/piwallet/radio-purge.done  # exists (inline or post-boot)

Imager Wi-Fi/network files are scrubbed automatically before you reboot.
The Imager login user (e.g. pisv) is kept for local HDMI/keyboard access.
For image capture: reboot after seal, wait for bonnet disclaimer, power
off, then dd. Provision from **tty2** with inline radio purge so the
captured image does **not** run apt on the buyer's first boot.

PiShrink **expands the rootfs to the SD size on first flash** (one automatic
reboot). Set ``PISHRINK_SKIP_AUTOEXPAND=1`` when capturing if you want to skip
expand (8 GB cards only; saves ~1–2 min on first flash).
EOF
    fi
    cat <<'EOF'

Reboot now with: sudo reboot
================================================================
EOF
}

main "$@"
