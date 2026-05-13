"""Bonnet settings screen interaction tests."""

from __future__ import annotations

import pytest

from piwallet.core.settings import BonnetSettings
from piwallet.ui.display import (
    MAX_BRIGHTNESS,
    MIN_BRIGHTNESS,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.settings_screen import (
    BRIGHTNESS_STEP,
    SettingsScreen,
)


def _evt(b: Button, k: EventKind = EventKind.PRESS) -> Event:
    return Event(button=b, kind=k, at_ms=0)


def _make_screen(
    *,
    brightness: float = MAX_BRIGHTNESS,
    apply_recorder: list[float] | None = None,
) -> SettingsScreen:
    apply_brightness = (
        apply_recorder.append if apply_recorder is not None else None
    )
    return SettingsScreen(
        settings=BonnetSettings(brightness=brightness),
        apply_brightness=apply_brightness,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_starts_on_brightness_row_with_persisted_value() -> None:
    s = _make_screen(brightness=0.7)
    assert s.cursor == 0
    assert s.draft.brightness == pytest.approx(0.7)
    assert s.result is None


def test_requires_at_least_one_row() -> None:
    with pytest.raises(ValueError):
        SettingsScreen(settings=BonnetSettings(), rows=())


# ---------------------------------------------------------------------------
# Adjustment + live preview
# ---------------------------------------------------------------------------


def test_right_increases_brightness_by_step_and_emits_preview() -> None:
    rec: list[float] = []
    s = _make_screen(brightness=0.5, apply_recorder=rec)

    s.on_event(_evt(Button.RIGHT))

    assert s.draft.brightness == pytest.approx(0.5 + BRIGHTNESS_STEP)
    assert rec == [pytest.approx(0.5 + BRIGHTNESS_STEP)]


def test_left_decreases_brightness_by_step() -> None:
    rec: list[float] = []
    s = _make_screen(brightness=0.5, apply_recorder=rec)

    s.on_event(_evt(Button.LEFT))

    assert s.draft.brightness == pytest.approx(0.5 - BRIGHTNESS_STEP)
    assert rec == [pytest.approx(0.5 - BRIGHTNESS_STEP)]


def test_repeat_events_continue_adjusting() -> None:
    rec: list[float] = []
    s = _make_screen(brightness=0.5, apply_recorder=rec)

    s.on_event(_evt(Button.RIGHT, EventKind.PRESS))
    s.on_event(_evt(Button.RIGHT, EventKind.REPEAT))
    s.on_event(_evt(Button.RIGHT, EventKind.REPEAT))

    assert s.draft.brightness == pytest.approx(0.5 + 3 * BRIGHTNESS_STEP)
    assert len(rec) == 3


def test_right_clamps_at_maximum() -> None:
    rec: list[float] = []
    s = _make_screen(brightness=MAX_BRIGHTNESS, apply_recorder=rec)

    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.RIGHT))

    assert s.draft.brightness == MAX_BRIGHTNESS
    # No preview events fired because the value never changed.
    assert rec == []


def test_left_clamps_at_minimum() -> None:
    rec: list[float] = []
    s = _make_screen(brightness=MIN_BRIGHTNESS, apply_recorder=rec)

    s.on_event(_evt(Button.LEFT))

    assert s.draft.brightness == MIN_BRIGHTNESS
    assert rec == []


# ---------------------------------------------------------------------------
# Save / cancel / exit semantics
# ---------------------------------------------------------------------------


def test_a_press_saves_draft_and_marks_done() -> None:
    rec: list[float] = []
    s = _make_screen(brightness=0.5, apply_recorder=rec)
    s.on_event(_evt(Button.RIGHT))

    s.on_event(_evt(Button.A))

    assert s.done
    assert s.result == "saved"
    assert s.settings.brightness == pytest.approx(0.5 + BRIGHTNESS_STEP)


def test_select_press_also_saves() -> None:
    s = _make_screen(brightness=0.5)
    s.on_event(_evt(Button.SELECT))
    assert s.result == "saved"


def test_b_press_cancels_and_restores_preview() -> None:
    rec: list[float] = []
    s = _make_screen(brightness=0.5, apply_recorder=rec)
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.RIGHT))

    s.on_event(_evt(Button.B))

    assert s.done
    assert s.result == "back"
    # The persisted settings on the screen are unchanged.
    assert s.settings.brightness == pytest.approx(0.5)
    # The last preview emission must restore the original.
    assert rec[-1] == pytest.approx(0.5)


def test_b_long_returns_exit() -> None:
    s = _make_screen(brightness=0.5)
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done
    assert s.result == "exit"


def test_b_long_restores_preview_before_exit() -> None:
    rec: list[float] = []
    s = _make_screen(brightness=0.5, apply_recorder=rec)
    s.on_event(_evt(Button.RIGHT))

    s.on_event(_evt(Button.B, EventKind.LONG))

    assert rec[-1] == pytest.approx(0.5)


def test_no_events_after_done() -> None:
    s = _make_screen(brightness=0.5)
    s.on_event(_evt(Button.A))
    assert s.done
    s.on_event(_evt(Button.RIGHT))
    # Saving locked the value in; further events do nothing.
    assert s.draft.brightness == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Render smoke tests (we draw without raising; pixel checks are out of scope)
# ---------------------------------------------------------------------------


def test_draw_runs_without_error() -> None:
    fb = FrameBuffer()
    s = _make_screen(brightness=0.5)
    s.draw(fb)


def test_draw_at_minimum_brightness() -> None:
    fb = FrameBuffer()
    s = _make_screen(brightness=MIN_BRIGHTNESS)
    s.draw(fb)


def test_draw_at_maximum_brightness() -> None:
    fb = FrameBuffer()
    s = _make_screen(brightness=MAX_BRIGHTNESS)
    s.draw(fb)
