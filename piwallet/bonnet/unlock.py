"""Vault unlock screen.

Wraps :class:`piwallet.ui.pin_entry.PinEntryScreen` with a verify
callback so the surrounding bonnet flow can recover or fail cleanly.
Wrong PIN retries immediately show a fresh PIN entry with one fewer
attempt, a visible Wrong PIN line in red, and the updated attempts hint
(no interim cancel path).

Outcome contract (returned via ``result``):

* ``("ok", pin)``       on success - caller keeps the PIN in scope only
                         as long as it needs it.
* ``("wiped", None)``    if the vault wiped itself after too many tries.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from piwallet.ui.display import COLOR_DANGER, FrameBuffer
from piwallet.ui.input import Event
from piwallet.ui.pin_entry import PinEntryScreen, attempts_subtitle
from piwallet.ui.widgets import Modal

UnlockOutcomeKind = Literal["ok", "wiped"]


@dataclass(frozen=True, slots=True)
class UnlockOutcome:
    kind: UnlockOutcomeKind
    pin: str | None  # populated only when kind == "ok"


# A verify callback returns one of three things:
#   ("ok", None)         -- PIN is correct
#   ("wrong", n)         -- PIN is wrong; `n` attempts remaining
#   ("wiped", None)      -- the vault has been wiped (don't retry)
VerifyResult = tuple[Literal["ok", "wrong", "wiped"], int | None]
VerifyFn = Callable[[str], VerifyResult]


@dataclass
class UnlockScreen:
    """Composes a ``PinEntryScreen`` with a verify-and-retry loop."""

    verify: VerifyFn
    length: int = 6
    attempts_remaining: int = 10
    done: bool = False
    result: UnlockOutcome | None = None
    pin_entry: PinEntryScreen = field(init=False)

    def __post_init__(self) -> None:
        self.pin_entry = self._make_pin_screen()

    def _make_pin_screen(self, *, after_wrong_pin: bool = False) -> PinEntryScreen:
        subtitle, color = attempts_subtitle(self.attempts_remaining)
        return PinEntryScreen(
            length=self.length,
            title="Unlock vault",
            subtitle=subtitle,
            subtitle_color=color,
            subtitle_alert="Wrong PIN" if after_wrong_pin else "",
            masked=False,  # show digits while editing; mask not enabled for v1
        )

    # -- driver-facing API ---------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        self.pin_entry.on_event(event)
        if not self.pin_entry.done:
            return
        assert self.pin_entry.result is not None
        pin = str(self.pin_entry.result)
        outcome, info = self.verify(pin)
        if outcome == "ok":
            self.done = True
            self.result = UnlockOutcome(kind="ok", pin=pin)
        elif outcome == "wiped":
            self.done = True
            self.result = UnlockOutcome(kind="wiped", pin=None)
        else:
            assert outcome == "wrong"
            remaining = (
                int(info) if info is not None
                else max(0, self.attempts_remaining - 1)
            )
            self.attempts_remaining = remaining
            if self.attempts_remaining <= 0:
                self.done = True
                self.result = UnlockOutcome(kind="wiped", pin=None)
                return
            self.pin_entry = self._make_pin_screen(after_wrong_pin=True)

    def draw(self, fb: FrameBuffer) -> None:
        if self.done and self.result is not None and self.result.kind == "wiped":
            Modal(
                title="Vault wiped",
                body=(
                    "Too many wrong PINs. The vault has been "
                    "destroyed. Restore from your seed phrase."
                ),
                footer="B: back",
                accent=COLOR_DANGER,
            ).draw(fb)
            return
        self.pin_entry.draw(fb)
