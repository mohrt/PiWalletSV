"""ShowPhraseScreen tests."""

from __future__ import annotations

import pytest

from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.show_phrase import ShowPhraseScreen


def _evt(b: Button, k: EventKind = EventKind.PRESS) -> Event:
    return Event(button=b, kind=k, at_ms=0)


WORDS_12 = [
    "abandon",
    "ability",
    "able",
    "about",
    "above",
    "absent",
    "absorb",
    "abstract",
    "absurd",
    "abuse",
    "access",
    "accident",
]


def test_pagination_default_4_per_page() -> None:
    s = ShowPhraseScreen(words=WORDS_12)
    assert s.num_pages == 3
    assert s.page == 0


def test_pagination_custom() -> None:
    s = ShowPhraseScreen(words=WORDS_12, per_page=6)
    assert s.num_pages == 2


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        ShowPhraseScreen(words=[])
    with pytest.raises(ValueError):
        ShowPhraseScreen(words=WORDS_12, per_page=0)


def test_right_advances_page() -> None:
    s = ShowPhraseScreen(words=WORDS_12)
    s.on_event(_evt(Button.RIGHT))
    assert s.page == 1
    assert s.done is False


def test_right_on_last_page_completes() -> None:
    s = ShowPhraseScreen(words=WORDS_12, page=2)
    s.on_event(_evt(Button.RIGHT))
    assert s.done is True
    assert s.result is True


def test_a_button_synonym_for_right() -> None:
    s = ShowPhraseScreen(words=WORDS_12)
    s.on_event(_evt(Button.A))
    assert s.page == 1


def test_left_goes_back_clamped_at_zero() -> None:
    s = ShowPhraseScreen(words=WORDS_12, page=1)
    s.on_event(_evt(Button.LEFT))
    assert s.page == 0
    s.on_event(_evt(Button.LEFT))
    assert s.page == 0


def test_b_press_acts_as_left() -> None:
    s = ShowPhraseScreen(words=WORDS_12, page=2)
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.page == 1


def test_b_long_cancels() -> None:
    s = ShowPhraseScreen(words=WORDS_12, page=1)
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is True
    assert s.result is False


def test_events_ignored_after_done() -> None:
    s = ShowPhraseScreen(words=WORDS_12, page=2)
    s.on_event(_evt(Button.RIGHT))
    assert s.done is True
    s.on_event(_evt(Button.LEFT))
    assert s.page == 2


def test_draw_smoke_24_words() -> None:
    fb = FrameBuffer()
    s = ShowPhraseScreen(words=[f"word{i:02d}" for i in range(24)])
    for _ in range(s.num_pages):
        s.draw(fb)
        if not s.done:
            s.on_event(_evt(Button.RIGHT))
