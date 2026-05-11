"""QR rendering helper tests."""

from __future__ import annotations

import pytest

from piwallet.ui.qr_render import paste_qr, render_qr


def test_render_qr_string_payload_produces_square_image() -> None:
    img = render_qr("hello", target_px=120)
    assert img.size == (120, 120)
    assert img.mode == "RGB"


def test_render_qr_bytes_payload_produces_square_image() -> None:
    img = render_qr(b"\x00\x01\x02\x03", target_px=120)
    assert img.size == (120, 120)


def test_render_qr_uses_high_contrast_pixels() -> None:
    img = render_qr("test", target_px=200, fg=(0, 0, 0), bg=(255, 255, 255))
    # We should see both colors somewhere in the inner region.
    saw_fg = False
    saw_bg = False
    for x in range(20, 180, 5):
        for y in range(20, 180, 5):
            p = img.getpixel((x, y))
            if p == (0, 0, 0):
                saw_fg = True
            elif p == (255, 255, 255):
                saw_bg = True
    assert saw_fg and saw_bg


def test_render_qr_rejects_too_small_target() -> None:
    with pytest.raises(ValueError):
        render_qr("x", target_px=10)


def test_render_qr_handles_long_payload() -> None:
    """A typical BSV address (~34 chars) must fit at 180x180 px."""
    address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
    img = render_qr(address, target_px=180)
    assert img.size == (180, 180)


def test_paste_qr_composites_at_offset() -> None:
    from PIL import Image
    canvas = Image.new("RGB", (240, 240), (0, 0, 0))
    qr = render_qr("abc", target_px=100, bg=(200, 200, 200))
    paste_qr(canvas, qr, x=30, y=40)
    # A pixel inside the pasted region should be the QR background (200).
    p = canvas.getpixel((35, 45))
    # It might be fg or bg — but should not be the original (0,0,0) background.
    assert p != (0, 0, 0)
