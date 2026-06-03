"""PairingMultipartQrScreen auto-advance and input."""

from __future__ import annotations

import pytest

from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.pairing_multipart_qr_screen import (
    PairingMultipartQrScreen,
    _max_qr_px_for_footer,
)


def test_max_qr_px_reserves_footer_gap() -> None:
    # Matches the current PairingMultipartQrScreen layout: 18-px title +
    # 4-px gap (qr_y=22), single 10-px-tall footer hint centered at y=230,
    # 6-px breathing room between QR bottom and footer center. The
    # resulting 196-px QR area is what gives v6 frames their 4 px/module
    # rendering — the threshold below which phone cameras struggle to
    # autofocus on the TFT.
    assert _max_qr_px_for_footer(qr_top_y=22, first_footer_center_y=230, gap_px=6) == 196


def test_pairing_multipart_qr_requires_non_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        PairingMultipartQrScreen([])


def test_pairing_multipart_qr_auto_advances_on_draw() -> None:
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
    assert s.idx == 1

    t["ms"][0] = 200
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


def test_b_long_returns_exit() -> None:
    s = PairingMultipartQrScreen(["a", "b"])
    s.on_event(Event(button=Button.B, kind=EventKind.LONG, at_ms=0))
    assert s.done is True
    assert s.result == "exit"

