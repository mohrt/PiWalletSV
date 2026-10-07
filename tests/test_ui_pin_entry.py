"""PIN entry screen tests."""

from __future__ import annotations

import pytest

from piwallet.core.vault import PIN_MAX_LEN, PIN_MIN_LEN
from piwallet.ui.display import COLOR_BG, FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.pin_entry import PinEntryScreen, attempts_subtitle


def _evt(button: Button, kind: EventKind = EventKind.PRESS, at_ms: int = 0) -> Event:
    return Event(button=button, kind=kind, at_ms=at_ms)


def _set_chars(screen: PinEntryScreen, chars: str) -> None:
    """Seed filled cells and confirm with A (bypasses cycling)."""
    screen.digits = list(chars)
    screen.length = len(chars)
    screen.cursor = len(chars) - 1
    screen.on_event(_evt(Button.A))


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_default_starts_at_six_empty_cells() -> None:
    s = PinEntryScreen()
    assert s.length == PIN_MIN_LEN
    assert s.digits == [None] * PIN_MIN_LEN
    assert s.cursor == 0


def test_custom_length_validates_range() -> None:
    PinEntryScreen(length=PIN_MIN_LEN)
    PinEntryScreen(length=PIN_MAX_LEN)
    with pytest.raises(ValueError):
        PinEntryScreen(length=PIN_MIN_LEN - 1)
    with pytest.raises(ValueError):
        PinEntryScreen(length=PIN_MAX_LEN + 1)


def test_legacy_int_digit_seed_accepted() -> None:
    s = PinEntryScreen(digits=[1, 2, 3, 4, 5, 6])
    assert s.digits == ["1", "2", "3", "4", "5", "6"]
    assert s.pin_value() == "123456"


# ---------------------------------------------------------------------------
# Classic 6-digit path (backward compatible)
# ---------------------------------------------------------------------------


def test_up_starts_from_none_at_zero() -> None:
    s = PinEntryScreen()
    s.on_event(_evt(Button.UP))
    assert s.digits[0] == "0"
    s.on_event(_evt(Button.UP))
    assert s.digits[0] == "1"


def test_down_starts_from_none_at_zero_then_wraps() -> None:
    s = PinEntryScreen()
    s.on_event(_evt(Button.DOWN))
    assert s.digits[0] == "0"
    s.on_event(_evt(Button.DOWN))
    assert s.digits[0] == "z"  # wraps past 0 into letters (lower)


def test_six_digit_confirm_works_like_before() -> None:
    s = PinEntryScreen(digits=[1, 2, 3, 4, 5, 6])
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "123456"


def test_backspace_at_min_length_clears_in_place() -> None:
    s = PinEntryScreen(digits=["1", "2", "3", None, None, None], cursor=2)
    s.on_event(_evt(Button.B))
    assert s.length == PIN_MIN_LEN
    assert s.digits[2] is None
    assert s.cursor == 2


# ---------------------------------------------------------------------------
# Grow / shrink / letters / case
# ---------------------------------------------------------------------------


def test_right_on_last_cell_grows() -> None:
    s = PinEntryScreen(digits=["1", "2", "3", "4", "5", "6"], cursor=5)
    s.on_event(_evt(Button.RIGHT))
    assert s.length == 7
    assert s.digits[6] is None
    assert s.cursor == 6


def test_cannot_move_horizontally_on_empty_cell() -> None:
    s = PinEntryScreen()
    s.on_event(_evt(Button.RIGHT))
    assert s.cursor == 0
    assert s.length == PIN_MIN_LEN
    s.on_event(_evt(Button.UP))  # fill with "0"
    s.on_event(_evt(Button.RIGHT))
    assert s.cursor == 1
    s.on_event(_evt(Button.LEFT))  # cell 1 still empty — blocked
    assert s.cursor == 1
    s.on_event(_evt(Button.UP))
    s.on_event(_evt(Button.LEFT))
    assert s.cursor == 0


def test_grow_caps_at_max() -> None:
    s = PinEntryScreen(length=PIN_MAX_LEN, digits=[None] * PIN_MAX_LEN)
    s.cursor = PIN_MAX_LEN - 1
    s.on_event(_evt(Button.RIGHT))
    assert s.length == PIN_MAX_LEN


def test_backspace_above_min_shrinks() -> None:
    s = PinEntryScreen(digits=["1", "2", "3", "4", "5", "6", "7"], cursor=3)
    s.on_event(_evt(Button.B))
    assert s.length == 6
    assert s.digits == ["1", "2", "3", "5", "6", "7"]
    assert s.cursor == 3


def test_cycle_reaches_letters_after_digits() -> None:
    s = PinEntryScreen()
    # 10 UPs from None: 0 then 1..9 then 'a'
    for _ in range(11):
        s.on_event(_evt(Button.UP))
    assert s.digits[0] == "a"


def test_select_toggles_case_and_converts_current_letter() -> None:
    s = PinEntryScreen(digits=["a", None, None, None, None, None], cursor=0)
    s.on_event(_evt(Button.SELECT))
    assert s.upper is True
    assert s.digits[0] == "A"
    s.on_event(_evt(Button.SELECT))
    assert s.upper is False
    assert s.digits[0] == "a"


def test_alphanumeric_pin_confirm() -> None:
    s = PinEntryScreen()
    _set_chars(s, "Ab12cd")
    assert s.result == "Ab12cd"


def test_preview_shows_full_pin_with_underscores() -> None:
    s = PinEntryScreen(digits=["1", "2", None, None, None, None])
    assert s.typed_text() == "12____"


def test_a_advances_to_next_empty_when_incomplete() -> None:
    s = PinEntryScreen(digits=["1", None, "3", None, None, None], cursor=0)
    s.on_event(_evt(Button.A))
    assert s.done is False
    assert s.cursor == 1


def test_reset_returns_to_six_empty() -> None:
    s = PinEntryScreen(digits=list("1234567"), cursor=3)
    s.done = True
    s.result = "1234567"
    s.reset()
    assert s.length == PIN_MIN_LEN
    assert s.digits == [None] * PIN_MIN_LEN
    assert s.cursor == 0
    assert s.done is False
    assert s.result is None


def test_repeat_throttle_on_digit_cycle() -> None:
    s = PinEntryScreen()
    s.on_event(_evt(Button.UP, at_ms=0))
    assert s.digits[0] == "0"
    # Immediate REPEAT ignored.
    s.on_event(_evt(Button.UP, EventKind.REPEAT, at_ms=50))
    assert s.digits[0] == "0"
    s.on_event(_evt(Button.UP, EventKind.REPEAT, at_ms=400))
    assert s.digits[0] == "1"


def test_draw_smoke() -> None:
    fb = FrameBuffer()
    fb.clear(COLOR_BG)
    PinEntryScreen().draw(fb)
    PinEntryScreen(digits=list("Ab12Xy"), masked=True).draw(fb)


def test_attempts_subtitle() -> None:
    text, _color = attempts_subtitle(5)
    assert "5 attempts" in text
    text, _color = attempts_subtitle(1)
    assert "wipe" in text.lower()
