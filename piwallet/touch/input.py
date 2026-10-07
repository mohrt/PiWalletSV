"""Pointer events for a touch panel.

The joystick ``Button`` stream stays in the bonnet shell. This module
reports a press and a coordinate. On the Pi the source is evdev
(ADS7846 from the Waveshare overlay). Tests inject :class:`ScriptedTouch`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Tap:
    x: int
    y: int
    pressed: bool


class ScriptedTouch:
    """Yield a fixed list of taps, then go quiet. For tests."""

    def __init__(self, taps: list[Tap]) -> None:
        self._taps = list(taps)

    def poll(self) -> Tap | None:
        if not self._taps:
            return None
        return self._taps.pop(0)

    def close(self) -> None:
        return None


def take_press_edge(was_pressed: bool, pressed: bool) -> tuple[bool, bool]:
    """Emit one tap when the finger goes down or up, not on each sample.

    Returns ``(emit, was_pressed)``.
    """
    if pressed == was_pressed:
        return False, was_pressed
    return True, pressed


def map_touch(
    raw_x: int,
    raw_y: int,
    *,
    width: int,
    height: int,
    xmin: int,
    xmax: int,
    ymin: int,
    ymax: int,
    swap_axes: bool,
    invert_x: bool,
    invert_y: bool,
) -> tuple[int, int]:
    """Scale an ADS7846 sample onto the panel."""
    if swap_axes:
        px = _scale(raw_y, ymin, ymax, width)
        py = _scale(raw_x, xmin, xmax, height)
    else:
        px = _scale(raw_x, xmin, xmax, width)
        py = _scale(raw_y, ymin, ymax, height)
    if invert_x:
        px = width - 1 - px
    if invert_y:
        py = height - 1 - py
    return px, py


def _scale(raw: int, lo: int, hi: int, span: int) -> int:
    frac = (raw - lo) / (hi - lo)
    px = int(frac * (span - 1))
    return max(0, min(span - 1, px))


class EvdevTouch:
    """Read ABS_X / ABS_Y / BTN_TOUCH from a Linux input device."""

    def __init__(
        self,
        device_path: str,
        width: int,
        height: int,
        *,
        swap_axes: bool,
        invert_x: bool = False,
        invert_y: bool = False,
    ) -> None:
        self.width = width
        self.height = height
        self.swap_axes = swap_axes
        self.invert_x = invert_x
        self.invert_y = invert_y
        self._pressed = False
        self._was_pressed = False
        self._raw_x = 0
        self._raw_y = 0
        self._queued: Tap | None = None
        self._dev = self._open(device_path)

    def _open(self, device_path: str):
        try:
            import evdev
        except ImportError as exc:
            raise RuntimeError("python3-evdev is not installed") from exc
        try:
            dev = evdev.InputDevice(device_path)
        except OSError as exc:
            raise RuntimeError(f"cannot open touch device {device_path}: {exc}") from exc
        info_x = dev.absinfo(evdev.ecodes.ABS_X)
        info_y = dev.absinfo(evdev.ecodes.ABS_Y)
        if info_x is None or info_y is None:
            dev.close()
            raise RuntimeError(f"{device_path} has no absolute axes")
        self._xmin, self._xmax = info_x.min, max(info_x.max, info_x.min + 1)
        self._ymin, self._ymax = info_y.min, max(info_y.max, info_y.min + 1)
        logger.info(
            "touch %s abs x=%s..%s y=%s..%s swap=%s",
            device_path,
            self._xmin,
            self._xmax,
            self._ymin,
            self._ymax,
            self.swap_axes,
        )
        return dev

    def poll(self) -> Tap | None:
        import evdev

        if self._queued is not None:
            tap = self._queued
            self._queued = None
            self._was_pressed = tap.pressed
            return tap

        changed = False
        saw_down = False
        while True:
            event = self._dev.read_one()
            if event is None:
                break
            changed = True
            if event.type == evdev.ecodes.EV_ABS and event.code == evdev.ecodes.ABS_X:
                self._raw_x = event.value
            elif event.type == evdev.ecodes.EV_ABS and event.code == evdev.ecodes.ABS_Y:
                self._raw_y = event.value
            elif event.type == evdev.ecodes.EV_KEY and event.code == evdev.ecodes.BTN_TOUCH:
                if event.value and not self._pressed:
                    saw_down = True
                self._pressed = bool(event.value)
        if not changed:
            return None
        # A quick tap can deliver the press and the lift in one read.
        # Emit the press now and the lift on the next poll, or the digit
        # is thrown away.
        if saw_down and not self._pressed and not self._was_pressed:
            self._was_pressed = True
            px, py = self._map()
            self._queued = Tap(px, py, False)
            return Tap(px, py, True)
        # Keep reporting while the finger is down so the control under it
        # can light up. The lift is a separate event. The screen commits
        # the action on the lift, not on every sample.
        if not self._pressed and not self._was_pressed:
            return None
        self._was_pressed = self._pressed
        px, py = self._map()
        return Tap(px, py, self._pressed)

    def _map(self) -> tuple[int, int]:
        return map_touch(
            self._raw_x,
            self._raw_y,
            width=self.width,
            height=self.height,
            xmin=self._xmin,
            xmax=self._xmax,
            ymin=self._ymin,
            ymax=self._ymax,
            swap_axes=self.swap_axes,
            invert_x=self.invert_x,
            invert_y=self.invert_y,
        )
        return Tap(px, py, self._pressed)

    def close(self) -> None:
        self._dev.close()


def find_touch_device() -> str:
    """Pick the ADS7846 (or any absolute touch) input node."""
    try:
        import evdev
    except ImportError as exc:
        raise RuntimeError("python3-evdev is not installed") from exc
    candidates: list[tuple[str, str]] = []
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        name = dev.name or ""
        caps = dev.capabilities()
        has_abs = evdev.ecodes.EV_ABS in caps
        dev.close()
        if not has_abs:
            continue
        candidates.append((name, path))
    if not candidates:
        raise RuntimeError("no absolute touch device found")
    for name, path in candidates:
        folded = name.casefold()
        if "ads7846" in folded or "touchscreen" in folded:
            return path
    return candidates[0][1]


def open_touch(
    path: str | None,
    width: int,
    height: int,
    *,
    swap_axes: bool,
    invert_x: bool = False,
    invert_y: bool = False,
) -> EvdevTouch:
    return EvdevTouch(
        path or find_touch_device(),
        width,
        height,
        swap_axes=swap_axes,
        invert_x=invert_x,
        invert_y=invert_y,
    )
