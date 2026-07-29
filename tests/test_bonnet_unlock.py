"""UnlockScreen interaction tests."""

from __future__ import annotations

from piwallet.bonnet.unlock import UnlockOutcome, UnlockScreen
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


def _evt(b: Button, k: EventKind = EventKind.PRESS, at_ms: int = 0) -> Event:
    return Event(button=b, kind=k, at_ms=at_ms)


def _press_a(screen: UnlockScreen) -> None:
    screen.on_event(_evt(Button.A))


def _type_pin(screen: UnlockScreen, digits: str) -> None:
    """Fill the embedded PIN entry with `digits` left-to-right."""
    pe = screen.pin_entry
    pe.digits = list(digits)
    pe.length = len(digits)
    pe.cursor = len(digits) - 1


def test_unlock_success_returns_pin() -> None:
    captured: list[str] = []

    def verify(pin: str) -> tuple[str, int | None]:
        captured.append(pin)
        return ("ok", None)

    screen = UnlockScreen(verify=verify, length=6, attempts_remaining=10)
    _type_pin(screen, "123456")
    _press_a(screen)
    assert captured == ["123456"]
    assert screen.done is True
    assert isinstance(screen.result, UnlockOutcome)
    assert screen.result.kind == "ok"
    assert screen.result.pin == "123456"


def test_unlock_wrong_pin_decrements_attempts_and_re_prompts() -> None:
    attempts_seen: list[str] = []

    def verify(pin: str) -> tuple[str, int | None]:
        attempts_seen.append(pin)
        if pin == "111111":
            return ("ok", None)
        return ("wrong", 9)

    screen = UnlockScreen(verify=verify, length=6, attempts_remaining=10)
    _type_pin(screen, "999999")
    _press_a(screen)
    # Immediate fresh PIN prompt; attempts tracked on subtitle + alert.
    assert screen.done is False
    assert screen.attempts_remaining == 9
    assert screen.pin_entry.digits == [None] * 6
    assert screen.pin_entry.subtitle_alert == "Wrong PIN"
    assert "9 attempts" in screen.pin_entry.subtitle

    # Try the correct PIN.
    _type_pin(screen, "111111")
    _press_a(screen)
    assert screen.done is True
    assert screen.result is not None and screen.result.kind == "ok"
    assert screen.result.pin == "111111"
    assert attempts_seen == ["999999", "111111"]


def test_unlock_wiped_after_last_attempt_failure() -> None:
    def verify(pin: str) -> tuple[str, int | None]:
        return ("wiped", None)

    screen = UnlockScreen(verify=verify, length=6, attempts_remaining=1)
    _type_pin(screen, "000000")
    _press_a(screen)
    assert screen.done is True
    assert screen.result is not None
    assert screen.result.kind == "wiped"
    assert screen.result.pin is None


def test_unlock_zero_attempts_remaining_after_wrong_pin() -> None:
    # Verify reports 0 attempts remaining; UnlockScreen should escalate
    # to "wiped" rather than re-prompting.
    def verify(pin: str) -> tuple[str, int | None]:
        return ("wrong", 0)

    screen = UnlockScreen(verify=verify, length=6, attempts_remaining=1)
    _type_pin(screen, "000000")
    _press_a(screen)
    assert screen.done is True
    assert screen.result is not None and screen.result.kind == "wiped"


def test_long_b_during_unlock_pin_entry_does_not_exit() -> None:
    def verify(pin: str) -> tuple[str, int | None]:
        return ("ok", None)

    screen = UnlockScreen(verify=verify, length=6, attempts_remaining=10)
    screen.on_event(_evt(Button.B, EventKind.LONG))
    assert screen.done is False


def test_unlock_drawable() -> None:
    def verify(pin: str) -> tuple[str, int | None]:
        return ("ok", None)

    fb = FrameBuffer()
    screen = UnlockScreen(verify=verify, length=6, attempts_remaining=2)
    screen.draw(fb)  # no exception


def test_unlock_select_toggles_case_without_confirming() -> None:
    """Joystick center toggles case; it must not submit a partial PIN."""
    screen = UnlockScreen(
        verify=lambda pin: ("ok", None),
        length=6,
        attempts_remaining=10,
    )
    _type_pin(screen, "123")  # incomplete — but seeding sets length 3
    # Restore to incomplete 6-slot entry for this case check.
    screen.pin_entry.digits = ["1", "2", "3", None, None, None]
    screen.pin_entry.length = 6
    screen.pin_entry.cursor = 0
    screen.on_event(_evt(Button.SELECT, EventKind.PRESS))
    assert screen.done is False
    assert screen.pin_entry.result is None
    assert screen.pin_entry.upper is True
