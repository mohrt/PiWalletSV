#!/usr/bin/env bash
# On-device camera diagnostic: plain pwsv vs systemd sandbox knobs.
# Run on the Pi as root (or with sudo). Requires /opt/piwallet provision layout.
set -euo pipefail

PIWALLET="${PIWALLET:-/opt/piwallet/.venv/bin/piwallet}"

if [[ ! -x "$PIWALLET" ]]; then
  echo "missing $PIWALLET — run from a provisioned Pi" >&2
  exit 1
fi

_run() {
  local label="$1"
  shift
  echo
  echo "=== $label ==="
  if "$@"; then
    echo "-> OK"
  else
    echo "-> FAIL (exit $?)"
  fi
}

_run "pwsv shell (no systemd sandbox)" \
  sudo -u pwsv "$PIWALLET" diag camera

_run "RestrictAddressFamilies=AF_UNIX only (broken on Trixie/libcamera)" \
  systemd-run --wait --pipe -p User=pwsv -p Group=pwsv \
    -p SupplementaryGroups=spi,gpio,video,i2c,dialout \
    -p RestrictAddressFamilies=AF_UNIX \
    "$PIWALLET" diag camera

_run "RestrictAddressFamilies=AF_UNIX AF_NETLINK (bonnet unit fix)" \
  systemd-run --wait --pipe -p User=pwsv -p Group=pwsv \
    -p SupplementaryGroups=spi,gpio,video,i2c,dialout \
    -p RestrictAddressFamilies=AF_UNIX AF_NETLINK \
    "$PIWALLET" diag camera

_run "MemoryDenyWriteExecute=yes (old bonnet unit — often breaks Picamera2)" \
  systemd-run --wait --pipe -p User=pwsv -p Group=pwsv \
    -p SupplementaryGroups=spi,gpio,video,i2c,dialout \
    -p RestrictAddressFamilies=AF_UNIX AF_NETLINK \
    -p MemoryDenyWriteExecute=yes \
    "$PIWALLET" diag camera

echo
echo "If pwsv OK but bonnet Photo entropy fails: patch piwallet-bonnet.service"
echo "  (AF_NETLINK + comment MemoryDenyWriteExecute), daemon-reload, restart."
