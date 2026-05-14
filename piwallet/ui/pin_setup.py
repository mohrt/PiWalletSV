"""PIN-setup composite screen (double-confirm new PIN entry).

Wraps two sequential :class:`piwallet.ui.pin_entry.PinEntryScreen`
phases — "Choose PIN" and "Confirm PIN" — and only succeeds when both
entries match digit-for-digit. Used by:

* the **first-boot vault setup** flow (``piwallet.bonnet.vault_setup``)
  to ask the operator for the *initial* PIN that will encrypt the
  vault, and
* the **change-PIN** flow (``piwallet.bonnet.change_pin``) reachable
  from the Settings screen, which uses this composite for the *new*
  PIN portion (the *current* PIN is verified separately via
  :class:`piwallet.bonnet.unlock.UnlockScreen`).

Behaviour
---------
=========================  ====================================================
Phase ``"first"``           PinEntryScreen titled with ``prompt`` (e.g.
                            "Choose a PIN"). The operator types and
                            confirms with A; the digits are stashed and
                            the screen flips to phase ``"confirm"``.
Phase ``"confirm"``         PinEntryScreen titled "Confirm PIN". Pressing
                            A compares the second entry to the first.
                            On match: ``result = <pin>``. On mismatch:
                            an alert ("PINs did not match") is rendered
                            on a freshly cleared first-phase screen so
                            the operator can start over without
                            retyping the cancellation gesture.
B PRESS                     Forwarded to the inner PinEntryScreen
                            (backspace).
B LONG (when cancellable)   Aborts the flow with ``result = None``. Off
                            by default — first-boot vault setup is not
                            cancellable, change-PIN is.
=========================  ====================================================

Why a fresh screen on mismatch
------------------------------
Reusing the same :class:`PinEntryScreen` instance and calling
``reset()`` would also work, but a brand-new instance has the side
benefit of resetting the cursor *and* the per-screen REPEAT throttle,
so the operator's first UP/DOWN tap after the alert always cycles
immediately. It also matches the pattern used by
:class:`piwallet.bonnet.unlock.UnlockScreen` for the wrong-PIN retry,
keeping screens-with-retry uniform across the codebase.

The :class:`PinSetupScreen` is intentionally pure (no vault calls) so
the two callers can apply the resulting PIN however they like —
``vault.create(pin)`` for first-boot, ``vault.change_pin(old, pin)``
for the settings flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.pin_entry import PinEntryScreen

PinSetupPhase = Literal["first", "confirm"]


@dataclass
class PinSetupScreen:
    """Drive a "type new PIN twice" flow over a :class:`PinEntryScreen`."""

    length: int = 6
    prompt: str = "Choose a PIN"
    confirm_prompt: str = "Confirm PIN"
    #: When ``True``, a long-press on B aborts the flow and sets
    #: ``result = None``. Leave ``False`` for first-boot setup so the
    #: operator can't end up with no vault after the disclaimer.
    cancellable: bool = False

    phase: PinSetupPhase = "first"
    done: bool = False
    #: ``str`` once both entries match, ``None`` while editing or on
    #: cancel. The discriminator is :attr:`done`.
    result: str | None = None
    _first_pin: str | None = field(default=None, repr=False)
    pin_entry: PinEntryScreen = field(init=False)
    #: Mismatch alert text rendered on the first-phase screen after a
    #: failed confirmation. Empty string in steady state.
    _alert: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        self.pin_entry = self._make_pin_screen(self.prompt)

    # -- internals ---------------------------------------------------

    def _make_pin_screen(self, title: str, *, alert: str = "") -> PinEntryScreen:
        return PinEntryScreen(
            length=self.length,
            title=title,
            subtitle="",
            subtitle_alert=alert,
            masked=False,
        )

    # -- input -------------------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if (
            self.cancellable
            and event.button == Button.B
            and event.kind == EventKind.LONG
        ):
            self.done = True
            self.result = None
            return
        self.pin_entry.on_event(event)
        if not self.pin_entry.done:
            return
        # PinEntryScreen always returns the entered PIN as a str when
        # confirmed; the assert is belt-and-braces against future
        # protocol changes.
        assert isinstance(self.pin_entry.result, str)
        entered = self.pin_entry.result

        if self.phase == "first":
            self._first_pin = entered
            self.phase = "confirm"
            self.pin_entry = self._make_pin_screen(self.confirm_prompt)
            self._alert = ""
            return

        # phase == "confirm"
        if entered == self._first_pin:
            self.done = True
            self.result = entered
            return
        # Mismatch -> bounce back to phase "first" with an alert.
        self.phase = "first"
        self._first_pin = None
        self._alert = "PINs did not match"
        self.pin_entry = self._make_pin_screen(self.prompt, alert=self._alert)

    # -- render ------------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        self.pin_entry.draw(fb)
