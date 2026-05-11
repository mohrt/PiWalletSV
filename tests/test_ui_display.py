"""Display backend and framebuffer tests."""

from __future__ import annotations

import pytest

from piwallet.ui.display import (
    COLOR_FG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FrameBuffer,
    HeadlessDisplay,
    open_display,
)


def test_framebuffer_default_size_and_clear() -> None:
    fb = FrameBuffer()
    assert fb.size == (DISPLAY_WIDTH, DISPLAY_HEIGHT)
    # Background defaults to black.
    assert fb.image.getpixel((0, 0)) == (0, 0, 0)
    fb.draw.rectangle((10, 10, 30, 30), fill=COLOR_FG)
    assert fb.image.getpixel((20, 20)) == COLOR_FG
    fb.clear()
    assert fb.image.getpixel((20, 20)) == (0, 0, 0)


def test_headless_display_flip_copies_buffer() -> None:
    display = HeadlessDisplay()
    fb = FrameBuffer()
    fb.draw.rectangle((0, 0, 240, 240), fill=COLOR_FG)

    assert display.flip_count == 0
    display.flip(fb)
    assert display.flip_count == 1
    assert display.pixel_at(5, 5) == COLOR_FG

    # Mutating the framebuffer after flip must NOT affect the displayed
    # image (atomic flip guarantee).
    fb.clear()
    assert display.pixel_at(5, 5) == COLOR_FG
    display.flip(fb)
    assert display.pixel_at(5, 5) == (0, 0, 0)
    assert display.flip_count == 2


def test_headless_display_rejects_size_mismatch() -> None:
    display = HeadlessDisplay(width=120, height=120)
    fb = FrameBuffer(width=240, height=240)
    with pytest.raises(ValueError, match="framebuf size"):
        display.flip(fb)


def test_open_display_headless() -> None:
    d = open_display("headless")
    assert isinstance(d, HeadlessDisplay)


def test_open_display_auto_falls_back_to_headless_on_mac() -> None:
    # On macOS the Adafruit stack is not installable, so 'auto' must
    # gracefully degrade.
    d = open_display("auto")
    assert isinstance(d, HeadlessDisplay)


def test_open_display_st7789_raises_without_extras() -> None:
    with pytest.raises(RuntimeError, match="display"):
        open_display("st7789")


def test_open_display_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="unknown display backend"):
        open_display("oscilloscope")
