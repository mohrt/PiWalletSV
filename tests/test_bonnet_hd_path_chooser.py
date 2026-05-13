"""HD path chooser screens + run_hd_path_chooser driver."""

from __future__ import annotations

from piwallet.bonnet.hd_path_chooser import (
    CustomHdPathScreen,
    HdPathPresetChooser,
    run_hd_path_chooser,
)
from piwallet.core import derivation as deriv
from piwallet.ui.display import FrameBuffer, HeadlessDisplay
from piwallet.ui.input import (
    Button,
    Event,
    EventKind,
    FakeInputBackend,
    InputManager,
)


def _evt(b: Button, k: EventKind = EventKind.PRESS) -> Event:
    return Event(button=b, kind=k, at_ms=0)


# ---------------------------------------------------------------------------
# HdPathPresetChooser
# ---------------------------------------------------------------------------


def test_preset_chooser_starts_with_bsv_default_highlighted() -> None:
    s = HdPathPresetChooser()
    assert s._list.cursor == 0
    item = s._list.items[0]
    assert item.value == "bsv-default"
    assert deriv.account_path() in item.label


def test_preset_chooser_a_press_returns_bsv_default() -> None:
    s = HdPathPresetChooser()
    s.on_event(_evt(Button.A))
    assert s.done
    assert s.result == "bsv-default"


def test_preset_chooser_select_advanced() -> None:
    s = HdPathPresetChooser()
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.A))
    assert s.result == "advanced"


def test_preset_chooser_long_b_returns_back() -> None:
    s = HdPathPresetChooser()
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done
    assert s.result == "back"


def test_preset_chooser_draw_smoke() -> None:
    fb = FrameBuffer()
    HdPathPresetChooser().draw(fb)


# ---------------------------------------------------------------------------
# CustomHdPathScreen
# ---------------------------------------------------------------------------


def test_custom_defaults_to_bsv() -> None:
    s = CustomHdPathScreen()
    assert s.coin_type == deriv.BSV_COIN_TYPE
    assert s.account_index == deriv.DEFAULT_ACCOUNT_INDEX
    assert s.path == deriv.account_path()


def test_custom_left_right_adjust_coin_type() -> None:
    s = CustomHdPathScreen()
    assert s.cursor == 0
    s.on_event(_evt(Button.RIGHT))
    assert s.coin_type == deriv.BSV_COIN_TYPE + 1
    s.on_event(_evt(Button.LEFT))
    s.on_event(_evt(Button.LEFT))
    assert s.coin_type == deriv.BSV_COIN_TYPE - 1


def test_custom_down_then_left_right_adjusts_account() -> None:
    s = CustomHdPathScreen()
    s.on_event(_evt(Button.DOWN))
    assert s.cursor == 1
    s.on_event(_evt(Button.RIGHT))
    s.on_event(_evt(Button.RIGHT))
    assert s.account_index == 2
    s.on_event(_evt(Button.LEFT))
    assert s.account_index == 1


def test_custom_clamps_at_zero() -> None:
    s = CustomHdPathScreen(coin_type=0, account_index=0)
    s.on_event(_evt(Button.LEFT))
    assert s.coin_type == 0
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.LEFT))
    assert s.account_index == 0


def test_custom_clamps_at_max() -> None:
    s = CustomHdPathScreen(coin_type=999)
    s.on_event(_evt(Button.RIGHT))
    assert s.coin_type == 999


def test_custom_repeat_events_continue_adjusting() -> None:
    s = CustomHdPathScreen(coin_type=100)
    s.on_event(_evt(Button.RIGHT, EventKind.PRESS))
    s.on_event(_evt(Button.RIGHT, EventKind.REPEAT))
    s.on_event(_evt(Button.RIGHT, EventKind.REPEAT))
    assert s.coin_type == 103


def test_custom_a_confirms() -> None:
    s = CustomHdPathScreen(coin_type=0, account_index=2)
    s.on_event(_evt(Button.A))
    assert s.done
    assert s.result == "confirmed"
    assert s.coin_type == 0
    assert s.account_index == 2


def test_custom_select_confirms() -> None:
    s = CustomHdPathScreen()
    s.on_event(_evt(Button.SELECT))
    assert s.result == "confirmed"


def test_custom_b_press_returns_back() -> None:
    s = CustomHdPathScreen()
    s.on_event(_evt(Button.B))
    assert s.result == "back"


def test_custom_b_long_cancels() -> None:
    s = CustomHdPathScreen()
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.result == "cancel"


def test_custom_path_property_reflects_current_values() -> None:
    s = CustomHdPathScreen(coin_type=0, account_index=5)
    assert s.path == "m/44'/0'/5'"


def test_custom_draw_smoke() -> None:
    fb = FrameBuffer()
    CustomHdPathScreen().draw(fb)


def test_custom_draw_with_account_field_focused() -> None:
    fb = FrameBuffer()
    s = CustomHdPathScreen(coin_type=0, account_index=42)
    s.on_event(_evt(Button.DOWN))
    s.draw(fb)


# ---------------------------------------------------------------------------
# run_hd_path_chooser driver (with stubbed run_screen)
# ---------------------------------------------------------------------------


def _make_io() -> tuple[HeadlessDisplay, InputManager]:
    return HeadlessDisplay(), InputManager(FakeInputBackend())


def test_driver_returns_bsv_when_preset_accepted() -> None:
    display, mgr = _make_io()

    def fake(_d, _m, screen, **_):
        if isinstance(screen, HdPathPresetChooser):
            screen.done = True
            screen.result = "bsv-default"
            return screen.result
        raise AssertionError("custom editor should not run")

    out = run_hd_path_chooser(display, mgr, run_screen_fn=fake)
    assert out == (deriv.BSV_COIN_TYPE, deriv.DEFAULT_ACCOUNT_INDEX)


def test_driver_returns_none_when_preset_cancelled() -> None:
    display, mgr = _make_io()

    def fake(_d, _m, screen, **_):
        if isinstance(screen, HdPathPresetChooser):
            screen.done = True
            screen.result = "back"
            return None
        raise AssertionError("custom editor should not run")

    assert run_hd_path_chooser(display, mgr, run_screen_fn=fake) is None


def test_driver_returns_custom_values_after_advanced_then_confirm() -> None:
    display, mgr = _make_io()
    state = {"phase": "preset"}

    def fake(_d, _m, screen, **_):
        if isinstance(screen, HdPathPresetChooser):
            assert state["phase"] == "preset"
            state["phase"] = "custom"
            screen.done = True
            screen.result = "advanced"
            return screen.result
        if isinstance(screen, CustomHdPathScreen):
            assert state["phase"] == "custom"
            screen.coin_type = 1
            screen.account_index = 7
            screen.done = True
            screen.result = "confirmed"
            return screen.result
        raise AssertionError(f"unexpected {type(screen)!r}")

    assert run_hd_path_chooser(display, mgr, run_screen_fn=fake) == (1, 7)


def test_driver_back_from_editor_re_shows_preset_chooser() -> None:
    display, mgr = _make_io()
    runs: list[str] = []

    def fake(_d, _m, screen, **_):
        if isinstance(screen, HdPathPresetChooser):
            runs.append("preset")
            screen.done = True
            # First time: pick advanced. Second time: accept BSV.
            screen.result = "advanced" if len(runs) == 1 else "bsv-default"
            return screen.result
        if isinstance(screen, CustomHdPathScreen):
            runs.append("custom")
            screen.done = True
            screen.result = "back"
            return screen.result
        raise AssertionError

    out = run_hd_path_chooser(display, mgr, run_screen_fn=fake)
    assert out == (deriv.BSV_COIN_TYPE, deriv.DEFAULT_ACCOUNT_INDEX)
    assert runs == ["preset", "custom", "preset"]


def test_driver_cancel_from_editor_returns_none() -> None:
    display, mgr = _make_io()

    def fake(_d, _m, screen, **_):
        if isinstance(screen, HdPathPresetChooser):
            screen.done = True
            screen.result = "advanced"
            return screen.result
        if isinstance(screen, CustomHdPathScreen):
            screen.done = True
            screen.result = "cancel"
            return screen.result
        raise AssertionError

    assert run_hd_path_chooser(display, mgr, run_screen_fn=fake) is None
