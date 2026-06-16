"""Startup splash screen.

Shows the PiWalletSV logo on boot. Hold **B** for five seconds to
enter factory diagnostics; otherwise the splash continues after a
short timeout.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image

from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import (
    COLOR_BG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    Display,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind, InputManager

_LOGO_PATH = Path(__file__).parent.parent / "assets" / "logo.png"

_LOGO_MAX_W = 180
_LOGO_MAX_H = 180

# Hold duration for factory diagnostics entry on the boot splash only.
BOOT_DIAGNOSTICS_HOLD_MS: int = 5000

BootSplashResult = Literal["continue", "diagnostics"]


def _default_clock_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def load_logo(max_w: int = _LOGO_MAX_W, max_h: int = _LOGO_MAX_H) -> Image.Image:
    """Load, scale, and composite the logo onto a black RGB background."""
    raw = Image.open(_LOGO_PATH).convert("RGBA")
    raw.thumbnail((max_w, max_h), Image.LANCZOS)
    bg = Image.new("RGB", raw.size, COLOR_BG)
    bg.paste(raw, mask=raw.split()[3])
    return bg


@dataclass
class BootSplashScreen:
    """Interactive boot logo — hold B for diagnostics or continue setup."""

    idle_timeout_ms: int = 1500
    diagnostics_hold_ms: int = BOOT_DIAGNOSTICS_HOLD_MS
    clock_ms: Callable[[], int] = field(default=_default_clock_ms)
    done: bool = False
    result: BootSplashResult | None = None
    _logo: Image.Image = field(init=False)
    _logo_pos: tuple[int, int] = field(init=False)
    _started_at_ms: int = field(init=False)
    _b_pressed_at: int | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._logo = load_logo()
        self._logo_pos = (
            (DISPLAY_WIDTH - self._logo.width) // 2,
            (DISPLAY_HEIGHT - self._logo.height) // 2,
        )
        self._started_at_ms = self.clock_ms()

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.B:
            if k == EventKind.PRESS:
                self._b_pressed_at = event.at_ms
            elif k == EventKind.RELEASE:
                self._b_pressed_at = None
        elif b in (Button.A, Button.SELECT) and k == EventKind.PRESS:
            self.done = True
            self.result = "continue"

    def draw(self, fb: FrameBuffer) -> None:
        if not self.done:
            if self._b_pressed_at is not None:
                held = self.clock_ms() - self._b_pressed_at
                if held >= self.diagnostics_hold_ms:
                    self.done = True
                    self.result = "diagnostics"
            else:
                elapsed = self.clock_ms() - self._started_at_ms
                if elapsed >= self.idle_timeout_ms:
                    self.done = True
                    self.result = "continue"

        fb.clear(COLOR_BG)
        fb.image.paste(self._logo, self._logo_pos)


def run_boot_splash(
    display: Display,
    input_mgr: InputManager,
    *,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
) -> BootSplashResult:
    """Show the boot logo until continue or diagnostics is chosen."""
    screen = BootSplashScreen()
    result = run_screen(
        display,
        input_mgr,
        screen,
        target_fps=target_fps,
        idle_wake=idle_wake,
    )
    if result == "diagnostics":
        return "diagnostics"
    return "continue"
