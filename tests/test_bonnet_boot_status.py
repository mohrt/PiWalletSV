"""Boot status screen tests."""

from __future__ import annotations

from piwallet.bonnet.boot_status import paint_boot_status
from piwallet.ui.display import COLOR_BG, FrameBuffer, HeadlessDisplay


def test_paint_boot_status_draws_title_and_subtitle() -> None:
    disp = HeadlessDisplay()
    fb = FrameBuffer()
    paint_boot_status(disp, fb, subtitle="Booting", anim_frame=2)
    disp.flip(fb)
    # Title + subtitle should introduce non-background pixels.
    pixels = list(disp.image.getdata())
    assert any(p != COLOR_BG for p in pixels)
