"""DiceEntropyScreen unit tests.

Focused on the cancel/back contract: both short tap and long hold of
B abort the dice-roll capture and yield ``result is None`` so the
caller cancels the create-wallet flow.
"""

from __future__ import annotations

from piwallet.bonnet.entropy_screens import DiceEntropyScreen
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


def _evt(b: Button, k: EventKind = EventKind.PRESS) -> Event:
    return Event(button=b, kind=k, at_ms=0)


def test_dice_short_b_press_cancels() -> None:
    """Short tap of B aborts dice capture; matches every other 'back' surface."""
    s = DiceEntropyScreen()
    s.on_event(_evt(Button.B, EventKind.PRESS))
    assert s.done and s.result is None


def test_dice_long_b_press_cancels() -> None:
    s = DiceEntropyScreen()
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done and s.result is None


def test_dice_face_up_down_cycles_in_range() -> None:
    s = DiceEntropyScreen()
    assert s.current_face == 3
    s.on_event(_evt(Button.UP))
    assert s.current_face == 4
    for _ in range(3):
        s.on_event(_evt(Button.UP))
    assert s.current_face == 1
    s.on_event(_evt(Button.DOWN))
    assert s.current_face == 6


def test_dice_a_press_records_roll() -> None:
    s = DiceEntropyScreen()
    s.current_face = 5
    s.on_event(_evt(Button.A))
    assert s.rolls == [5]
    assert not s.done


def test_dice_left_undoes_last_roll() -> None:
    s = DiceEntropyScreen()
    s.current_face = 2
    s.on_event(_evt(Button.A))
    s.on_event(_evt(Button.LEFT))
    assert s.rolls == []


def test_dice_draw_smoke() -> None:
    fb = FrameBuffer()
    DiceEntropyScreen().draw(fb)
