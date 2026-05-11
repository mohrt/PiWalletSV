"""End-to-end driver test: scripted user input + screen state machine."""

from __future__ import annotations

from dataclasses import dataclass

from piwallet.ui.app import run_screen
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
