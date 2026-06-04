#!/usr/bin/env bash
# Mount or unmount a USB partition for PiWalletSV backup (run as root).
#
# Install on the Pi (production image does this via provision-pi.sh):
#   sudo install -m 755 /opt/piwallet/piwallet/backup/usb_mount.sh \
#       /opt/piwallet/bin/usb-mount
#   sudo install deploy/systemd/piwallet-usb-mount.service \
#       /etc/systemd/system/piwallet-usb-mount.service
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now piwallet-usb-mount
#
# Usage:
#   usb-mount mount /dev/sda1
#   usb-mount unmount
set -euo pipefail
MOUNT_POINT="/mnt/piwallet-usb"
RUNTIME_USER="${PIWALLET_USB_MOUNT_USER:-pwsv}"

_mount_opts() {
  local uid gid
  uid="$(id -u "$RUNTIME_USER")"
  gid="$(id -g "$RUNTIME_USER")"
  # pwsv must create PiWalletSV/backups/ on the stick; vfat/exfat have no
  # Unix owners unless set at mount time.
  printf 'uid=%s,gid=%s,umask=022' "$uid" "$gid"
}

cmd="${1:?usage: usb-mount mount|unmount [device]}"
case "$cmd" in
  mount)
    dev="${2:?device required, e.g. /dev/sda1}"
    mkdir -p "$MOUNT_POINT"
    if mountpoint -q "$MOUNT_POINT"; then
      umount "$MOUNT_POINT" || true
    fi
    existing_mp="$(findmnt -n -o TARGET --source "$dev" 2>/dev/null || true)"
    if [[ -n "$existing_mp" && "$existing_mp" != "$MOUNT_POINT" ]]; then
      umount "$dev" || umount "$existing_mp" || true
    fi
    fstype=$(blkid -o value -s TYPE "$dev" 2>/dev/null || true)
    mnt_opts="$(_mount_opts)"
    case "$fstype" in
      vfat|fat|fat32) mount -t vfat -o "$mnt_opts" "$dev" "$MOUNT_POINT" ;;
      exfat) mount -t exfat -o "$mnt_opts" "$dev" "$MOUNT_POINT" ;;
      "") mount -t auto -o "$mnt_opts" "$dev" "$MOUNT_POINT" ;;
      *) echo "unsupported filesystem: $fstype (use FAT32 or exFAT)" >&2; exit 1 ;;
    esac
    echo "$MOUNT_POINT"
    ;;
  unmount)
    if mountpoint -q "$MOUNT_POINT"; then
      umount "$MOUNT_POINT"
    fi
    ;;
  *)
    echo "usage: usb-mount mount /dev/sda1 | usb-mount unmount" >&2
    exit 1
    ;;
esac
