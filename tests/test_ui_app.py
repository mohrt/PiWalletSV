"""End-to-end driver test: scripted user input + screen state machine."""

from __future__ import annotations

from dataclasses import dataclass

from piwallet.ui.app import (
    IdleWakeTracker,
    idle_suppresses_frame_paint,
    run_screen,
)
from piwallet.ui.display import FrameBuffer, HeadlessDisplay
from piwallet.ui.input import Button, Event, EventKind, FakeInputBackend, InputManager


class _Clock:
    def __init__(self, start: int = 0) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def tick(self, ms: int) -> None:
        self.now += ms


@dataclass
class _MenuScreen:
    """Trivial 2-item menu: ↓ to navigate, A to confirm."""

    items: tuple[str, ...] = ("send", "receive")
    cursor: int = 0
    done: bool = False
    result: object | None = None

    def on_event(self, event: Event) -> None:
        if event.kind != EventKind.PRESS:
            return
        if event.button == Button.DOWN:
            self.cursor = (self.cursor + 1) % len(self.items)
        elif event.button == Button.A:
            self.result = self.items[self.cursor]
            self.done = True

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear()


def _script_input(
    backend: FakeInputBackend,
    clock: _Clock,
    mgr: InputManager,
    screen: _MenuScreen,
    sequence: list[tuple[int, Button, bool]],
) -> None:
    """Drive (backend, manager) with a scripted sequence.

    Each tuple is ``(advance_ms, button, pressed)``. Between actions we
    call the driver once to flush a frame.
    """
    display = HeadlessDisplay()
    iterator = iter(sequence)

    def apply_next() -> bool:
        try:
            advance, button, pressed = next(iterator)
        except StopIteration:
            return False
        clock.tick(advance)
        backend.set(button, pressed)
        return True

    # Pre-apply the first action so the first poll inside run_screen
    # sees something interesting.
    if not apply_next():
        return

    # Replace run_screen's blocking sleep loop with a hand-rolled driver
    # that swaps in subsequent scripted actions.
    fb = FrameBuffer()
    while not screen.done:
        for ev in mgr.poll():
            screen.on_event(ev)
            if screen.done:
                break
        screen.draw(fb)
        display.flip(fb)
        if not apply_next():
            # Run one more poll cycle so the final transition can settle.
            clock.tick(50)
            for ev in mgr.poll():
                screen.on_event(ev)
            break


def test_scripted_input_drives_menu_to_confirmation() -> None:
    backend = FakeInputBackend()
    clock = _Clock()
    mgr = InputManager(backend, clock=clock)
    screen = _MenuScreen()

    _script_input(
        backend,
        clock,
        mgr,
        screen,
        sequence=[
            # DOWN press, then release; then A press, then release.
            (1, Button.DOWN, True),
            (10, Button.DOWN, False),
            (10, Button.A, True),
            (10, Button.A, False),
        ],
    )

    assert screen.done is True
    assert screen.result == "receive"


def test_idle_suppresses_frame_paint_after_timeout() -> None:
    backend = FakeInputBackend()
    clock = _Clock(0)
    mgr = InputManager(backend, clock=clock, debounce_ms=0)
    idle = IdleWakeTracker(mgr, timeout_ms=500)
    assert idle.last_activity_ms == 0
    clock.tick(600)
    display = HeadlessDisplay()
    assert idle_suppresses_frame_paint(
        display, idle, [], mgr.now_ms(), input_mgr=mgr
    ) is True
    assert idle.asleep
    assert display.backlight_on is False


def test_idle_wake_on_next_input() -> None:
    backend = FakeInputBackend()
    clock = _Clock(0)
    mgr = InputManager(backend, clock=clock, debounce_ms=0)
    idle = IdleWakeTracker(mgr, timeout_ms=100)
    clock.tick(200)
    display = HeadlessDisplay()
    assert idle_suppresses_frame_paint(
        display, idle, [], mgr.now_ms(), input_mgr=mgr
    ) is True
    assert idle.asleep
    assert display.backlight_on is False
    backend.press(Button.A)
    events = mgr.poll()
    assert events
    assert idle_suppresses_frame_paint(
        display, idle, events, mgr.now_ms(), input_mgr=mgr
    ) is False
    assert not idle.asleep
    assert display.backlight_on is True


def test_idle_timeout_zero_never_sleeps() -> None:
    """``timeout_ms == 0`` is the "Off" preset; the panel never blanks.

    Even after a long quiet period the idle tracker must not flip to
    asleep state. This is the path Settings -> Sleep timer -> Off
    wires up.
    """
    backend = FakeInputBackend()
    clock = _Clock(0)
    mgr = InputManager(backend, clock=clock, debounce_ms=0)
    idle = IdleWakeTracker(mgr, timeout_ms=0)
    display = HeadlessDisplay()
    # 30 minutes of idle wall-clock time.
    clock.tick(1_800_000)
    assert idle_suppresses_frame_paint(
        display, idle, [], mgr.now_ms(), input_mgr=mgr
    ) is False
    assert idle.asleep is False
    assert display.backlight_on is True


def test_idle_timeout_zero_wakes_panel_if_previously_asleep() -> None:
    """Switching to "Off" while asleep must turn the backlight back on.

    Operator path: timer at 1 min, panel blanks, operator goes to
    Settings, drops timer to "Off", saves; the bonnet writes
    ``idle.timeout_ms = 0`` in place. The next idle poll has to
    notice the asleep state and reverse it instead of leaving the
    panel dark forever.
    """
    backend = FakeInputBackend()
    clock = _Clock(0)
    mgr = InputManager(backend, clock=clock, debounce_ms=0)
    idle = IdleWakeTracker(mgr, timeout_ms=60_000)
    display = HeadlessDisplay()
    clock.tick(120_000)
    idle_suppresses_frame_paint(
        display, idle, [], mgr.now_ms(), input_mgr=mgr
    )
    assert idle.asleep is True
    assert display.backlight_on is False
    # Operator picks "Off" -> caller mutates timeout_ms in place.
    idle.timeout_ms = 0
    assert idle_suppresses_frame_paint(
        display, idle, [], mgr.now_ms(), input_mgr=mgr
    ) is False
    assert idle.asleep is False
    assert display.backlight_on is True


def test_idle_wake_on_raw_before_debounced_press() -> None:
    """First poll after contact may emit zero events when debounce_ms > 0."""
    backend = FakeInputBackend()
    clock = _Clock(0)
    mgr = InputManager(backend, clock=clock, debounce_ms=40)
    idle = IdleWakeTracker(mgr, timeout_ms=100)
    clock.tick(200)
    display = HeadlessDisplay()
    assert idle_suppresses_frame_paint(
        display, idle, [], mgr.now_ms(), input_mgr=mgr
    ) is True
    backend.press(Button.A)
    events = mgr.poll()
    # Debounce hides the edge on this sample; without raw wake we'd stay blank.
    assert idle_suppresses_frame_paint(
        display, idle, events, mgr.now_ms(), input_mgr=mgr
    ) is False
    assert not idle.asleep
    assert display.backlight_on is True


def test_idle_sleep_sets_pin_locked_and_calls_on_pin_lock() -> None:
    backend = FakeInputBackend()
    clock = _Clock(0)
    mgr = InputManager(backend, clock=clock, debounce_ms=0)
    idle = IdleWakeTracker(mgr, timeout_ms=100)
    locked: list[bool] = []

    def _on_lock() -> None:
        locked.append(True)

    idle.on_pin_lock = _on_lock
    clock.tick(200)
    display = HeadlessDisplay()
    assert idle_suppresses_frame_paint(
        display, idle, [], mgr.now_ms(), input_mgr=mgr
    ) is True
    assert idle.asleep
    assert idle.pin_locked
    assert locked == [True]


def test_run_screen_wake_runs_on_unlock_and_swallows_wake_event() -> None:
    """After sleep, the wake button must not reach the underlying screen."""
    backend = FakeInputBackend()
    clock = _Clock(0)
    mgr = InputManager(backend, clock=clock, debounce_ms=0)
    idle = IdleWakeTracker(mgr, timeout_ms=100)
    unlocked: list[bool] = []
    idle.on_unlock = lambda: unlocked.append(True)

    @dataclass
    class _TapCounter:
        taps: int = 0
        done: bool = False
        result: object | None = None

        def on_event(self, event: Event) -> None:
            if event.kind == EventKind.PRESS:
                self.taps += 1
                self.done = True
                self.result = self.taps

        def draw(self, fb: FrameBuffer) -> None:
            fb.clear()

    display = HeadlessDisplay()
    screen = _TapCounter()
    clock.tick(200)
    idle_suppresses_frame_paint(display, idle, [], mgr.now_ms(), input_mgr=mgr)
    assert idle.asleep and idle.pin_locked

    backend.press(Button.A)
    run_screen(
        display,
        mgr,
        screen,
        sleep=False,
        idle_wake=idle,
        max_iterations=1,
    )
    assert unlocked == [True]
    assert screen.taps == 0
    assert idle.pin_locked is False


def test_run_screen_respects_max_iterations() -> None:
    """A screen that never sets done must not loop forever in tests."""
    backend = FakeInputBackend()
    clock = _Clock()
    mgr = InputManager(backend, clock=clock)
    display = HeadlessDisplay()

    @dataclass
    class _NeverDone:
        done: bool = False
        result: object | None = "never"

        def on_event(self, event: Event) -> None:
            pass

        def draw(self, fb: FrameBuffer) -> None:
            fb.clear()

    screen = _NeverDone()
    result = run_screen(display, mgr, screen, max_iterations=5, sleep=False)
    assert screen.done is False  # bail-out path
    assert result == "never"  # we still return the current result
    assert display.flip_count == 5
