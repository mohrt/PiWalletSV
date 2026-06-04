"""Removable USB block device discovery and optional mount helpers."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from piwallet.backup.usb_mount_socket import (
    DEFAULT_MOUNT_POINT,
    UsbMountError,
    mount_device,
    unmount_stick,
)

log = logging.getLogger(__name__)

DEFAULT_USB_MOUNT_POINT = DEFAULT_MOUNT_POINT


@dataclass(frozen=True)
class UsbVolume:
    """A removable USB partition the operator can pick."""

    device: str  # e.g. /dev/sda1
    size: str
    label: str
    fstype: str
    mountpoint: str | None

    @property
    def display_name(self) -> str:
        parts = [self.label or self.device, self.size]
        if self.fstype:
            parts.append(self.fstype)
        return "  ".join(p for p in parts if p)


_SUPPORTED_FSTYPES = frozenset({"vfat", "exfat", "fat", "fat32"})


def _parse_lsblk_entry(entry: dict) -> UsbVolume | None:
    name = entry.get("name")
    if not name or not isinstance(name, str):
        return None
    rm = entry.get("rm")
    if rm is not True and rm != 1 and str(rm) != "1":
        return None
    devtype = entry.get("type")
    if devtype not in ("part", "disk"):
        return None
    if name.startswith("mmc"):
        return None
    device = f"/dev/{name}"
    fstype = str(entry.get("fstype") or "")
    if devtype == "disk" and not fstype:
        return None
    if fstype and fstype.lower() not in _SUPPORTED_FSTYPES:
        return None
    mountpoint = entry.get("mountpoint")
    mp = str(mountpoint) if mountpoint else None
    size = str(entry.get("size") or "?")
    label = str(entry.get("label") or "")
    return UsbVolume(
        device=device,
        size=size,
        label=label,
        fstype=fstype,
        mountpoint=mp,
    )


def list_usb_volumes(*, lsblk_path: str = "lsblk") -> list[UsbVolume]:
    """Return removable vfat/exfat volumes, excluding the SD card."""
    try:
        proc = subprocess.run(
            [
                lsblk_path,
                "-J",
                "-o",
                "NAME,SIZE,TYPE,RM,LABEL,FSTYPE,MOUNTPOINT",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    devices = data.get("blockdevices") or []
    out: list[UsbVolume] = []
    seen: set[str] = set()

    def walk(nodes: list) -> None:
        for entry in nodes:
            if not isinstance(entry, dict):
                continue
            vol = _parse_lsblk_entry(entry)
            if vol is not None and vol.device not in seen:
                seen.add(vol.device)
                out.append(vol)
            children = entry.get("children")
            if isinstance(children, list):
                walk(children)

    walk(devices)
    return out


def stick_root_from_volume(volume: UsbVolume) -> Path | None:
    """Return mountpoint path if the volume is already mounted."""
    if volume.mountpoint:
        return Path(volume.mountpoint)
    return None


def ensure_mounted(
    volume: UsbVolume,
    mount_point: Path,
    *,
    mount_cmd: list[str] | None = None,
) -> Path:
    """Mount ``volume`` at ``mount_point`` if needed; return stick root path."""
    if volume.mountpoint == str(mount_point):
        return mount_point

    if mount_cmd is not None:
        mount_point.mkdir(parents=True, exist_ok=True)
        subprocess.run(mount_cmd, check=True)
        return mount_point

    try:
        return mount_device(volume.device)
    except UsbMountError:
        log.exception("usb mount daemon failed for %s", volume.device)
        raise


def unmount(mount_point: Path, *, umount_cmd: list[str] | None = None) -> None:
    if umount_cmd is not None:
        subprocess.run(umount_cmd, check=False)
        return
    if mount_point != DEFAULT_USB_MOUNT_POINT:
        cmd = ["umount", str(mount_point)]
        subprocess.run(cmd, check=False)
        return
    try:
        unmount_stick()
    except Exception:
        log.exception("usb unmount failed for %s", mount_point)
