"""First screen for the Waveshare panel: a held QR and a tap target.

This is the bring-up loop, not the wallet UI. It proves the framebuffer
and the touch device on Trixie Lite before the rest of the shell exists.
"""

from __future__ import annotations

import time

from piwallet.touch.input import ScriptedTouch, Tap
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_FG,
    COLOR_OK,
    Display,
    FrameBuffer,
)
from piwallet.ui.qr_render import render_qr


class TouchBringup:
    """Paint a still QR and record the last tap."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.done = False
        self.result: Tap | None = None
        self.last: Tap | None = None
        side = min(width, height) - 80
        self._qr = render_qr("piwallet-touch", target_px=max(80, side))

    def on_tap(self, tap: Tap) -> None:
        self.last = tap
        if tap.pressed:
            self.result = tap

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        qr = self._qr
        x = (self.width - qr.width) // 2
        y = 28
        fb.image.paste(qr, (x, y))
        label = "touch the panel"
        if self.last is not None:
            label = f"{self.last.x},{self.last.y}  down={int(self.last.pressed)}"
        fb.draw.text((8, self.height - 28), label, fill=COLOR_FG)
        color = COLOR_OK if self.last and self.last.pressed else COLOR_ACCENT
        fb.draw.rectangle((self.width - 36, 8, self.width - 8, 36), fill=color)


def run_touch_bringup(
    display: Display,
    touch: ScriptedTouch,
    *,
    target_fps: int = 10,
    max_iterations: int | None = None,
    sleep: bool = True,
) -> Tap | None:
    """Drive :class:`TouchBringup` until ``max_iterations`` or forever."""
    screen = TouchBringup(display.width, display.height)
    fb = FrameBuffer(width=display.width, height=display.height)
    frame_budget = 1.0 / max(1, target_fps)
    iterations = 0
    while True:
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1
        tap = touch.poll()
        if tap is not None:
            screen.on_tap(tap)
        screen.draw(fb)
        display.flip(fb)
        if sleep:
            time.sleep(frame_budget)
    return screen.result
