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
if ! id -u "$RUNTIME_USER" >/dev/null 2>&1; then
  if [[ -n "${SUDO_USER:-}" ]] && id -u "$SUDO_USER" >/dev/null 2>&1; then
    RUNTIME_USER="$SUDO_USER"
  fi
fi

_mount_opts() {
  local uid gid
  uid="$(id -u "$RUNTIME_USER")"
  gid="$(id -g "$RUNTIME_USER")"
  # pwsv must create PiWalletSV/backups/ on the stick; vfat/exfat have no
  # Unix owners unless set at mount time.
  printf 'uid=%s,gid=%s,umask=022' "$uid" "$gid"
}

_try_exfat() {
  local dev="$1" opts="$2"
  modprobe exfat 2>/dev/null || true
  mount -t exfat -o "$opts" "$dev" "$MOUNT_POINT" && return 0
  if command -v mount.exfat-fuse >/dev/null 2>&1; then
    mount.exfat-fuse -o "$opts" "$dev" "$MOUNT_POINT" && return 0
  elif command -v mount.exfat >/dev/null 2>&1; then
    mount.exfat -o "$opts" "$dev" "$MOUNT_POINT" && return 0
  fi
  return 1
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
    oem=$(dd if="$dev" bs=1 skip=3 count=8 2>/dev/null || true)
    case "$oem" in
      "EXFAT   ") fstype=exfat ;;
      "NTFS    ") fstype=ntfs ;;
    esac
    if [[ "$fstype" != "exfat" && "$fstype" != "ntfs" ]]; then
      fat=$(dd if="$dev" bs=1 skip=82 count=5 2>/dev/null || true)
      case "$fat" in
        FAT32) fstype=vfat ;;
      esac
    fi
    mnt_opts="$(_mount_opts)"
    case "$fstype" in
      vfat|fat|fat32)
        mount -t vfat -o "$mnt_opts" "$dev" "$MOUNT_POINT"
        ;;
      exfat)
        if ! _try_exfat "$dev" "$mnt_opts"; then
          echo "exFAT is not available. Run: sudo apt install exfatprogs exfat-fuse" >&2
          exit 1
        fi
        ;;
      "")
        if ! _try_exfat "$dev" "$mnt_opts"; then
          mount -t vfat -o "$mnt_opts" "$dev" "$MOUNT_POINT"
        fi
        ;;
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
