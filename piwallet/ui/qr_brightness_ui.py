"""On-screen hints for live QR background adjustment."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from piwallet.ui.display import COLOR_FG, DISPLAY_HEIGHT, DISPLAY_WIDTH, FrameBuffer
from piwallet.ui.qr_render import QR_PANEL_FOOTER_H
from piwallet.ui.widgets import draw_text

#: How long the ↑/↓ brightness toast stays visible on entry and after each tweak.
QR_BRIGHTNESS_HINT_MS: int = 1500

_FOOTER_BAR_H: int = QR_PANEL_FOOTER_H
_TOAST_H: int = 34
_TOAST_PAD_X: int = 10


def _default_clock_ms() -> int:
    return time.monotonic_ns() // 1_000_000


@dataclass
class QrBrightnessHint:
    """Tracks whether the QR brightness toast should paint this frame."""

    hint_ms: int = QR_BRIGHTNESS_HINT_MS
    clock_ms: Callable[[], int] = field(default=_default_clock_ms)
    until_ms: int = field(init=False)

    def __post_init__(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Show (or extend) the toast — call on screen open and after UP/DOWN."""
        self.until_ms = self.clock_ms() + self.hint_ms

    def visible(self) -> bool:
        return self.clock_ms() < self.until_ms


def qr_footer_y() -> int:
    """Vertical center for footer hint text on the bottom bar."""
    return DISPLAY_HEIGHT - _FOOTER_BAR_H // 2 + 1


def draw_qr_screen_footer(fb: FrameBuffer, *, back_label: str = "A/B back") -> None:
    """Black footer bar with a readable ↑/↓ QR hint (always visible)."""
    y0 = DISPLAY_HEIGHT - _FOOTER_BAR_H
    fb.draw.rectangle((0, y0, DISPLAY_WIDTH, DISPLAY_HEIGHT), fill=(20, 20, 32))
    draw_text(
        fb,
        DISPLAY_WIDTH // 2,
        qr_footer_y(),
        f"↑↓ QR light {back_label}",
        size=10,
        color=COLOR_FG,
        anchor="mm",
    )


def draw_qr_brightness_toast(fb: FrameBuffer, *, bottom_y: int) -> None:
    """Semi-opaque toast just above the footer — ↑ brighter / ↓ dimmer QR."""
    toast_bottom = bottom_y - 4
    toast_top = toast_bottom - _TOAST_H
    fb.draw.rectangle(
        (_TOAST_PAD_X, toast_top, DISPLAY_WIDTH - _TOAST_PAD_X, toast_bottom),
        fill=(20, 20, 32),
        outline=COLOR_FG,
    )
    cx = DISPLAY_WIDTH // 2
    draw_text(fb, cx, toast_top + 10, "↑ Brighter QR", size=10, color=COLOR_FG, anchor="mm")
    draw_text(fb, cx, toast_top + 24, "↓ Dimmer QR", size=10, color=COLOR_FG, anchor="mm")
