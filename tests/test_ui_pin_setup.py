"""Tests for the double-confirm PIN setup composite (`PinSetupScreen`)."""

from __future__ import annotations

from piwallet.ui.display import COLOR_BG, FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.pin_setup import PinSetupScreen


def _evt(button: Button, kind: EventKind = EventKind.PRESS, at_ms: int = 0) -> Event:
    return Event(button=button, kind=kind, at_ms=at_ms)


def _type_pin(screen: PinSetupScreen, digits: str) -> None:
    """Drive the inner PinEntryScreen by directly seeding its digit slots.

    Bypasses the cycling UI so the test stays focused on the
    *composite* state machine instead of re-testing PinEntryScreen's
    digit-cycling logic.
    """
    inner = screen.pin_entry
    inner.digits = [int(d) for d in digits]
    inner.cursor = inner.length - 1
    screen.on_event(_evt(Button.A))


def test_default_phase_is_first() -> None:
    s = PinSetupScreen()
    assert s.phase == "first"
    assert s.done is False
    assert s.result is None
    assert s._first_pin is None


def test_first_entry_advances_to_confirm_phase() -> None:
    s = PinSetupScreen()
    _type_pin(s, "112233")
    assert s.phase == "confirm"
    assert s.done is False
    assert s._first_pin == "112233"
    # The pin_entry instance must have been swapped, not reused —
    # both for a fresh title and for a fresh REPEAT throttle.
    assert s.pin_entry.title == s.confirm_prompt
    assert s.pin_entry.digits == [None] * s.length


def test_matching_confirm_completes_with_pin() -> None:
    s = PinSetupScreen()
    _type_pin(s, "112233")
    _type_pin(s, "112233")
    assert s.done is True
    assert s.result == "112233"


def test_mismatched_confirm_resets_to_first_phase_with_alert() -> None:
    s = PinSetupScreen()
    _type_pin(s, "112233")
    _type_pin(s, "112244")
    assert s.done is False
    assert s.phase == "first"
    assert s._first_pin is None
    assert s.pin_entry.title == s.prompt
    assert s.pin_entry.subtitle_alert == "PINs did not match"


def test_recovery_after_mismatch_succeeds() -> None:
    s = PinSetupScreen()
    _type_pin(s, "112233")
    _type_pin(s, "112244")  # mismatch
    _type_pin(s, "777777")  # new first attempt
    _type_pin(s, "777777")  # matching confirm
    assert s.done is True
    assert s.result == "777777"


def test_default_is_not_cancellable() -> None:
    s = PinSetupScreen()
    s.on_event(_evt(Button.B, EventKind.LONG))
    # Long-B forwards to the inner PinEntryScreen which ignores it.
    assert s.done is False
    assert s.result is None


def test_cancellable_long_b_aborts_with_none() -> None:
    s = PinSetupScreen(cancellable=True)
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is True
    assert s.result is None


def test_cancellable_short_b_still_falls_through_to_backspace() -> None:
    """Short-B is not the cancel gesture — it still backspaces."""
    s = PinSetupScreen(cancellable=True)
    s.on_event(_evt(Button.UP))  # inner cell becomes 0
    assert s.pin_entry.digits[0] == 0
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.pin_entry.digits[0] is None
    assert s.done is False


def test_custom_length_threads_through() -> None:
    s = PinSetupScreen(length=8)
    assert s.pin_entry.length == 8
    _type_pin(s, "11223344")
    _type_pin(s, "11223344")
    assert s.result == "11223344"


def test_done_screen_ignores_subsequent_events() -> None:
    s = PinSetupScreen()
    _type_pin(s, "112233")
    _type_pin(s, "112233")
    snapshot = (s.done, s.result, s.phase)
    s.on_event(_evt(Button.UP))
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert (s.done, s.result, s.phase) == snapshot


def test_draw_smoke() -> None:
    s = PinSetupScreen()
    fb = FrameBuffer(240, 240)
    fb.clear(COLOR_BG)
    s.draw(fb)
    # Advance to confirm phase and re-draw.
    _type_pin(s, "112233")
    s.draw(fb)
    # Trigger mismatch alert and re-draw.
    _type_pin(s, "112244")
    s.draw(fb)
