"""QR background luminance helpers."""

from __future__ import annotations

from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.qr_brightness import (
 DEFAULT_QR_BACKGROUND,
 decrease_qr_background,
 increase_qr_background,
 qr_background_rgb,
 try_qr_brightness_event,
)

def test_default_qr_background_level() -> None:
 assert DEFAULT_QR_BACKGROUND == 62
 assert qr_background_rgb(DEFAULT_QR_BACKGROUND) == (62, 62, 62)

def test_increase_and_decrease_step_by_31() -> None:
 assert increase_qr_background(62) == 93
 assert decrease_qr_background(62) == 31
 assert increase_qr_background(255) == 255
 assert decrease_qr_background(31) == 31

def test_try_qr_brightness_event_calls_on_changed() -> None:
 seen: list[int] = []

 new = try_qr_brightness_event(
 Event(button=Button.UP, kind=EventKind.PRESS, at_ms=0),
 62,
 on_changed=seen.append,
 )
 assert new == 93
 assert seen == [93]

def test_try_qr_brightness_event_ignores_unrelated_buttons() -> None:
 assert (
 try_qr_brightness_event(
 Event(button=Button.A, kind=EventKind.PRESS, at_ms=0),
 62,
 )
 is None
 )
