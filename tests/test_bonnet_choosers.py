"""WordCountChooser and EntropySourceChooser unit tests.

The two chooser screens are tiny ListView wrappers but they own one
piece of bespoke logic: B is "cancel/back" on both press lengths.
The rest of the bonnet flow gates on ``result is None`` to detect
the cancel case, so these tests pin down both press shapes.
"""

from __future__ import annotations

from piwallet.bonnet.choosers import EntropySourceChooser, WordCountChooser
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


def _evt(b: Button, k: EventKind = EventKind.PRESS) -> Event:
    return Event(button=b, kind=k, at_ms=0)


# ---------------------------------------------------------------------------
# WordCountChooser
# ---------------------------------------------------------------------------


def test_word_count_a_press_on_default_picks_12() -> None:
    s = WordCountChooser()
    s.on_event(_evt(Button.A))
    assert s.done and s.result == 12


def test_word_count_down_then_a_picks_24() -> None:
    s = WordCountChooser()
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.A))
    assert s.done and s.result == 24


def test_word_count_long_b_cancels() -> None:
    s = WordCountChooser()
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done and s.result is None


def test_word_count_short_b_press_also_cancels() -> None:
    """A short tap of B should be a cancel/back, not just a long hold."""
    s = WordCountChooser()
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.done and s.result is None


def test_word_count_draw_smoke() -> None:
    fb = FrameBuffer()
    WordCountChooser().draw(fb)


# ---------------------------------------------------------------------------
# EntropySourceChooser
# ---------------------------------------------------------------------------


def test_entropy_source_a_press_picks_csr() -> None:
    s = EntropySourceChooser()
    s.on_event(_evt(Button.A))
    assert s.done and s.result == "csr"


def test_entropy_source_long_b_cancels() -> None:
    s = EntropySourceChooser()
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done and s.result is None


def test_entropy_source_short_b_press_also_cancels() -> None:
    s = EntropySourceChooser()
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.done and s.result is None


def test_entropy_source_draw_smoke() -> None:
    fb = FrameBuffer()
    EntropySourceChooser().draw(fb)
