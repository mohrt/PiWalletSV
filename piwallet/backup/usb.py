"""Removable USB block device discovery and optional mount helpers."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from piwallet.backup.usb_mount_socket import (
    DEFAULT_MOUNT_POINT,
    UsbMountError,
    _is_mounted,
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
    model: str = ""

    @property
    def display_name(self) -> str:
        kind = {"vfat": "FAT32", "fat": "FAT32", "fat32": "FAT32", "msdos": "FAT32", "exfat": "exFAT"}.get(
            self.fstype, self.fstype
        )
        parts = [self.label or self.device, self.size]
        if kind:
            parts.append(kind)
        return "  ".join(p for p in parts if p)


_EXFAT_TYPES = frozenset({"exfat", "fuse.exfat", "exfat-fuse"})
_VFAT_TYPES = frozenset({"vfat", "fat", "fat32", "msdos"})


def _marked_removable(value: object) -> bool:
    return value is True or value == 1 or str(value) == "1"


def _is_usb(entry: dict, *, parent_usb: bool) -> bool:
    """A partition often has ``rm`` false even when the disk is a USB stick.

    On a Pi the SD card is ``mmcblk*``. A backup stick shows up as ``sd*``
    even when ``lsblk`` leaves both the removable flag and the transport blank.
    """
    name = str(entry.get("name") or "")
    if name.startswith(("loop", "zram", "dm-", "mmcblk0")):
        return False
    if parent_usb or name.startswith("sd"):
        return True
    if _marked_removable(entry.get("rm")):
        return True
    return str(entry.get("tran") or "").lower() == "usb"


def _probe_signature(device: str) -> str | None:
    """Read the boot sector. exFAT and NTFS share a partition type, so blkid can be wrong."""
    try:
        with open(device, "rb") as handle:
            sector = handle.read(512)
    except OSError:
        return None
    if len(sector) < 90:
        return None
    oem = sector[3:11]
    if oem == b"EXFAT   ":
        return "exfat"
    if oem == b"NTFS    ":
        return "ntfs"
    if sector[82:87] == b"FAT32" or sector[54:57] == b"FAT":
        return "vfat"
    return None


def _classify_filesystem(device: str, reported: str) -> str | None:
    kind = reported.lower()
    if kind in _EXFAT_TYPES:
        return "exfat"
    if kind in _VFAT_TYPES:
        return "vfat"
    probed = _probe_signature(device)
    if probed == "exfat":
        return "exfat"
    if probed == "vfat":
        return "vfat"
    if probed == "ntfs":
        return None
    if not kind:
        return ""
    return None


def _parse_lsblk_entry(entry: dict, *, usb: bool) -> UsbVolume | None:
    name = entry.get("name")
    if not name or not isinstance(name, str) or not usb:
        return None
    if name.startswith("mmc"):
        return None
    devtype = entry.get("type")
    if devtype not in ("part", "disk"):
        return None
    children = entry.get("children")
    if devtype == "disk" and isinstance(children, list) and children:
        return None
    device = f"/dev/{name}"
    fstype = _classify_filesystem(device, str(entry.get("fstype") or ""))
    if fstype is None:
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


def _run_lsblk(lsblk_path: str, columns: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            [lsblk_path, "-J", "-o", columns],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None


def _parent_disk(name: str) -> str:
    if name.startswith("mmcblk"):
        head, sep, tail = name.rpartition("p")
        if sep and tail.isdigit():
            return head
        return name
    stripped = name.rstrip("0123456789")
    return stripped or name


def _is_external_block(name: str, sys_class: Path) -> bool:
    """USB sticks and USB card readers. The Pi's own microSD is mmcblk0."""
    if name.startswith(("loop", "ram", "zram", "dm-", "nbd", "mmcblk0")):
        return False
    if name.startswith("sd"):
        return True
    device = sys_class / _parent_disk(name) / "device"
    try:
        return "/usb" in str(device.resolve())
    except OSError:
        return False


def _sector_count(path: Path) -> int:
    try:
        return int(path.read_text().strip() or "0")
    except (OSError, ValueError):
        return -1


def parent_disk(device: str) -> str:
    """``/dev/sdb1`` and ``/dev/sdb2`` belong to the stick ``sdb``."""
    return _parent_disk(device.removeprefix("/dev/"))


def _sysfs_line(path: Path) -> str:
    try:
        return " ".join(path.read_text(errors="replace").split())
    except OSError:
        return ""


_ROOT_HUB = re.compile(r"usb\d+")


def _scsi_name(device: Path) -> str:
    vendor = _sysfs_line(device / "vendor")
    model = _sysfs_line(device / "model")
    if vendor and model.lower().startswith(vendor.lower()):
        return model
    return " ".join(part for part in (vendor, model) if part)


def _should_walk_usb(start: Path) -> bool:
    """Climb only a real /sys USB chain, or a test tree that contains a root hub."""
    if str(start).startswith("/sys/"):
        return True
    current = start
    for _ in range(8):
        if _ROOT_HUB.fullmatch(current.name):
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent
    return False


def _usb_product(device: Path) -> str:
    """Product string of the USB stick. The Pi's own controller is named after the kernel."""
    try:
        current = device.resolve()
    except OSError:
        return ""
    if not _should_walk_usb(current):
        return ""
    for _ in range(8):
        if _ROOT_HUB.fullmatch(current.name):
            return ""
        maker = _sysfs_line(current / "manufacturer")
        if maker.startswith("Linux "):
            return ""
        product = _sysfs_line(current / "product")
        if product:
            if maker and maker.lower() not in product.lower():
                return f"{maker} {product}"
            return product
        parent = current.parent
        if parent == current:
            return ""
        if str(current).startswith("/sys/") and not str(parent).startswith("/sys"):
            return ""
        current = parent
    return ""


def _disk_model(sys_class: Path, name: str) -> str:
    """USB product name, or the SCSI vendor and model when the stick has no product string."""
    device = sys_class / _parent_disk(name) / "device"
    return _usb_product(device) or _scsi_name(device)


def _human_size(sectors: int) -> str:
    if sectors < 0:
        return "?"
    nbytes = sectors * 512
    if nbytes >= 1 << 30:
        return f"{nbytes / (1 << 30):.1f}G"
    if nbytes >= 1 << 20:
        return f"{nbytes // (1 << 20)}M"
    return f"{nbytes}B"


def _volumes_from_class(sys_class: Path) -> list[UsbVolume]:
    """List USB disks from sysfs, without trusting lsblk's filesystem type."""
    if not sys_class.is_dir():
        return []
    names = [node.name for node in sys_class.iterdir() if _is_external_block(node.name, sys_class)]
    parents = {_parent_disk(name) for name in names if _parent_disk(name) != name}
    volumes: list[UsbVolume] = []
    for name in sorted(names):
        if name in parents:
            continue
        sectors = _sector_count(sys_class / name / "size")
        if sectors == 0:
            continue
        device = f"/dev/{name}"
        kind = _classify_filesystem(device, "")
        if kind is None:
            continue
        volumes.append(
            UsbVolume(
                device=device,
                size=_human_size(sectors),
                label="",
                fstype=kind,
                mountpoint=None,
                model=_disk_model(sys_class, name),
            )
        )
    return volumes


def _fstypes_from_lsblk(lsblk_path: str) -> dict[str, str]:
    """Partition name to filesystem, from udev. Reading the device node itself may be denied."""
    proc = _run_lsblk(lsblk_path, "NAME,FSTYPE")
    if proc is None or proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    found: dict[str, str] = {}

    def walk(nodes: list) -> None:
        for entry in nodes:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if isinstance(name, str) and name:
                found[name] = str(entry.get("fstype") or "")
            children = entry.get("children")
            if isinstance(children, list):
                walk(children)

    walk(data.get("blockdevices") or [])
    return found


def _with_formats(volumes: list[UsbVolume], lsblk_path: str) -> list[UsbVolume]:
    """Fill FAT32/exFAT when the boot-sector probe could not read the device."""
    reported = _fstypes_from_lsblk(lsblk_path)
    if not reported:
        return volumes
    filled: list[UsbVolume] = []
    for volume in volumes:
        if volume.fstype:
            filled.append(volume)
            continue
        kind = _classify_filesystem(volume.device, reported.get(volume.device.removeprefix("/dev/"), ""))
        if kind:
            filled.append(replace(volume, fstype=kind))
        else:
            filled.append(volume)
    return filled


def list_usb_volumes(*, lsblk_path: str = "lsblk", sys_class: Path | None = None) -> list[UsbVolume]:
    """Return USB FAT32/exFAT volumes, excluding the Pi's own SD card."""
    if sys_class is not None:
        return _volumes_from_class(sys_class)
    found = _volumes_from_class(Path("/sys/class/block"))
    if found:
        return _with_formats(found, lsblk_path)
    return _list_from_lsblk(lsblk_path)


def _list_from_lsblk(lsblk_path: str) -> list[UsbVolume]:
    proc = _run_lsblk(lsblk_path, "NAME,SIZE,TYPE,RM,TRAN,LABEL,FSTYPE,MOUNTPOINT")
    if proc is None:
        return []
    if proc.returncode != 0:
        proc = _run_lsblk(lsblk_path, "NAME,SIZE,TYPE,RM,LABEL,FSTYPE,MOUNTPOINT")
    if proc is None or proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    devices = data.get("blockdevices") or []
    out: list[UsbVolume] = []
    seen: set[str] = set()

    def walk(nodes: list, *, parent_usb: bool = False) -> None:
        for entry in nodes:
            if not isinstance(entry, dict):
                continue
            usb = _is_usb(entry, parent_usb=parent_usb)
            vol = _parse_lsblk_entry(entry, usb=usb)
            if vol is not None and vol.device not in seen:
                seen.add(vol.device)
                out.append(vol)
            children = entry.get("children")
            if isinstance(children, list):
                walk(children, parent_usb=usb)

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
    except UsbMountError as exc:
        if "not running" not in str(exc):
            log.exception("usb mount daemon failed for %s", volume.device)
            raise
        return _mount_via_sudo(volume.device)


def _sudo_helper(action: str, device: str | None = None) -> subprocess.CompletedProcess[str]:
    helper = Path(__file__).with_name("usb_mount.sh")
    user = os.environ.get("USER") or "root"
    cmd = ["sudo", "-n", "env", f"PIWALLET_USB_MOUNT_USER={user}", str(helper), action]
    if device:
        cmd.append(device)
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _mount_via_sudo(device: str) -> Path:
    """Mount when the root socket daemon is not installed (dev Pi)."""
    try:
        proc = _sudo_helper("mount", device)
    except OSError as exc:
        raise UsbMountError("USB mount service is not running.") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Could not mount USB.").strip()
        line = detail.splitlines()[-1] if detail else "Could not mount USB."
        raise UsbMountError(line[:160])
    if not _is_mounted(device, DEFAULT_USB_MOUNT_POINT):
        raise UsbMountError("USB drive did not mount.")
    return DEFAULT_USB_MOUNT_POINT


def _unmount_via_sudo() -> None:
    try:
        proc = _sudo_helper("unmount")
    except OSError as exc:
        raise UsbMountError("Could not eject the USB drive.") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Could not eject the USB drive.").strip()
        line = detail.splitlines()[-1] if detail else "Could not eject the USB drive."
        raise UsbMountError(line[:160])


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
    except UsbMountError as exc:
        if "not running" not in str(exc):
            log.exception("usb unmount failed for %s", mount_point)
            raise
        _unmount_via_sudo()
