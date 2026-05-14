"""Bonnet PIN entry screen.

Reusable, domain-agnostic numeric-PIN entry widget. The screen exposes
fixed-length digit slots (default 6); the user adjusts each slot with
the joystick and confirms with A. On confirm the entered PIN is
returned as a string in ``result``. There is intentionally no bail-out:
the enclosing flow must retain the device gate.

The screen is intentionally pure: it does NOT call the vault. Compose
it inside a higher-level "unlock" flow that owns the verify-and-retry
loop.

Controls
--------
====== ======================================================
Input  Effect
====== ======================================================
UP     Cycle current slot's digit forward (... 8 -> 9 -> 0).
DOWN   Cycle current slot's digit backward (... 1 -> 0 -> 9).
LEFT   Move active slot left (clamped at slot 0).
RIGHT  Move active slot right (clamped at last slot).
A      Confirm. If any slot is empty, advance to the next
       empty slot instead.
B PRESS Backspace: clear the current slot and move left.
       (Long presses on ``B`` are ignored so accidental holds do not quit.)
SELECT Same as A.
====== ======================================================

Empty slots render as ``_``. Filled slots render their digit while
the screen is live; if ``masked=True`` is set, non-active filled
slots render as ``*`` so a shoulder-surfer only sees the cell the
user is currently editing.

Repeat throttling
-----------------
The default :class:`InputManager` repeat cadence (120 ms) cycles
digits at ~8/sec when UP/DOWN is held — fast enough that operators
overshoot the digit they wanted. Digit cycling on this screen
throttles ``REPEAT`` events to :data:`_DIGIT_REPEAT_THROTTLE_MS`
(~3 cycles/sec), giving each digit step a deliberate visual beat.
``PRESS`` always cycles immediately so single taps stay snappy. Cell
movement (LEFT/RIGHT) is not throttled — it's clamped at ``length``
slots and benefits from quick scrolling.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import draw_text

# Default visual layout — tuned for a 6-digit PIN on a 240x240 panel.
_CELL_WIDTH = 30
_CELL_HEIGHT = 44
_CELL_GAP = 6

#: Minimum interval between digit cycles when UP/DOWN is held. The
#: input layer fires REPEAT events at ~120 ms cadence (8/sec); at that
#: rate a 0..9 digit reel blurs past faster than operators can react.
#: 320 ms (~3/sec) gives each digit a clearly-readable beat without
#: making intentional cycling tedious. PRESS bypasses this throttle so
#: single taps still feel instantaneous.
_DIGIT_REPEAT_THROTTLE_MS: int = 320


@dataclass
class PinEntryScreen:
    """Numeric PIN entry. See module docstring for controls."""

    length: int = 6
    title: str = "Enter PIN"
    subtitle: str = ""  # e.g. "3 attempts left"
    subtitle_color: tuple[int, int, int] = COLOR_DIM
    subtitle_alert: str = ""  # optional red line above subtitle (e.g. "Wrong PIN")
    masked: bool = False
    cursor: int = 0
    done: bool = False
    result: object | None = None  # str pin on confirm; None while editing
    digits: list[int | None] = field(default_factory=list)
    # Wall time of the last accepted UP/DOWN cycle. Used to throttle
    # REPEAT events so held-joystick scrolling lands on the right digit
    # (see :data:`_DIGIT_REPEAT_THROTTLE_MS`). The very-negative default
    # makes the first PRESS / first REPEAT after construction always
    # accept regardless of clock skew.
    _last_cycle_at_ms: int = field(default=-(10**9), repr=False)

    def __post_init__(self) -> None:
        if self.length < 4 or self.length > 12:
            raise ValueError(f"PIN length must be 4..12, got {self.length}")
        if not self.digits:
            self.digits = [None] * self.length
        elif len(self.digits) != self.length:
            raise ValueError(
                f"digits seed must match length={self.length}, "
                f"got {len(self.digits)}"
            )
        self.cursor = max(0, min(self.cursor, self.length - 1))

    # -- input handling -----------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind

        if b == Button.UP and self._should_cycle(k, event.at_ms):
            self._cycle(+1)
            self._last_cycle_at_ms = event.at_ms
        elif b == Button.DOWN and self._should_cycle(k, event.at_ms):
            self._cycle(-1)
            self._last_cycle_at_ms = event.at_ms
        elif b == Button.LEFT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._move_cursor(-1)
        elif b == Button.RIGHT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._move_cursor(+1)
        elif b in (Button.A, Button.SELECT) and k == EventKind.PRESS:
            self._confirm_or_advance()
        elif b == Button.B and k == EventKind.PRESS:
            self._backspace()

    def _should_cycle(self, kind: EventKind, at_ms: int) -> bool:
        """Decide whether an UP/DOWN event should advance the current digit.

        Always honours ``PRESS``; throttles ``REPEAT`` to the configured
        digit cadence so held-joystick scrolling is controllable.
        """
        if kind == EventKind.PRESS:
            return True
        if kind != EventKind.REPEAT:
            return False
        return at_ms - self._last_cycle_at_ms >= _DIGIT_REPEAT_THROTTLE_MS

    def _cycle(self, delta: int) -> None:
        cur = self.digits[self.cursor]
        new = 0 if cur is None else (cur + delta) % 10
        self.digits[self.cursor] = new

    def _move_cursor(self, delta: int) -> None:
        self.cursor = max(0, min(self.cursor + delta, self.length - 1))

    def _confirm_or_advance(self) -> None:
        if all(d is not None for d in self.digits):
            self.done = True
            self.result = "".join(str(d) for d in self.digits)
            return
        # Otherwise jump to the next empty slot.
        for i in range(self.cursor + 1, self.length):
            if self.digits[i] is None:
                self.cursor = i
                return
        for i in range(0, self.cursor):
            if self.digits[i] is None:
                self.cursor = i
                return

    def _backspace(self) -> None:
        if self.digits[self.cursor] is not None:
            self.digits[self.cursor] = None
        elif self.cursor > 0:
            self.cursor -= 1
            self.digits[self.cursor] = None

    # -- introspection (for tests / composition) ----------------------

    def is_complete(self) -> bool:
        return all(d is not None for d in self.digits)

    def reset(self, *, keep_cursor: bool = False) -> None:
        self.digits = [None] * self.length
        if not keep_cursor:
            self.cursor = 0
        self.done = False
        self.result = None
        # Treat the next UP/DOWN as the first one again so the throttle
        # doesn't reject an immediate re-entry attempt after a reset.
        self._last_cycle_at_ms = -(10**9)

    # -- rendering ----------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        # Title bar.
        title_h = 30
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, title_h), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            title_h // 2,
            self.title,
            size=14,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        # Subtitle / helper lines under the title bar.
        y_meta = title_h + 12
        if self.subtitle_alert:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                y_meta,
                self.subtitle_alert,
                size=11,
                color=COLOR_DANGER,
                anchor="mm",
            )
            y_meta += 16
        if self.subtitle:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                y_meta,
                self.subtitle,
                size=11,
                color=self.subtitle_color,
                anchor="mm",
            )

        # Center the row of digit cells horizontally and vertically.
        row_width = (
            self.length * _CELL_WIDTH + max(0, self.length - 1) * _CELL_GAP
        )
        x0 = (DISPLAY_WIDTH - row_width) // 2
        y0 = (DISPLAY_HEIGHT - _CELL_HEIGHT) // 2 + 4

        for i in range(self.length):
            cell_x = x0 + i * (_CELL_WIDTH + _CELL_GAP)
            self._draw_cell(fb, i, cell_x, y0)

        # Footer hints.
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 30,
            "UP/DOWN digit   L/R cell",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 16,
            "A confirm   B clear digit",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )

    def _draw_cell(self, fb: FrameBuffer, idx: int, x: int, y: int) -> None:
        is_cursor = idx == self.cursor
        outline = COLOR_ACCENT if is_cursor else COLOR_DIM
        bg = (32, 38, 52) if is_cursor else (16, 16, 24)
        fb.draw.rectangle(
            (x, y, x + _CELL_WIDTH, y + _CELL_HEIGHT),
            fill=bg,
            outline=outline,
            width=2,
        )
        digit = self.digits[idx]
        if digit is None:
            glyph = "_"
            color = COLOR_DIM
        elif self.masked and not is_cursor:
            glyph = "*"
            color = COLOR_FG
        else:
            glyph = str(digit)
            color = COLOR_FG if not is_cursor else COLOR_ACCENT
        draw_text(
            fb,
            x + _CELL_WIDTH // 2,
            y + _CELL_HEIGHT // 2,
            glyph,
            size=22,
            color=color,
            anchor="mm",
        )


def attempts_subtitle(attempts_remaining: int) -> tuple[str, tuple[int, int, int]]:
    """Format an attempt-counter subtitle + colour for use in PIN unlock flows."""
    if attempts_remaining <= 0:
        return ("vault wiped", COLOR_DANGER)
    if attempts_remaining == 1:
        return ("1 attempt left - wipe on failure!", COLOR_DANGER)
    if attempts_remaining <= 3:
        return (f"{attempts_remaining} attempts left", COLOR_DANGER)
    return (f"{attempts_remaining} attempts left", COLOR_DIM)
