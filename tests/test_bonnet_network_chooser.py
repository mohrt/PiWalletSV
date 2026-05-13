"""Network chooser screen + run_network_chooser driver."""

from __future__ import annotations

from piwallet.bonnet.network_chooser import (
    NetworkChooserScreen,
    run_network_chooser,
)
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
# NetworkChooserScreen
# ---------------------------------------------------------------------------


def test_chooser_starts_with_mainnet_highlighted() -> None:
    """The default cursor is on mainnet — operators who hit A immediately
    end up with a real-money wallet, which is what they want most of
    the time. Testnet must be a deliberate second selection."""
    s = NetworkChooserScreen()
    assert s._list.cursor == 0
    assert s._list.items[0].value == "main"
    assert s._list.items[1].value == "test"


def test_chooser_a_press_returns_main() -> None:
    s = NetworkChooserScreen()
    s.on_event(_evt(Button.A))
    assert s.done
    assert s.result == "main"
    assert s.exit_requested is False


def test_chooser_select_testnet() -> None:
    s = NetworkChooserScreen()
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.A))
    assert s.done
    assert s.result == "test"


def test_chooser_b_press_returns_none_no_exit() -> None:
    s = NetworkChooserScreen()
    s.on_event(_evt(Button.B))
    assert s.done
    assert s.result is None
    assert s.exit_requested is False


def test_chooser_b_long_requests_app_exit() -> None:
    s = NetworkChooserScreen()
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done
    assert s.result is None
    assert s.exit_requested is True


def test_chooser_select_with_select_button() -> None:
    """SELECT (joystick centre press) should also confirm the choice."""
    s = NetworkChooserScreen()
    s.on_event(_evt(Button.SELECT))
    assert s.done
    assert s.result == "main"


def test_chooser_post_done_lockout() -> None:
    s = NetworkChooserScreen()
    s.on_event(_evt(Button.A))
    assert s.result == "main"
    # Subsequent events must not flip the result.
    s.on_event(_evt(Button.DOWN))
    s.on_event(_evt(Button.A))
    assert s.result == "main"


def test_chooser_draw_smoke() -> None:
    fb = FrameBuffer()
    s = NetworkChooserScreen()
    s.draw(fb)  # must not raise
    # Sanity: at least some pixels were painted.
    assert fb.image.getbbox() is not None


# ---------------------------------------------------------------------------
# run_network_chooser driver
# ---------------------------------------------------------------------------


def _make_io() -> tuple[HeadlessDisplay, InputManager]:
    return HeadlessDisplay(), InputManager(FakeInputBackend())


def test_run_default_accepts_main() -> None:
    display, mgr = _make_io()

    def fake(_d, _m, screen, **_):
        assert isinstance(screen, NetworkChooserScreen)
        screen.done = True
        screen.result = "main"
        return screen.result

    assert run_network_chooser(display, mgr, run_screen_fn=fake) == "main"


def test_run_picks_test() -> None:
    display, mgr = _make_io()

    def fake(_d, _m, screen, **_):
        screen.done = True
        screen.result = "test"
        return screen.result

    assert run_network_chooser(display, mgr, run_screen_fn=fake) == "test"


def test_run_b_press_returns_none() -> None:
    display, mgr = _make_io()

    def fake(_d, _m, screen, **_):
        screen.done = True
        screen.result = None
        return None

    assert run_network_chooser(display, mgr, run_screen_fn=fake) is None
