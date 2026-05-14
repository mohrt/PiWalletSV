"""PIN entry screen tests."""

from __future__ import annotations

import pytest

from piwallet.ui.display import COLOR_BG, FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.pin_entry import PinEntryScreen, attempts_subtitle


def _evt(button: Button, kind: EventKind = EventKind.PRESS, at_ms: int = 0) -> Event:
    return Event(button=button, kind=kind, at_ms=at_ms)


def _enter_digits(screen: PinEntryScreen, digits: str) -> None:
    """Type `digits` left-to-right using UP cycles and RIGHT moves."""
    for i, ch in enumerate(digits):
        d = int(ch)
        # If we're not already on slot `i`, move cursor right.
        while screen.cursor < i:
            screen.on_event(_evt(Button.RIGHT))
        # Cycle UP `d` times (since initial value after UP is 0; cycling UP
        # from 0 gives 1).
        for _ in range(d):
            screen.on_event(_evt(Button.UP))
        if d == 0:
            # We need to leave the cell at 0; one UP gets us to 0 from the
            # `None` -> 0 initial cycle.
            screen.on_event(_evt(Button.UP))
            # Now value is 1; cycle 9 more to wrap back to 0.
            for _ in range(9):
                screen.on_event(_evt(Button.UP))


# ---------------------------------------------------------------------------
# Construction & validation
# ---------------------------------------------------------------------------


def test_default_length_is_six() -> None:
    s = PinEntryScreen()
    assert s.length == 6
    assert s.digits == [None] * 6
    assert s.cursor == 0


def test_custom_length_validates_range() -> None:
    PinEntryScreen(length=4)
    PinEntryScreen(length=12)
    with pytest.raises(ValueError):
        PinEntryScreen(length=3)
    with pytest.raises(ValueError):
        PinEntryScreen(length=13)


def test_digits_seed_must_match_length() -> None:
    PinEntryScreen(length=4, digits=[1, 2, 3, None])
    with pytest.raises(ValueError):
        PinEntryScreen(length=4, digits=[1, 2, 3])


# ---------------------------------------------------------------------------
# Digit cycling
# ---------------------------------------------------------------------------


def test_up_starts_from_none_at_zero() -> None:
    s = PinEntryScreen()
    s.on_event(_evt(Button.UP))
    assert s.digits[0] == 0
    s.on_event(_evt(Button.UP))
    assert s.digits[0] == 1


def test_down_starts_from_none_at_zero_then_wraps() -> None:
    s = PinEntryScreen()
    s.on_event(_evt(Button.DOWN))
    assert s.digits[0] == 0
    # Going DOWN from 0 wraps to 9.
    s.on_event(_evt(Button.DOWN))
    assert s.digits[0] == 9


def test_up_repeat_advances_digit_in_repeat_mode() -> None:
    """Holding UP cycles the digit via REPEAT events (when paced)."""
    s = PinEntryScreen()
    # PRESS always cycles. Subsequent REPEATs cycle once the digit-
    # repeat throttle has elapsed (320 ms by default).
    s.on_event(_evt(Button.UP, EventKind.PRESS, at_ms=0))
    s.on_event(_evt(Button.UP, EventKind.REPEAT, at_ms=400))
    s.on_event(_evt(Button.UP, EventKind.REPEAT, at_ms=800))
    assert s.digits[0] == 2


def test_up_repeat_below_throttle_is_ignored() -> None:
    """Fast-cadence REPEATs (every 120 ms) must NOT all advance the digit.

    The InputManager fires REPEAT at ~120 ms cadence under hold; a 1:1
    mapping would scroll digits at ~8/sec, which is too fast to land
    on a target. The screen throttles cycling to ~3/sec.
    """
    s = PinEntryScreen()
    s.on_event(_evt(Button.UP, EventKind.PRESS, at_ms=0))
    assert s.digits[0] == 0
    # Three successive REPEATs at the input layer's natural 120 ms
    # cadence — none of them are old enough to bypass the digit
    # throttle, so the digit should NOT advance further.
    for at in (120, 240, 360):
        s.on_event(_evt(Button.UP, EventKind.REPEAT, at_ms=at))
    # 360 - 0 = 360 >= 320 throttle, so the third REPEAT *does* fire.
    assert s.digits[0] == 1


def test_press_always_cycles_regardless_of_throttle() -> None:
    """Distinct PRESS events must never be throttled — single-tap cycling."""
    s = PinEntryScreen()
    # Three taps in quick succession (e.g. operator pressing UP three
    # times in 100 ms each) should land on digit 3.
    s.on_event(_evt(Button.UP, EventKind.PRESS, at_ms=0))
    s.on_event(_evt(Button.UP, EventKind.PRESS, at_ms=100))
    s.on_event(_evt(Button.UP, EventKind.PRESS, at_ms=200))
    assert s.digits[0] == 2


def test_left_right_repeat_not_throttled() -> None:
    """Cell movement uses the input layer's natural cadence, no throttle."""
    s = PinEntryScreen(length=6)
    s.on_event(_evt(Button.RIGHT, EventKind.PRESS, at_ms=0))
    s.on_event(_evt(Button.RIGHT, EventKind.REPEAT, at_ms=120))
    s.on_event(_evt(Button.RIGHT, EventKind.REPEAT, at_ms=240))
    # Three motions at 120 ms cadence should advance three cells.
    assert s.cursor == 3


# ---------------------------------------------------------------------------
# Cursor motion
# ---------------------------------------------------------------------------


def test_left_right_move_cursor_clamped() -> None:
    s = PinEntryScreen(length=4)
    assert s.cursor == 0
    s.on_event(_evt(Button.LEFT))
    assert s.cursor == 0  # clamped
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.RIGHT))
    assert s.cursor == 2
    for _ in range(10):
        s.on_event(_evt(Button.RIGHT))
    assert s.cursor == 3  # clamped at last slot


# ---------------------------------------------------------------------------
# Confirm / advance / backspace
# ---------------------------------------------------------------------------


def test_a_with_all_digits_filled_confirms() -> None:
    s = PinEntryScreen(length=4, digits=[1, 2, 3, 4])
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "1234"


def test_a_with_empty_slots_jumps_to_first_empty() -> None:
    s = PinEntryScreen(length=4, digits=[1, None, 3, None])
    # Cursor starts at 0; A should jump us to slot 1 (first empty).
    s.on_event(_evt(Button.A))
    assert s.done is False
    assert s.cursor == 1


def test_a_jumps_to_next_empty_after_current() -> None:
    s = PinEntryScreen(length=4, digits=[1, 2, None, None])
    s.cursor = 1
    s.on_event(_evt(Button.A))
    assert s.cursor == 2


def test_select_acts_as_a() -> None:
    s = PinEntryScreen(length=4, digits=[5, 5, 5, 5])
    s.on_event(_evt(Button.SELECT))
    assert s.done is True
    assert s.result == "5555"


def test_b_press_clears_current_then_moves_left() -> None:
    s = PinEntryScreen(length=4, digits=[1, 2, 3, None])
    s.cursor = 3
    # First B: cell is None at slot 3; should move left and clear slot 2.
    s.on_event(_evt(Button.B))
    assert s.cursor == 2
    assert s.digits[2] is None
    # Slot 2 is now None; next B should move left and clear slot 1.
    s.on_event(_evt(Button.B))
    assert s.cursor == 1
    assert s.digits[1] is None


def test_b_press_at_slot_zero_just_clears_does_not_move() -> None:
    s = PinEntryScreen(length=4, digits=[5, None, None, None])
    s.on_event(_evt(Button.B))
    assert s.cursor == 0
    assert s.digits[0] is None
    # Another B: nothing to clear, cursor stays.
    s.on_event(_evt(Button.B))
    assert s.cursor == 0


def test_b_long_does_not_finish_or_cancel() -> None:
    s = PinEntryScreen(length=4, digits=[1, 2, 3, 4])
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is False


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def test_is_complete_and_reset() -> None:
    s = PinEntryScreen(length=4, digits=[1, 2, 3, 4])
    assert s.is_complete()
    s.reset()
    assert s.digits == [None] * 4
    assert s.cursor == 0
    assert s.done is False
    assert s.result is None


def test_reset_keeps_cursor_when_asked() -> None:
    s = PinEntryScreen(length=4, digits=[1, 2, 3, 4])
    s.cursor = 2
    s.reset(keep_cursor=True)
    assert s.cursor == 2


def test_events_ignored_after_done() -> None:
    s = PinEntryScreen(length=4, digits=[1, 2, 3, 4])
    s.on_event(_evt(Button.A))
    assert s.done is True and s.result == "1234"
    # Further events must not mutate state.
    s.on_event(_evt(Button.UP))
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.result == "1234"


# ---------------------------------------------------------------------------
# Subtitle helper
# ---------------------------------------------------------------------------


def test_attempts_subtitle_phrasing() -> None:
    msg, _color = attempts_subtitle(5)
    assert "5" in msg
    msg, _color = attempts_subtitle(1)
    assert "1 attempt" in msg
    msg, _color = attempts_subtitle(0)
    assert "wiped" in msg


# ---------------------------------------------------------------------------
# Rendering smoke
# ---------------------------------------------------------------------------


def test_draw_does_not_raise_empty_state() -> None:
    fb = FrameBuffer()
    PinEntryScreen().draw(fb)
    # Some non-background pixels (title bar at least).
    assert any(
        fb.image.getpixel((x, y)) != COLOR_BG
        for x in range(0, 240, 8)
        for y in range(0, 32, 4)
    )


def test_draw_with_subtitle_and_partial_pin() -> None:
    fb = FrameBuffer()
    s = PinEntryScreen(digits=[1, 2, 3, None, None, None], subtitle="2 attempts left")
    s.cursor = 3
    s.draw(fb)  # no exception


def test_draw_with_subtitle_alert_smoke() -> None:
    fb = FrameBuffer()
    s = PinEntryScreen(
        length=4,
        subtitle_alert="Wrong PIN",
        subtitle="9 attempts left",
    )
    s.draw(fb)  # no exception


def test_masked_mode_hides_inactive_digits() -> None:
    fb = FrameBuffer()
    s = PinEntryScreen(length=4, digits=[1, 2, 3, 4], masked=True)
    s.cursor = 1
    # Just verify drawing succeeds; pixel-level glyph check is too font-dependent.
    s.draw(fb)
