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


def test_console_claim_switches_the_vt_to_graphics(monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl

    from piwallet.ui.display import _KD_GRAPHICS, _KD_TEXT, _KDSETMODE, claim_linux_console

    calls: list[tuple[int, int]] = []

    def open_tty(path: str, flags: int) -> int:
        import os

        assert path == "/dev/tty0"
        assert flags & os.O_ACCMODE == os.O_WRONLY
        return 7

    def ioctl(fd: int, request: int, arg: int = 0) -> int:
        calls.append((request, arg))
        return 0

    closed: list[int] = []
    monkeypatch.setattr("os.open", open_tty)
    monkeypatch.setattr("os.close", lambda fd: closed.append(fd))
    monkeypatch.setattr(fcntl, "ioctl", ioctl)

    claim = claim_linux_console()
    assert claim.tty_fd == 7
    assert calls == [(_KDSETMODE, _KD_GRAPHICS)]
    claim.release()
    assert calls == [(_KDSETMODE, _KD_GRAPHICS), (_KDSETMODE, _KD_TEXT)]
    assert closed == [7]
    assert claim.tty_fd is None


def test_console_claim_turns_blink_off_when_the_tty_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from piwallet.ui.display import claim_linux_console

    blink = tmp_path / "cursor_blink"
    blink.write_text("1\n", encoding="ascii")
    monkeypatch.setattr("piwallet.ui.display._CURSOR_BLINK", str(blink))

    def no_tty(*_args: object, **_kwargs: object) -> int:
        raise OSError("no tty")

    monkeypatch.setattr("os.open", no_tty)

    claim = claim_linux_console()
    assert claim.tty_fd is None
    assert blink.read_text(encoding="ascii") == "0\n"
    claim.release()
    assert blink.read_text(encoding="ascii") == "1\n"
