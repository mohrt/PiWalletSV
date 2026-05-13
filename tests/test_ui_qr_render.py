"""QR rendering helper tests."""

from __future__ import annotations

import pytest

from piwallet.ui import qr_render
from piwallet.ui.qr_render import (
    clear_qr_cache,
    paste_qr,
    qr_cache_size,
    render_qr,
)


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


# ---------------------------------------------------------------------------
# Render cache: animated multipart-QR + address screens redraw the same
# payload at ~30 fps; caching the rendered PIL image avoids the per-pixel
# segno + scale loop on every frame and keeps button input responsive on
# the Pi Zero 2 W. These tests pin the LRU contract.
# ---------------------------------------------------------------------------


def test_render_qr_cache_returns_same_instance_for_identical_args() -> None:
    clear_qr_cache()
    a = render_qr("xpub-frame-1", target_px=176, border=2)
    b = render_qr("xpub-frame-1", target_px=176, border=2)
    assert a is b


def test_render_qr_cache_misses_on_different_target_px() -> None:
    clear_qr_cache()
    a = render_qr("addr", target_px=120)
    b = render_qr("addr", target_px=128)
    assert a is not b
    assert a.size == (120, 120)
    assert b.size == (128, 128)


def test_render_qr_cache_misses_on_different_border() -> None:
    clear_qr_cache()
    a = render_qr("addr", target_px=120, border=2)
    b = render_qr("addr", target_px=120, border=4)
    assert a is not b


def test_clear_qr_cache_drops_entries() -> None:
    clear_qr_cache()
    render_qr("foo", target_px=120)
    assert qr_cache_size() == 1
    clear_qr_cache()
    assert qr_cache_size() == 0


def test_render_qr_cache_evicts_lru_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    # Shrink the cap so the test stays fast and obvious.
    monkeypatch.setattr(qr_render, "_QR_CACHE_MAX", 3)
    clear_qr_cache()
    first = render_qr("a", target_px=120)
    render_qr("b", target_px=120)
    render_qr("c", target_px=120)
    # Inserting a 4th entry must evict the oldest ("a").
    render_qr("d", target_px=120)
    assert qr_cache_size() == 3
    # Re-rendering "a" should now miss (i.e., produce a fresh instance).
    new_first = render_qr("a", target_px=120)
    assert new_first is not first


def test_render_qr_cache_reorders_on_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    # With cap=3, touching the oldest before inserting a 4th protects it.
    monkeypatch.setattr(qr_render, "_QR_CACHE_MAX", 3)
    clear_qr_cache()
    first = render_qr("a", target_px=120)
    render_qr("b", target_px=120)
    render_qr("c", target_px=120)
    # Refresh "a"'s LRU position so "b" becomes the eviction target.
    same_first = render_qr("a", target_px=120)
    assert same_first is first
    render_qr("d", target_px=120)
    # "a" must still be cached; "b" should have been evicted.
    still_first = render_qr("a", target_px=120)
    assert still_first is first
