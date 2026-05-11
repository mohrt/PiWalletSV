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
and repaints. Anything fancier (animations, async work) should be
driven by the screen itself on each ``draw()``.
"""

from __future__ import annotations

import time
from abc import abstractmethod
from typing import Protocol, runtime_checkable

from piwallet.ui.display import Display, FrameBuffer
from piwallet.ui.input import Event, InputBackend, InputManager


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
) -> object | None:
    """Drive ``screen`` until ``screen.done`` is True.

    Returns ``screen.result``.

    ``max_iterations`` is useful for tests: pass a finite cap so we
    don't loop forever if the test's scripted input fails to mark the
    screen done.

    ``sleep`` defaults to True for the real app loop. Tests pass
    ``sleep=False`` so the loop runs as fast as the fake clock can
    advance.
    """
    frame_budget = 1.0 / max(1, target_fps)
    fb = FrameBuffer(width=display.width, height=display.height)
    iterations = 0
    while not screen.done:
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1
        for event in input_mgr.poll():
            screen.on_event(event)
            if screen.done:
                break
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
    repeat_initial_ms: int = 400,
    repeat_ms: int = 120,
) -> InputManager:
    """Convenience constructor with sensible defaults."""
    kwargs = dict(
        debounce_ms=debounce_ms,
        long_ms=long_ms,
        repeat_initial_ms=repeat_initial_ms,
        repeat_ms=repeat_ms,
    )
    if clock is not None:
        kwargs["clock"] = clock
    return InputManager(backend, **kwargs)
