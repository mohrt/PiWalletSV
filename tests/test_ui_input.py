"""InputManager debounce / repeat / long-press tests."""

from __future__ import annotations

import pytest

from piwallet.ui.input import (
    Button,
    EventKind,
    FakeInputBackend,
    InputManager,
    open_input,
)


class FakeClock:
    """Monotonic millisecond clock controlled by the test."""

    def __init__(self, start_ms: int = 0) -> None:
        self.now: int = start_ms

    def __call__(self) -> int:
        return self.now

    def tick(self, ms: int) -> None:
        self.now += ms


@pytest.fixture()
def env() -> tuple[FakeInputBackend, FakeClock, InputManager]:
    backend = FakeInputBackend()
    clock = FakeClock()
    # debounce_ms=0 by default: commit transitions on the same poll
    # they're observed. This matches the way the 30 Hz main loop sees
    # input on the real bonnet (any switch bounce has already settled
    # by the time we sample). The dedicated debounce test below opts
    # in to debounce_ms=15 to verify the noise-filter behavior.
    mgr = InputManager(
        backend,
        long_ms=700,
        repeat_initial_ms=400,
        repeat_ms=120,
        clock=clock,
    )
    return backend, clock, mgr


def test_press_fires_on_first_poll_with_default_debounce(
    env: tuple[FakeInputBackend, FakeClock, InputManager],
) -> None:
    backend, _clock, mgr = env
    backend.press(Button.A)
    events = mgr.poll()
    assert [e.kind for e in events] == [EventKind.PRESS]
    assert events[0].button == Button.A


def test_debounce_window_swallows_noise() -> None:
    """When debounce_ms > 0, brief raw bounces are filtered out."""
    backend = FakeInputBackend()
    clock = FakeClock()
    mgr = InputManager(backend, debounce_ms=15, clock=clock)

    backend.press(Button.A)
    events = mgr.poll()
    assert events == []  # too soon; debounce hasn't elapsed
    backend.release(Button.A)
    clock.tick(5)
    assert mgr.poll() == []
    backend.press(Button.A)
    clock.tick(5)
    assert mgr.poll() == []
    clock.tick(20)
    events = mgr.poll()
    assert [e.kind for e in events] == [EventKind.PRESS]
    assert events[0].button == Button.A


def test_release_emits_release_event(env: tuple[FakeInputBackend, FakeClock, InputManager]) -> None:
    backend, _clock, mgr = env
    backend.press(Button.UP)
    mgr.poll()
    backend.release(Button.UP)
    events = mgr.poll()
    assert [e.kind for e in events] == [EventKind.RELEASE]


def test_repeat_after_initial_delay_then_steady_cadence(
    env: tuple[FakeInputBackend, FakeClock, InputManager],
) -> None:
    backend, clock, mgr = env
    backend.press(Button.DOWN)
    mgr.poll()  # PRESS

    # No repeats yet — still under the initial 400 ms.
    clock.tick(300)
    assert mgr.poll() == []

    # First repeat: cross the initial 400 ms threshold.
    clock.tick(120)  # total held: 420 ms
    events = mgr.poll()
    assert any(e.kind == EventKind.REPEAT for e in events)

    # Subsequent repeats at the 120 ms cadence.
    clock.tick(120)
    events = mgr.poll()
    assert any(e.kind == EventKind.REPEAT for e in events)


def test_long_event_fires_exactly_once_per_press(
    env: tuple[FakeInputBackend, FakeClock, InputManager],
) -> None:
    backend, clock, mgr = env
    backend.press(Button.A)
    mgr.poll()
    # Cross the long threshold (700 ms).
    clock.tick(720)
    events = mgr.poll()
    longs = [e for e in events if e.kind == EventKind.LONG]
    assert len(longs) == 1
    # Continuing to hold must not refire LONG.
    clock.tick(500)
    events = mgr.poll()
    assert not any(e.kind == EventKind.LONG for e in events)
    # After release + re-press, LONG can fire again.
    backend.release(Button.A)
    mgr.poll()
    backend.press(Button.A)
    mgr.poll()
    clock.tick(720)
    events = mgr.poll()
    assert any(e.kind == EventKind.LONG for e in events)


def test_multiple_buttons_handled_independently(
    env: tuple[FakeInputBackend, FakeClock, InputManager],
) -> None:
    backend, _clock, mgr = env
    backend.press(Button.LEFT)
    backend.press(Button.A)
    events = mgr.poll()
    kinds = {(e.button, e.kind) for e in events}
    assert (Button.LEFT, EventKind.PRESS) in kinds
    assert (Button.A, EventKind.PRESS) in kinds


def test_is_pressed_and_hold_ms(
    env: tuple[FakeInputBackend, FakeClock, InputManager],
) -> None:
    backend, clock, mgr = env
    assert not mgr.is_pressed(Button.A)
    backend.press(Button.A)
    mgr.poll()
    assert mgr.is_pressed(Button.A)
    clock.tick(250)
    assert mgr.hold_ms(Button.A) == 250


def test_invalid_construction_args() -> None:
    backend = FakeInputBackend()
    with pytest.raises(ValueError):
        InputManager(backend, debounce_ms=-1)
    with pytest.raises(ValueError):
        InputManager(backend, long_ms=0)
    with pytest.raises(ValueError):
        InputManager(backend, repeat_ms=0)


def test_open_input_fake() -> None:
    backend = open_input("fake")
    assert isinstance(backend, FakeInputBackend)


def test_open_input_auto_falls_back_to_fake_on_mac() -> None:
    backend = open_input("auto")
    # On macOS Blinka is unavailable; we expect a FakeInputBackend.
    assert isinstance(backend, FakeInputBackend)


def test_open_input_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError):
        open_input("dpad-deluxe")
