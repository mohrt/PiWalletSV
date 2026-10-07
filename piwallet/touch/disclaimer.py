"""Touch disclaimer, shown once before PIN setup.

The Zero walks three pages and says "Hold A to accept." This panel
fits the same warnings on one screen. Hold Accept, or power off.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from piwallet.touch.input import ScriptedTouch, Tap
from piwallet.touch.ui import Hit
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    Display,
    FrameBuffer,
)
from piwallet.ui.widgets import draw_text, text_bbox

HOLD_S = 0.7

# Same warnings as the Zero pages, without the joystick instructions.
_SECTIONS: tuple[tuple[str, str], ...] = (
    (
        "Beta software",
        "PiWalletSV is beta — fully functional, no known issues. "
        "Fixes and notices via @PiWalletSV. Funds are always recoverable "
        "with your seed phrase.",
    ),
    (
        "Your seed phrase",
        "Your seed phrase is the only way to recover funds. "
        "Keep it offline. Don't share it. Don't photograph it.",
    ),
    (
        "No liability",
        "The authors disclaim all liability. Use at your own risk. "
        "Selling a commercial kit or case needs permission (@PiWalletSV).",
    ),
)


class TouchDisclaimer:
    """One screen. ``holding`` is true while Accept is pressed."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.holding = False
        self._down: str | None = None

    def hits(self) -> list[Hit]:
        y = self.height - 64
        return [Hit("accept", 8, y, self.width - 8, self.height - 8)]

    def on_tap(self, tap: Tap) -> None:
        hit = self._at(tap.x, tap.y)
        if tap.pressed:
            self._down = hit
            self.holding = hit == "accept"
            return
        self._down = None
        self.holding = False

    def _at(self, x: int, y: int) -> str | None:
        for item in self.hits():
            if item.contains(x, y):
                return item.id
        return None

    def draw(self, fb: FrameBuffer, *, held_for: float) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Disclaimer", size=18, color=COLOR_FG)
        y = 48
        for title, body in _SECTIONS:
            draw_text(fb, 16, y, title, size=16, color=COLOR_FG)
            y += 22
            for line in _wrap(body, self.width - 32, size=15):
                draw_text(fb, 16, y, line, size=15, color=COLOR_DIM)
                y += 20
            y += 12
        self._draw_hold(fb, held_for)
        labels = {"accept": "Hold to accept"}
        for item in self.hits():
            held = item.id == self._down
            fb.draw.rounded_rectangle(
                (item.x0, item.y0, item.x1 - 1, item.y1 - 1),
                radius=8,
                fill=COLOR_DANGER if held else (24, 24, 24),
                outline=COLOR_FG if held else COLOR_DANGER,
                width=3 if held else 2,
            )
            draw_text(
                fb,
                *item.center(),
                labels[item.id],
                size=16,
                color=COLOR_BG if held else COLOR_FG,
                anchor="mm",
            )

    def _draw_hold(self, fb: FrameBuffer, held_for: float) -> None:
        progress = 0.0 if held_for <= 0 else min(1.0, held_for / HOLD_S)
        if progress <= 0:
            return
        pad = 16
        bar_y = self.height - 80
        width = self.width - 2 * pad
        fb.draw.rectangle((pad, bar_y, pad + width, bar_y + 6), fill=(40, 40, 48))
        fill = round(width * progress)
        if fill > 0:
            fb.draw.rectangle((pad, bar_y, pad + fill, bar_y + 6), fill=COLOR_DANGER)


def run_touch_disclaimer(
    display: Display,
    touch: ScriptedTouch,
    *,
    hold_s: float = HOLD_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: bool = True,
    poll_s: float = 1 / 30,
) -> bool:
    """Show the disclaimer until Accept is held."""
    flow = TouchDisclaimer(display.width, display.height)
    fb = FrameBuffer(width=display.width, height=display.height)
    held_at: float | None = None
    while True:
        tap = touch.poll()
        now = clock()
        if tap is not None:
            flow.on_tap(tap)
            if flow.holding:
                if held_at is None:
                    held_at = now
            else:
                held_at = None
        held_for = 0.0 if held_at is None else now - held_at
        if held_at is not None and held_for >= hold_s:
            return True
        flow.draw(fb, held_for=held_for)
        display.flip(fb)
        if sleep:
            remaining = poll_s - (time.monotonic() - now)
            if remaining > 0:
                time.sleep(remaining)


def _wrap(text: str, width: int, *, size: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = word if not current else f"{current} {word}"
        if text_bbox(trial, size=size)[2] > width and current:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines
