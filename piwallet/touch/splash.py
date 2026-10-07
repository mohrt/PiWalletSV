"""Boot logo for the touch panel.

The PiWalletSV logo fills the screen for a couple of seconds. Hold a
finger for five seconds, the same gesture as holding B on the Zero, to
open factory diagnostics.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from piwallet.bonnet.splash import BOOT_DIAGNOSTICS_HOLD_MS, load_logo
from piwallet.touch.input import ScriptedTouch
from piwallet.ui.display import COLOR_BG, Display, FrameBuffer

SPLASH_IDLE_S = 2.0
SPLASH_HOLD_S = BOOT_DIAGNOSTICS_HOLD_MS / 1000


def run_touch_splash(
    display: Display,
    touch: ScriptedTouch,
    *,
    idle_s: float = SPLASH_IDLE_S,
    hold_s: float = SPLASH_HOLD_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: bool = True,
    poll_s: float = 1 / 30,
) -> str:
    """Show the logo. Return ``continue`` or ``diagnostics``."""
    logo = load_logo(display.width, display.height)
    origin = (
        (display.width - logo.width) // 2,
        (display.height - logo.height) // 2,
    )
    fb = FrameBuffer(width=display.width, height=display.height)
    started = clock()
    held_at: float | None = None
    while True:
        tap = touch.poll()
        now = clock()
        if tap is not None:
            if tap.pressed:
                if held_at is None:
                    held_at = now
            else:
                held_at = None
        if held_at is not None and now - held_at >= hold_s:
            return "diagnostics"
        if held_at is None and now - started >= idle_s:
            return "continue"
        fb.clear(COLOR_BG)
        fb.image.paste(logo, origin)
        display.flip(fb)
        if sleep:
            remaining = poll_s - (time.monotonic() - now)
            if remaining > 0:
                time.sleep(remaining)
