"""QR quiet-zone luminance — live adjustment on QR screens.

Phone cameras clip a bright TFT quiet zone. We keep modules black and
dim only the QR *background* (not the whole panel). Levels run 31–255
in steps of 31; default 62 (~24% grey).
"""

from __future__ import annotations

from collections.abc import Callable

from piwallet.ui.input import Button, Event, EventKind

#: Default QR background level (~24% grey).
DEFAULT_QR_BACKGROUND: int = 62

#: Minimum quiet-zone level (below this is effectively black).
QR_BACKGROUND_MIN: int = 31

#: Maximum quiet-zone level (pure white — avoid on the bonnet TFT).
QR_BACKGROUND_MAX: int = 255

#: Step size for UP/DOWN adjustment (eight levels total).
QR_BACKGROUND_STEP: int = 31


def clamp_qr_background(level: int) -> int:
    """Clamp ``level`` into ``[QR_BACKGROUND_MIN, QR_BACKGROUND_MAX]``."""
    return max(QR_BACKGROUND_MIN, min(QR_BACKGROUND_MAX, int(level)))


def qr_background_rgb(level: int) -> tuple[int, int, int]:
    """Return an RGB triple for QR quiet-zone / matte fill."""
    v = clamp_qr_background(level)
    return (v, v, v)


def increase_qr_background(level: int) -> int:
    """Joystick UP — brighter quiet zone (+31)."""
    return clamp_qr_background(level + QR_BACKGROUND_STEP)


def decrease_qr_background(level: int) -> int:
    """Joystick DOWN — dimmer quiet zone (−31)."""
    return clamp_qr_background(level - QR_BACKGROUND_STEP)


def try_qr_brightness_event(
    event: Event,
    level: int,
    *,
    on_changed: Callable[[int], None] | None = None,
) -> int | None:
    """Apply UP/DOWN press/repeat; return new level or ``None`` if unchanged."""
    if event.kind not in (EventKind.PRESS, EventKind.REPEAT):
        return None
    if event.button == Button.UP:
        new_level = increase_qr_background(level)
    elif event.button == Button.DOWN:
        new_level = decrease_qr_background(level)
    else:
        return None
    if new_level == level:
        return None
    if on_changed is not None:
        on_changed(new_level)
    return new_level
