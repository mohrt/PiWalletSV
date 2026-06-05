"""Bonnet app driver.

A *screen* is anything that implements two methods:

* ``draw(framebuf)`` — paint the current state to the framebuffer.
* ``on_event(event)`` — react to an input event.

A screen signals it has finished by setting its ``done`` attribute to
``True``. The driver then exits its loop and returns the screen's
``result``. This lets higher-level flows compose multiple screens
without each screen having to know about the overall main loop.

The driver is deliberately minimal: it sleeps for a fixed budget per
frame (defaulting to ~33 ms ≈ 30 fps), polls input, dispatches events,
and repaints. When :class:`IdleWakeTracker` is passed to
:func:`run_screen`, the backlight blanks after sixty seconds without
_any_ input events; the next event turns it back on before the screen
handles the press. Animations belong in ``draw()`` or higher-level loops.
"""

from __future__ import annotations

import time
from abc import abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from piwallet.ui.display import Display, FrameBuffer
from piwallet.ui.input import Button, Event, InputBackend, InputManager

class IdleUnlockWiped(Exception):
    """Raised when the vault wipes during post-sleep PIN entry."""

# Default bonnet idle blanking (backlight off until the next button event).
# Five minutes matches `piwallet.core.settings.DEFAULT_SLEEP_TIMEOUT_MS`;
# do not edit one without the other.
IDLE_TIMEOUT_MS: int = 300_000


@dataclass
class IdleWakeTracker:
    """Dim the panel after ``timeout_ms`` without any input event.

    Wired into :func:`run_screen` for every bonnet flow. Uses the same
    millisecond clock as the :class:`InputManager` so tests can fast-forward
    idle with a synthetic clock.

    ``timeout_ms == 0`` disables sleep entirely: the panel stays lit
    until the bonnet exits. The Settings screen surfaces this as the
    "Off" preset; operators on a bench-mounted device with mains power
    typically pick it.
    """

    input_mgr: InputManager
    timeout_ms: int = IDLE_TIMEOUT_MS
    last_activity_ms: int = field(init=False)
    asleep: bool = False
    pin_locked: bool = False
    on_pin_lock: Callable[[], None] | None = None
    on_unlock: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        self.last_activity_ms = self.input_mgr.now_ms()


def idle_suppresses_frame_paint(
    display: Display,
    idle_wake: IdleWakeTracker | None,
    events: list[Event],
    now_ms: int,
    *,
    input_mgr: InputManager | None = None,
) -> bool:
    """Update idle backlight state after :meth:`InputManager.poll`.

    Returns ``True`` when ``run_screen`` should skip ``draw``/``flip`` for
    this frame because the backlight is off and no input woke the panel.
    """
    if idle_wake is None:
        return False
    # ``timeout_ms == 0`` is the "Off" preset: never blank, never wake;
    # we still record activity so a later edit that re-enables sleep
    # starts counting from the right reference point.
    if idle_wake.timeout_ms <= 0:
        if events:
            idle_wake.last_activity_ms = events[-1].at_ms
        if idle_wake.asleep:
            # Defensive: if a previous (smaller) timeout ever put us
            # to sleep and the operator then disabled sleep, undo it.
            idle_wake.asleep = False
            display.set_backlight(True)
        return False
    if events:
        idle_wake.last_activity_ms = events[-1].at_ms
        if idle_wake.asleep:
            idle_wake.asleep = False
            display.set_backlight(True)
        return False
    # Debounce can defer the first PRESS to a later poll; raw wake avoids a
    # stuck blank panel until the debounce window elapses.
    if (
        idle_wake.asleep
        and input_mgr is not None
        and input_mgr.raw_any_pressed()
    ):
        idle_wake.last_activity_ms = now_ms
        idle_wake.asleep = False
        display.set_backlight(True)
        return False
    if not idle_wake.asleep:
        if now_ms - idle_wake.last_activity_ms >= idle_wake.timeout_ms:
            idle_wake.asleep = True
            idle_wake.pin_locked = True
            if idle_wake.on_pin_lock is not None:
                idle_wake.on_pin_lock()
            display.set_backlight(False)
            return True
        return False
    # Staying asleep until the next event.
    return True


@runtime_checkable
class Screen(Protocol):
    """Anything the driver can run."""

    done: bool
    result: object | None

    @abstractmethod
    def draw(self, fb: FrameBuffer) -> None: ...

    @abstractmethod
    def on_event(self, event: Event) -> None: ...


def run_screen(
    display: Display,
    input_mgr: InputManager,
    screen: Screen,
    *,
    target_fps: int = 30,
    max_iterations: int | None = None,
    sleep: bool = True,
    idle_wake: IdleWakeTracker | None = None,
    ignore_pin_lock: bool = False,
) -> object | None:
    """Drive ``screen`` until ``screen.done`` is True.

    Returns ``screen.result``.

    ``max_iterations`` is useful for tests: pass a finite cap so we
    don't loop forever if the test's scripted input fails to mark the
    screen done.

    ``sleep`` defaults to True for the real app loop. Tests pass
    ``sleep=False`` so the loop runs as fast as the fake clock can
    advance.

    ``idle_wake`` turns the backlight off after its timeout with no input
    (see :class:`IdleWakeTracker`). The next input wakes the backlight
    before events are dispatched to ``screen``.

    When ``idle_wake.pin_locked`` is set (panel blanked by the sleep
    timer), the next wake runs ``idle_wake.on_unlock`` before the
    underlying screen sees input. Pass ``ignore_pin_lock=True`` for
    the unlock screen itself.
    """
    frame_budget = 1.0 / max(1, target_fps)
    fb = FrameBuffer(width=display.width, height=display.height)
    iterations = 0
    while not screen.done:
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1
        events = input_mgr.poll()
        now_ms = input_mgr.now_ms()
        was_asleep = idle_wake.asleep if idle_wake is not None else False
        suppress_paint = idle_suppresses_frame_paint(
            display, idle_wake, events, now_ms, input_mgr=input_mgr
        )
        just_woke = (
            idle_wake is not None
            and was_asleep
            and not idle_wake.asleep
            and idle_wake.pin_locked
        )
        if just_woke and not ignore_pin_lock:
            events = []
            if idle_wake.on_unlock is not None:
                idle_wake.on_unlock()
                idle_wake.pin_locked = False
            else:
                idle_wake.pin_locked = False
        for event in events:
            screen.on_event(event)
            if screen.done:
                break
        if events:
            # A button press may have capacitively coupled to the RST or DC
            # line and left the ST7789 in sleep mode.  recover() re-asserts
            # SLPOUT + MADCTL + DISPON so the next flip is visible.
            display.recover()
        if not suppress_paint:
            screen.draw(fb)
            display.flip(fb)
        if sleep:
            time.sleep(frame_budget)
    return screen.result


def make_input_manager(
    backend: InputBackend,
    *,
    clock=None,
    debounce_ms: int = 15,
    long_ms: int = 700,
    long_press_ms_by_button: Mapping[Button, int] | None = None,
    repeat_initial_ms: int = 400,
    repeat_ms: int = 120,
) -> InputManager:
    """Convenience :class:`InputManager` preset for bonnet polling (debounced)."""
    extra: dict[str, object] = {}
    if long_press_ms_by_button is not None:
        extra["long_press_ms_by_button"] = dict(long_press_ms_by_button)
    if clock is not None:
        extra["clock"] = clock
    return InputManager(
        backend,
        debounce_ms=debounce_ms,
        long_ms=long_ms,
        repeat_initial_ms=repeat_initial_ms,
        repeat_ms=repeat_ms,
        **extra,
    )
