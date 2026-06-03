"""Startup splash screen.

Displays the PiWalletSV logo centred on the 240×240 panel for a fixed
duration. The logo is composited once and the result sent as a single
SPI transfer; repeating full-panel writes at 30 fps left the ST7789 in
a state that caused all subsequent frames to appear black.
"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from piwallet.ui.display import (
    COLOR_BG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    Display,
    FrameBuffer,
)

_LOGO_PATH = Path(__file__).parent.parent / "assets" / "logo.png"

_LOGO_MAX_W = 180
_LOGO_MAX_H = 180


def _load_logo(max_w: int = _LOGO_MAX_W, max_h: int = _LOGO_MAX_H) -> Image.Image:
    """Load, scale, and composite the logo onto a black RGB background."""
    raw = Image.open(_LOGO_PATH).convert("RGBA")
    raw.thumbnail((max_w, max_h), Image.LANCZOS)
    # Composite onto a solid black background so the result is pure RGB —
    # avoids sending any RGBA data through the SPI path.
    bg = Image.new("RGB", raw.size, COLOR_BG)
    bg.paste(raw, mask=raw.split()[3])
    return bg


def show_splash_once(display: Display, duration_s: float = 2.0) -> None:
    """Draw the logo, send one SPI frame, sleep, then return."""
    logo = _load_logo()
    fb = FrameBuffer(display.width, display.height)
    x = (DISPLAY_WIDTH - logo.width) // 2
    y = (DISPLAY_HEIGHT - logo.height) // 2
    fb.image.paste(logo, (x, y))
    display.flip(fb)
    time.sleep(duration_s)
