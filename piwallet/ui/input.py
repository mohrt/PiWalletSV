"""Input event dispatcher for the bonnet joystick + buttons.

Hardware mapping (Adafruit product 4506):

============= ===============
Button        BCM pin
============= ===============
joystick up   GPIO 17
joystick down GPIO 22
joystick left GPIO 27
joystick right GPIO 23
joystick press GPIO 4
button A      GPIO 5
button B      GPIO 6
============= ===============

All buttons are active-low (pulled high by 10 kΩ resistors on the
bonnet). Raw GPIO state is read by ``InputBackend.read_raw()`` and the
``InputManager`` is responsible for debouncing, repeat handling, and
long-press detection.

Design
------
The manager is *time-injectable*: it takes a ``clock()`` callable
returning monotonic milliseconds. Tests use a fake clock to verify
debounce thresholds without sleeping; production wires up
``time.monotonic_ns() // 1_000_000``.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class Button(Enum):
    """Logical button identities. Order matches polling order."""

    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    SELECT = auto()  # joystick press
    A = auto()
    B = auto()


ALL_BUTTONS: tuple[Button, ...] = (
    Button.UP,
    Button.DOWN,
    Button.LEFT,
    Button.RIGHT,
    Button.SELECT,
    Button.A,
    Button.B,
)


class EventKind(Enum):
    """Kinds of events emitted by the InputManager."""

    PRESS = auto()   # button transitioned to pressed (debounced)
    RELEASE = auto()  # button transitioned back to released
    REPEAT = auto()   # button held; emitted at ``repeat_ms`` cadence
    LONG = auto()     # button held past ``long_ms``; fired exactly once


@dataclass(frozen=True, slots=True)
class Event:
    button: Button
    kind: EventKind
    at_ms: int


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class InputBackend(ABC):
    """Reads raw, instantaneous button state from the hardware."""

    @abstractmethod
    def read_raw(self) -> dict[Button, bool]:
        """Return ``{button -> pressed?}`` (True = currently pressed)."""

    def close(self) -> None:  # noqa: B027 (optional override; default no-op by design)
        """Optional teardown hook. Default no-op."""


class FakeInputBackend(InputBackend):
    """Backend whose state is set directly by the test or driver.

    The constructor seeds every button as released. Tests mutate
    :meth:`set` between :meth:`InputManager.poll` calls to script user
    interaction.
    """

    def __init__(self) -> None:
        self._state: dict[Button, bool] = {b: False for b in ALL_BUTTONS}

    def set(self, button: Button, pressed: bool) -> None:
        self._state[button] = pressed

    def press(self, button: Button) -> None:
        self._state[button] = True

    def release(self, button: Button) -> None:
        self._state[button] = False

    def read_raw(self) -> dict[Button, bool]:
        return dict(self._state)


class BonnetInputBackend(InputBackend):
    """Reads the bonnet's GPIO pins via Adafruit Blinka.

    Imported lazily, so the module is safe to import on macOS.
    """

    _PINS: ClassVar[dict[Button, str]] = {
        Button.UP: "D17",
        Button.DOWN: "D22",
        Button.LEFT: "D27",
        Button.RIGHT: "D23",
        Button.SELECT: "D4",
        Button.A: "D5",
        Button.B: "D6",
    }

    def __init__(self) -> None:  # pragma: no cover
        try:
            import board  # type: ignore[import-not-found]
            import digitalio  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "BonnetInputBackend requires the 'display' extra. "
                "Install with `bash scripts/bootstrap-pi-dev.sh` on a Raspberry Pi."
            ) from exc

        self._inputs: dict[Button, Any] = {}
        for button, pin_name in self._PINS.items():
            pin = getattr(board, pin_name)
            io = digitalio.DigitalInOut(pin)
            io.direction = digitalio.Direction.INPUT
            io.pull = digitalio.Pull.UP
            self._inputs[button] = io

    def read_raw(self) -> dict[Button, bool]:  # pragma: no cover
        # Pins are pulled high; pressed means LOW.
        return {b: (not io.value) for b, io in self._inputs.items()}

    def close(self) -> None:  # pragma: no cover
        for io in self._inputs.values():
            io.deinit()


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


def _wall_clock_ms() -> int:
    return time.monotonic_ns() // 1_000_000


class InputManager:
    """Debounces raw button state and emits press / release / repeat / long
    events.

    Timing knobs (defaults chosen for the 1.3" bonnet's mechanical
    switches and a typical handheld bonnet UX):

    =========== ========= =================================================
    Parameter   Default   Meaning
    =========== ========= =================================================
    debounce_ms      0    Minimum stable interval before a transition is
                          accepted. 0 means "trust the raw value the
                          moment we observe it" - fine at our 30 Hz poll
                          cadence because any switch bounce (<= ~5 ms on
                          the tactile switches used by the bonnet) is
                          already over by the time we sample. Hardware
                          tuning may bump this to ~10-15 ms if a polling
                          loop runs faster than 100 Hz.
    long_ms        700    Held past this threshold (same for every button unless
                          overridden via ``long_press_ms_by_button``) emits one
                          ``EventKind.LONG`` per press. Used by disclaimer
                          hold-A / hold-B and other deliberate gestures.
    repeat_initial 400    Delay after PRESS before the first REPEAT.
    repeat_ms      120    Cadence of subsequent REPEATs while held.
    =========== ========= =================================================
    """

    def __init__(
        self,
        backend: InputBackend,
        *,
        debounce_ms: int = 0,
        long_ms: int = 700,
        long_press_ms_by_button: Mapping[Button, int] | None = None,
        repeat_initial_ms: int = 400,
        repeat_ms: int = 120,
        clock: Callable[[], int] = _wall_clock_ms,
    ) -> None:
        if repeat_ms <= 0 or repeat_initial_ms <= 0:
            raise ValueError("repeat timings must be positive")
        if debounce_ms < 0 or long_ms <= 0:
            raise ValueError("debounce_ms must be non-negative and long_ms positive")
        overrides: dict[Button, int] = dict(long_press_ms_by_button or ())
        bad = [(b, ms) for b, ms in overrides.items() if ms <= 0]
        if bad:
            raise ValueError(f"long_press_ms_by_button values must be positive: {bad!r}")

        self._backend = backend
        self._debounce_ms = debounce_ms
        self._long_ms = long_ms
        self._long_press_ms_by_button: dict[Button, int] = overrides
        self._repeat_initial_ms = repeat_initial_ms
        self._repeat_ms = repeat_ms
        self._clock = clock

        # Logical "is this button currently pressed?" after debounce.
        self._pressed: dict[Button, bool] = {b: False for b in ALL_BUTTONS}
        # Last sample, used purely for debounce window timing.
        self._last_raw: dict[Button, bool] = {b: False for b in ALL_BUTTONS}
        # Time of last raw transition for this button. Used to evaluate
        # whether enough stable time has passed to accept the new state.
        self._last_transition_ms: dict[Button, int] = {b: 0 for b in ALL_BUTTONS}
        # When the (debounced) press started, in ms; or None if released.
        self._press_started_ms: dict[Button, int | None] = {b: None for b in ALL_BUTTONS}
        # When we last emitted a REPEAT event.
        self._last_repeat_ms: dict[Button, int] = {b: 0 for b in ALL_BUTTONS}
        # Whether we've already emitted the LONG event for this press.
        self._long_fired: dict[Button, bool] = {b: False for b in ALL_BUTTONS}

    def now_ms(self) -> int:
        """Monotonic milliseconds (same clock as debounce / long-press timing)."""
        return self._clock()

    def raw_any_pressed(self) -> bool:
        """True if any hardware button reads pressed *right now* (pre-debounce).

        Used to wake the display from idle blanking on the first 30 Hz sample
        where the user has closed a contact, before :meth:`poll` may emit a
        debounced :class:`Event`.
        """
        raw = self._backend.read_raw()
        return any(raw.get(b, False) for b in ALL_BUTTONS)

    # -- queries used by widget code ----------------------------------

    def is_pressed(self, button: Button) -> bool:
        return self._pressed[button]

    def hold_ms(self, button: Button, *, now_ms: int | None = None) -> int:
        """Milliseconds the button has been held continuously, or 0."""
        started = self._press_started_ms[button]
        if started is None:
            return 0
        now = now_ms if now_ms is not None else self._clock()
        return max(0, now - started)

    # -- the main poll() entry point ----------------------------------

    def poll(self) -> list[Event]:
        """Sample the backend, advance state machines, return events.

        Call from the app main loop (e.g. once per frame). The returned
        events are in chronological order *within* this poll.
        """
        now = self._clock()
        raw = self._backend.read_raw()
        events: list[Event] = []

        for button in ALL_BUTTONS:
            new_raw = raw.get(button, False)
            old_raw = self._last_raw[button]
            if new_raw != old_raw:
                # Raw just changed; reset the debounce window. We do NOT
                # short-circuit here — if debounce_ms == 0 we still want
                # the same poll to commit the new state.
                self._last_raw[button] = new_raw
                self._last_transition_ms[button] = now

            # Require the raw value to have been stable for at least
            # `debounce_ms`. With debounce_ms = 0 (the default) this is
            # always satisfied and the manager commits transitions as
            # soon as they're observed.
            stable_for = now - self._last_transition_ms[button]
            if stable_for < self._debounce_ms:
                continue

            logical = self._pressed[button]
            if new_raw and not logical:
                # PRESS edge.
                self._pressed[button] = True
                self._press_started_ms[button] = now
                self._last_repeat_ms[button] = now
                self._long_fired[button] = False
                events.append(Event(button, EventKind.PRESS, now))
            elif (not new_raw) and logical:
                # RELEASE edge.
                self._pressed[button] = False
                self._press_started_ms[button] = None
                events.append(Event(button, EventKind.RELEASE, now))
            elif logical:
                # Still held. Maybe emit LONG / REPEAT.
                started = self._press_started_ms[button]
                if started is None:
                    # Defensive: shouldn't happen.
                    continue
                held = now - started
                long_threshold_ms = (
                    self._long_press_ms_by_button.get(button, self._long_ms)
                )
                if (
                    not self._long_fired[button]
                    and held >= long_threshold_ms
                ):
                    self._long_fired[button] = True
                    events.append(Event(button, EventKind.LONG, now))
                # Repeats only kick in after the initial delay.
                if held >= self._repeat_initial_ms:
                    since_last = now - self._last_repeat_ms[button]
                    if since_last >= self._repeat_ms:
                        self._last_repeat_ms[button] = now
                        events.append(Event(button, EventKind.REPEAT, now))

        return events


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def open_input(backend: str = "auto") -> InputBackend:
    """Construct an input backend.

    ``backend`` can be:

    * ``"auto"``     — try the bonnet GPIO, fall back to a fake (no
                       buttons; useful for headless smoke tests).
    * ``"bonnet"``   — force the real GPIO. Raises if unavailable.
    * ``"fake"``     — always use :class:`FakeInputBackend`.
    """
    if backend == "fake":
        return FakeInputBackend()
    if backend == "bonnet":
        return BonnetInputBackend()
    if backend == "auto":
        try:
            return BonnetInputBackend()
        except RuntimeError as exc:
            # Visible at WARNING by default — the production unit
            # pins --input bonnet to fail loudly instead of running
            # input-less, but `piwallet bonnet` from a dev laptop
            # still wants the auto downgrade.
            logger.warning(
                "Bonnet GPIO input unavailable, falling back to "
                "FakeInputBackend: %s",
                exc,
            )
            return FakeInputBackend()
    raise ValueError(f"unknown input backend: {backend!r}")
