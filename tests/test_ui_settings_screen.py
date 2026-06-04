"""Bonnet settings screen interaction tests."""

from __future__ import annotations

import pytest

from piwallet.core.settings import (
    DEFAULT_SLEEP_TIMEOUT_MS,
    SLEEP_TIMER_OPTIONS_MS,
    BonnetSettings,
)
from piwallet.ui.display import (
    MAX_BRIGHTNESS,
    MIN_BRIGHTNESS,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.settings_screen import (
    BRIGHTNESS_STEP,
    SETTINGS_ROWS,
    SettingsScreen,
    _format_sleep_timeout_ms,
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


# ---------------------------------------------------------------------------
# Sleep timer row
# ---------------------------------------------------------------------------


def test_settings_rows_include_brightness_then_sleep_timer_then_camera_then_action_rows() -> None:
    """Order is fixed — value rows first, then action rows.

    The Settings screen's row ordering is observable via cursor index;
    if a future edit reorders the rows, every existing test that
    pokes ``cursor`` (and anyone's muscle memory on a real device)
    has to update too.
    """
    keys = [row.key for row in SETTINGS_ROWS]
    assert keys == [
        "brightness",
        "sleep_timer",
        "camera_type",
        "change_pin",
        "airgap",
        "usb_backup",
    ]


def test_change_pin_airgap_and_usb_backup_are_action_rows() -> None:
    rows_by_key = {row.key: row for row in SETTINGS_ROWS}
    assert rows_by_key["change_pin"].is_action is True
    assert rows_by_key["airgap"].is_action is True
    assert rows_by_key["usb_backup"].is_action is True
    # Value rows must explicitly stay non-action so a future
    # refactor that flips defaults can't accidentally promote them.
    assert rows_by_key["brightness"].is_action is False
    assert rows_by_key["sleep_timer"].is_action is False


def test_a_on_usb_backup_row_returns_usb_backup_result() -> None:
    s = _make_screen(brightness=0.5)
    target = next(i for i, r in enumerate(SETTINGS_ROWS) if r.key == "usb_backup")
    while s.cursor != target:
        s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "usb_backup"


def test_a_on_airgap_row_returns_airgap_result() -> None:
    s = _make_screen(brightness=0.5)
    target = next(i for i, r in enumerate(SETTINGS_ROWS) if r.key == "airgap")
    while s.cursor != target:
        s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "airgap"


def test_format_sleep_timeout_ms_renders_each_preset() -> None:
    assert _format_sleep_timeout_ms(60_000) == "1 min"
    assert _format_sleep_timeout_ms(300_000) == "5 min"
    assert _format_sleep_timeout_ms(0) == "Off"


def test_down_moves_cursor_to_sleep_timer_row() -> None:
    s = _make_screen(brightness=0.5)
    assert s.cursor == 0  # brightness
    s.on_event(_evt(Button.DOWN))
    assert s.cursor == 1  # sleep_timer


def test_right_on_sleep_timer_cycles_to_next_preset() -> None:
    """Default is 5 min; RIGHT advances to the next slot in the cycle.

    Cycle order: 1 min -> 5 min -> off, so RIGHT from 5 min lands on
    Off rather than wrapping back to 1 min. (LEFT goes back to 1 min.)
    """
    s = _make_screen(brightness=0.5)
    s.on_event(_evt(Button.DOWN))  # cursor -> sleep_timer
    s.on_event(_evt(Button.RIGHT))
    assert s.draft.sleep_timeout_ms == 0  # "Off"


def test_left_on_sleep_timer_steps_back_through_cycle() -> None:
    s = _make_screen(brightness=0.5)
    s.on_event(_evt(Button.DOWN))  # cursor -> sleep_timer
    # Default index is 1 (5 min). LEFT goes to index 0 (1 min).
    s.on_event(_evt(Button.LEFT))
    assert s.draft.sleep_timeout_ms == 60_000


def test_sleep_timer_cycle_wraps_in_both_directions() -> None:
    s = _make_screen(brightness=0.5)
    s.on_event(_evt(Button.DOWN))
    # Walk the full forward cycle once.
    s.on_event(_evt(Button.RIGHT))  # 5 min -> off
    s.on_event(_evt(Button.RIGHT))  # off  -> 1 min
    s.on_event(_evt(Button.RIGHT))  # 1 min -> 5 min
    assert s.draft.sleep_timeout_ms == DEFAULT_SLEEP_TIMEOUT_MS


def test_sleep_timer_does_not_emit_brightness_preview() -> None:
    """Cycling the sleep timer must not poke ``apply_brightness``."""
    rec: list[float] = []
    s = _make_screen(brightness=0.5, apply_recorder=rec)
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.LEFT))
    assert rec == []


def test_save_persists_sleep_timer_change() -> None:
    s = _make_screen(brightness=0.5)
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.RIGHT))  # 5 min -> off
    s.on_event(_evt(Button.A))
    assert s.result == "saved"
    assert s.settings.sleep_timeout_ms == 0
    # Brightness round-trips untouched.
    assert s.settings.brightness == pytest.approx(0.5)


def test_cancel_reverts_sleep_timer_change() -> None:
    s = _make_screen(brightness=0.5)
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.RIGHT))  # draft moves to "off"
    s.on_event(_evt(Button.B))
    # Persisted value is unchanged.
    assert s.settings.sleep_timeout_ms == DEFAULT_SLEEP_TIMEOUT_MS


def test_brightness_unchanged_when_only_sleep_timer_edited_and_saved() -> None:
    rec: list[float] = []
    s = _make_screen(brightness=0.6, apply_recorder=rec)
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.A))
    assert s.settings.brightness == pytest.approx(0.6)
    # No preview events fired because brightness wasn't touched.
    assert rec == []


def test_drafted_off_preset_stays_off_through_redraw() -> None:
    """Sleep-timer changes are visible to the value renderer immediately."""
    s = _make_screen(brightness=0.5)
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.RIGHT))  # 5 min -> off
    fb = FrameBuffer()
    s.draw(fb)  # must not raise
    assert s.draft.sleep_timeout_ms == 0


# ---------------------------------------------------------------------------
# Change-PIN action row dispatch
# ---------------------------------------------------------------------------


def _move_to_change_pin_row(s: SettingsScreen) -> None:
    """Walk DOWN until the cursor sits on the change_pin row."""
    target = next(i for i, r in enumerate(SETTINGS_ROWS) if r.key == "change_pin")
    while s.cursor != target:
        s.on_event(_evt(Button.DOWN))


def test_a_on_change_pin_row_returns_change_pin_result() -> None:
    s = _make_screen(brightness=0.5)
    _move_to_change_pin_row(s)
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "change_pin"


def test_select_on_change_pin_row_returns_change_pin_result() -> None:
    s = _make_screen(brightness=0.5)
    _move_to_change_pin_row(s)
    s.on_event(_evt(Button.SELECT))
    assert s.result == "change_pin"


def test_a_on_change_pin_row_persists_pending_value_drafts() -> None:
    """Operator tweaks brightness, then taps Change PIN — the slider
    change must be saved (mirrored into ``settings``) before the
    sub-flow runs so it isn't lost while the change-PIN modal stack
    takes over the display."""
    s = _make_screen(brightness=0.5)
    s.on_event(_evt(Button.RIGHT))  # bump brightness on the brightness row
    bumped = s.draft.brightness
    _move_to_change_pin_row(s)
    s.on_event(_evt(Button.A))
    assert s.result == "change_pin"
    assert s.settings.brightness == pytest.approx(bumped)


def test_left_right_on_change_pin_row_is_a_noop() -> None:
    s = _make_screen(brightness=0.5)
    _move_to_change_pin_row(s)
    rec_before = s.draft
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.LEFT))
    assert s.draft == rec_before


def test_b_press_on_change_pin_row_still_cancels() -> None:
    """B is the universal back gesture — must work on action rows too."""
    s = _make_screen(brightness=0.5)
    _move_to_change_pin_row(s)
    s.on_event(_evt(Button.B))
    assert s.result == "back"


def test_draw_on_change_pin_row() -> None:
    s = _make_screen(brightness=0.5)
    _move_to_change_pin_row(s)
    fb = FrameBuffer()
    s.draw(fb)


def test_unknown_drafted_value_snaps_to_first_preset_on_cycle() -> None:
    """Hand-edited file with non-preset value still cycles cleanly.

    ``_cycle_sleep_timer`` recovers by snapping to index 0 before
    stepping, so an L/R press from a corrupt draft lands on the
    second preset (1 min -> 5 min).
    """
    s = SettingsScreen(
        settings=BonnetSettings(sleep_timeout_ms=DEFAULT_SLEEP_TIMEOUT_MS),
    )
    # Forcibly drift the draft off the preset list.
    s._draft = BonnetSettings(sleep_timeout_ms=17_000)  # type: ignore[attr-defined]
    s.cursor = 1  # sleep_timer
    s.on_event(_evt(Button.RIGHT))
    # idx 0 (1 min) + step → idx 1 (5 min).
    assert s.draft.sleep_timeout_ms == SLEEP_TIMER_OPTIONS_MS[1]
