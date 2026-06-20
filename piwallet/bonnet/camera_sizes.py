"""Picamera2 capture sizes tuned per SoC (Pi Zero W is armv6 / tight CMA)."""

from __future__ import annotations

import platform

_CAPTURE_SIZES_ARMV6: list[tuple[int, int]] = [
    (640, 480),
    (480, 360),
    (416, 312),
]
_CAPTURE_SIZES_DEFAULT: list[tuple[int, int]] = [
    (1280, 960),
    (640, 480),
    (480, 360),
    (416, 312),
]


def capture_sizes_for_machine() -> list[tuple[int, int]]:
    machine = platform.machine().lower()
    if machine.startswith("armv6"):
        return list(_CAPTURE_SIZES_ARMV6)
    return list(_CAPTURE_SIZES_DEFAULT)


def bonnet_live_preview_enabled() -> bool:
    """Live TFT preview while aiming before capture."""
    return True
