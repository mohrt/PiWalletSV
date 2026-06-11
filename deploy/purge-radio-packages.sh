#!/usr/bin/env bash
# One-time radio userspace purge for sealed PiWalletSV images.
#
# Invoked by piwallet-purge-radios.service on first boot after provision.
# Must NOT run while SSH is over Wi-Fi — dpkg maintainer scripts stop
# wpa_supplicant synchronously and can hang indefinitely.
#
# At first boot, provision has already written dtoverlay=disable-wifi/bt,
# modprobe blacklists, and masked radio units, so wpa_supplicant is not
# managing a live association.
set -euo pipefail

readonly LOG_PREFIX="[purge-radios]"
readonly STATE_DIR="/var/lib/piwallet"
readonly PENDING="${STATE_DIR}/radio-purge.pending"
readonly DONE_STAMP="${STATE_DIR}/radio-purge.done"

log()  { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s WARN: %s\n' "$LOG_PREFIX" "$*" >&2; }

if [[ -f "$DONE_STAMP" ]]; then
    log "already purged ($DONE_STAMP)"
    exit 0
fi

if [[ ! -f "$PENDING" ]]; then
    log "no pending flag ($PENDING) — skip"
    exit 0
fi

if [[ $(id -u) -ne 0 ]]; then
    echo "$LOG_PREFIX must run as root" >&2
    exit 1
fi

readonly RADIO_PKGS=(
    wireless-tools
    wpasupplicant
    bluez
    bluez-firmware
    pi-bluetooth
    libnss-mdns
    avahi-daemon
    avahi-utils
)

installed=()
for pkg in "${RADIO_PKGS[@]}"; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then
        installed+=("$pkg")
    fi
done

if [[ ${#installed[@]} -eq 0 ]]; then
    log "no radio packages installed"
    touch "$DONE_STAMP"
    rm -f "$PENDING"
    exit 0
fi

log "purging: ${installed[*]}"

# Best-effort stop before dpkg (should be inactive/masked after provision).
systemctl stop wpa_supplicant.service 2>/dev/null || true
systemctl stop 'wpa_supplicant@*.service' 2>/dev/null || true
systemctl stop bluetooth.service 2>/dev/null || true
systemctl stop avahi-daemon.service 2>/dev/null || true

if ! env DEBIAN_FRONTEND=noninteractive apt-get purge -y "${installed[@]}"; then
    warn "apt purge reported errors — RF remains blocked via boot config"
fi
env DEBIAN_FRONTEND=noninteractive apt-get autoremove -y --purge || true

touch "$DONE_STAMP"
rm -f "$PENDING"
log "done"
