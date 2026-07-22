"""PairingMultipartQrScreen auto-advance and input."""

from __future__ import annotations

import pytest

from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.pairing_multipart_qr_screen import (
    PairingMultipartQrScreen,
    _max_qr_px_for_footer,
)
from piwallet.ui.qr_brightness_ui import qr_footer_y
from piwallet.ui.qr_render import QR_LIGHT_BG


def test_max_qr_px_reserves_footer_gap() -> None:
    # Bottom bar is 22 px; footer text is centered at qr_footer_y() (~230).
    footer_y = qr_footer_y()
    assert _max_qr_px_for_footer(qr_top_y=22, first_footer_center_y=footer_y, gap_px=6) == 196


def test_pairing_multipart_qr_requires_non_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        PairingMultipartQrScreen([])


def test_pairing_multipart_qr_auto_advances_after_entry_hint() -> None:
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

    t["ms"][0] = 100
    s.draw(fb)
    assert s.idx == 0

    # The initial QR-brightness hint deliberately holds the first frame long
    # enough to read; rotation resumes when that 1.5 second hint expires.
    t["ms"][0] = 1500
    s.draw(fb)
    assert s.idx == 1

    t["ms"][0] = 1600
    s.draw(fb)
    assert s.idx == 0


def test_b_press_returns_back() -> None:
    s = PairingMultipartQrScreen(["a", "b"])
    s.on_event(Event(button=Button.B, kind=EventKind.PRESS, at_ms=0))
    assert s.done is True
    assert s.result == "back"


def test_a_press_returns_back() -> None:
    s = PairingMultipartQrScreen(["a", "b"])
    s.on_event(Event(button=Button.A, kind=EventKind.PRESS, at_ms=0))
    assert s.done is True
    assert s.result == "back"


def test_select_press_returns_back() -> None:
    s = PairingMultipartQrScreen(["a", "b"])
    s.on_event(Event(button=Button.SELECT, kind=EventKind.PRESS, at_ms=0))
    assert s.done is True
    assert s.result == "back"


def test_b_long_is_ignored() -> None:
    s = PairingMultipartQrScreen(["a", "b"])
    s.on_event(Event(button=Button.B, kind=EventKind.LONG, at_ms=0))
    assert s.done is False


def test_draw_fills_grey_panel_behind_qr() -> None:
    fb = FrameBuffer()
    PairingMultipartQrScreen(["line-a"]).draw(fb)
    assert fb.image.getpixel((8, 24)) == QR_LIGHT_BG


def test_up_down_adjusts_qr_background_and_restarts_sequence() -> None:
    t = {"ms": [1000]}

    def clock() -> int:
        return t["ms"][0]

    s = PairingMultipartQrScreen(
        ["line-a", "line-b"],
        clock_ms=clock,
        auto_advance_ms=500,
    )
    s.idx = 1
    s.on_event(Event(button=Button.DOWN, kind=EventKind.PRESS, at_ms=0))
    assert s.qr_background == 31
    assert s.idx == 0
