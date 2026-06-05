"""QR brightness on-screen hints."""

from __future__ import annotations

from piwallet.ui.display import FrameBuffer
from piwallet.ui.qr_brightness_ui import draw_qr_brightness_toast
from piwallet.ui.pairing_multipart_qr_screen import PairingMultipartQrScreen


def test_hint_visible_on_first_draw() -> None:
    t = {"ms": [0]}

    def clock() -> int:
        return t["ms"][0]

    s = PairingMultipartQrScreen(["a"], clock_ms=clock)
    assert s._brightness_hint.visible()


def test_animation_pauses_while_hint_visible() -> None:
    t = {"ms": [0]}

    def clock() -> int:
        return t["ms"][0]

    s = PairingMultipartQrScreen(
        ["line-a", "line-b"],
        clock_ms=clock,
        auto_advance_ms=100,
    )
    fb = FrameBuffer()
    s.draw(fb)
    assert s.idx == 0
    t["ms"][0] = 200
    s.draw(fb)
    assert s.idx == 0


def test_toast_draws_on_framebuffer() -> None:
    fb = FrameBuffer()
    draw_qr_brightness_toast(fb, bottom_y=200)
    # Dark toast fill should differ from default black background.
    assert fb.image.getpixel((120, 180)) != (0, 0, 0)
