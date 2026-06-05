"""Read Raspberry Pi board serial numbers from kernel interfaces."""

from __future__ import annotations

from pathlib import Path

_DEVICE_TREE_SERIAL = Path("/proc/device-tree/serial-number")
_CPUINFO = Path("/proc/cpuinfo")


def read_pi_serial() -> str | None:
    """Return the Pi board serial as uppercase hex, or ``None`` if unavailable."""
    serial = _serial_from_device_tree()
    if serial is None:
        serial = _serial_from_cpuinfo()
    if serial is None:
        return None
    return serial.strip().upper()


def _serial_from_device_tree() -> str | None:
    if not _DEVICE_TREE_SERIAL.is_file():
        return None
    try:
        raw = _DEVICE_TREE_SERIAL.read_bytes()
    except OSError:
        return None
    text = raw.decode("ascii", errors="ignore").strip("\0").strip()
    return text or None


def _serial_from_cpuinfo() -> str | None:
    if not _CPUINFO.is_file():
        return None
    try:
        text = _CPUINFO.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    return serial_from_cpuinfo_text(text)


def serial_from_cpuinfo_text(text: str) -> str | None:
    """Parse ``Serial`` from ``/proc/cpuinfo`` contents (test helper)."""
    for line in text.splitlines():
        if line.lower().startswith("serial"):
            _, _, value = line.partition(":")
            serial = value.strip()
            if serial and serial != "0000000000000000":
                return serial
    return None
