"""DoubleConfirmScreen behaviour."""

from __future__ import annotations

from piwallet.ui.display import FrameBuffer
from piwallet.ui.double_confirm import DoubleConfirmScreen
from piwallet.ui.input import Button, Event, EventKind


def _press(b: Button) -> Event:
    return Event(button=b, kind=EventKind.PRESS, at_ms=0)


def test_double_confirm_accepts_two_a_presses() -> None:
    s = DoubleConfirmScreen(
        title="T",
        first_prompt="one",
        second_prompt="two",
    )
    s.on_event(_press(Button.A))
    assert not s.done and s.step == 1
    s.on_event(_press(Button.A))
    assert s.done and s.result is True


def test_double_confirm_b_on_first_cancels() -> None:
    s = DoubleConfirmScreen(title="T", first_prompt="a", second_prompt="b")
    s.on_event(_press(Button.B))
    assert s.done and s.result is False


def test_double_confirm_b_on_second_cancels() -> None:
    s = DoubleConfirmScreen(title="T", first_prompt="a", second_prompt="b")
    s.on_event(_press(Button.A))
    s.on_event(_press(Button.B))
    assert s.done and s.result is False


def test_select_same_as_a() -> None:
    s = DoubleConfirmScreen(title="T", first_prompt="a", second_prompt="b")
    s.on_event(_press(Button.SELECT))
    s.on_event(_press(Button.SELECT))
    assert s.done and s.result is True


def test_draw_smoke() -> None:
    fb = FrameBuffer()
    DoubleConfirmScreen(title="Erase?", first_prompt="sure?", second_prompt="really?").draw(fb)


def test_draw_second_step_warning_smoke() -> None:
    fb = FrameBuffer()
    s = DoubleConfirmScreen(
        title="Erase?",
        first_prompt="first",
        second_prompt="second line",
        second_step_warning=True,
        second_title="Final step",
    )
    s.step = 1
    s.draw(fb)
