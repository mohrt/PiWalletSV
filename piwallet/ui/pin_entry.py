"""Bonnet PIN entry screen.

Reusable PIN entry widget used by unlock, first-boot setup, and change-PIN.
Cells start at :data:`PIN_MIN_LEN` (6) empty slots — the same footprint as
classic 6-digit vaults — and may grow to :data:`PIN_MAX_LEN` (16) when the
operator presses RIGHT on the last cell. UP/DOWN cycles the focused cell
through digits first, then letters; joystick center toggles letter case.

Backward compatibility
----------------------
Existing vaults encrypted with a 6-digit numeric PIN continue to unlock:
enter six digits and press A, same as before. Letters and extra cells are
opt-in for new / changed PINs.

Controls
--------
====== ======================================================
Input  Effect
====== ======================================================
UP     Cycle current cell forward (0-9, then a-z / A-Z).
DOWN   Cycle current cell backward.
LEFT   Move left only if the current cell is filled.
RIGHT  Move right / grow only if the current cell is filled
       (up to ``PIN_MAX_LEN``). Empty cells block horizontal move;
       use B to retreat.
SELECT Toggle upper / lower case for letter glyphs (and
       convert the current cell if it is a letter).
A      Confirm when every cell is filled and length ≥ 6;
       otherwise advance to the next empty cell.
B PRESS  Length == 6: clear the current cell (and step left
         if already empty). Length > 6: remove the current
         cell (shrink), floor at 6.
====== ======================================================

Empty slots render as ``_``. Filled slots show their character; if
``masked=True``, non-active filled slots render as ``*``.

A plain-text preview under the cells always shows the full PIN
(empty slots as ``_``) so long values stay readable when the cell
row is windowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from piwallet.core.vault import PIN_MAX_LEN, PIN_MIN_LEN
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    COLOR_OK,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import draw_text

# Digits first so classic numeric PINs match the old UP/DOWN feel.
_PIN_DIGITS: tuple[str, ...] = tuple("0123456789")
_PIN_LETTERS_LOWER: tuple[str, ...] = tuple("abcdefghijklmnopqrstuvwxyz")
_PIN_LETTERS_UPPER: tuple[str, ...] = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

_CELL_WIDTH = 30
_CELL_HEIGHT = 40
_CELL_GAP = 6

#: Minimum interval between glyph cycles when UP/DOWN is held.
_DIGIT_REPEAT_THROTTLE_MS: int = 320


def _glyphs(*, upper: bool) -> tuple[str, ...]:
    letters = _PIN_LETTERS_UPPER if upper else _PIN_LETTERS_LOWER
    return _PIN_DIGITS + letters


@dataclass
class PinEntryScreen:
    """Alphanumeric PIN entry. See module docstring for controls."""

    #: Initial / minimum slot count (classic vault PIN length).
    length: int = PIN_MIN_LEN
    #: Hard cap on growable slots.
    max_len: int = PIN_MAX_LEN
    title: str = "Enter PIN"
    subtitle: str = ""
    subtitle_color: tuple[int, int, int] = COLOR_DIM
    subtitle_alert: str = ""
    masked: bool = False
    cursor: int = 0
    done: bool = False
    result: object | None = None
    #: Per-slot glyph; ``None`` = empty. Prefer seeding via ``chars``.
    digits: list[str | None] = field(default_factory=list)
    upper: bool = False
    _last_cycle_at_ms: int = field(default=-(10**9), repr=False)

    def __post_init__(self) -> None:
        if self.length < PIN_MIN_LEN or self.length > self.max_len:
            raise ValueError(
                f"PIN length must be {PIN_MIN_LEN}..{self.max_len}, got {self.length}"
            )
        if self.max_len < PIN_MIN_LEN or self.max_len > PIN_MAX_LEN:
            raise ValueError(
                f"max_len must be {PIN_MIN_LEN}..{PIN_MAX_LEN}, got {self.max_len}"
            )
        if not self.digits:
            self.digits = [None] * self.length
        else:
            # Accept legacy int seeds from older callers/tests.
            normalized: list[str | None] = []
            for d in self.digits:
                if d is None:
                    normalized.append(None)
                elif isinstance(d, int):
                    if d < 0 or d > 9:
                        raise ValueError(f"digit seed out of range: {d}")
                    normalized.append(str(d))
                else:
                    ch = str(d)
                    if len(ch) != 1 or not ch.isalnum():
                        raise ValueError(f"invalid PIN char seed: {d!r}")
                    normalized.append(ch)
            self.digits = normalized
            if len(self.digits) < PIN_MIN_LEN or len(self.digits) > self.max_len:
                raise ValueError(
                    f"digits seed length must be {PIN_MIN_LEN}..{self.max_len}, "
                    f"got {len(self.digits)}"
                )
            self.length = len(self.digits)
        self.cursor = max(0, min(self.cursor, self.length - 1))

    # -- helpers ------------------------------------------------------

    def typed_text(self) -> str:
        """Full PIN string with empty slots as ``_`` (preview source of truth)."""
        return "".join("_" if c is None else c for c in self.digits)

    def pin_value(self) -> str | None:
        """Entered PIN if every cell is filled, else ``None``."""
        if any(c is None for c in self.digits):
            return None
        return "".join(self.digits)  # type: ignore[arg-type]

    def is_complete(self) -> bool:
        return (
            len(self.digits) >= PIN_MIN_LEN
            and all(c is not None for c in self.digits)
        )

    def _glyph_set(self) -> tuple[str, ...]:
        return _glyphs(upper=self.upper)

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
        elif b == Button.SELECT and k == EventKind.PRESS:
            self._toggle_case()
        elif b == Button.A and k == EventKind.PRESS:
            self._confirm_or_advance()
        elif b == Button.B and k == EventKind.PRESS:
            self._backspace()

    def _should_cycle(self, kind: EventKind, at_ms: int) -> bool:
        if kind == EventKind.PRESS:
            return True
        if kind != EventKind.REPEAT:
            return False
        return at_ms - self._last_cycle_at_ms >= _DIGIT_REPEAT_THROTTLE_MS

    def _cycle(self, delta: int) -> None:
        glyphs = self._glyph_set()
        cur = self.digits[self.cursor]
        if cur is None:
            # First press lands on '0' for both UP and DOWN (classic feel).
            self.digits[self.cursor] = glyphs[0]
            return
        # Map current char into the active glyph set (case-normalized).
        key = cur.upper() if cur.isalpha() and self.upper else (
            cur.lower() if cur.isalpha() and not self.upper else cur
        )
        if key not in glyphs:
            # Digit while viewing letters set, etc. — snap to first glyph.
            self.digits[self.cursor] = glyphs[0]
            return
        i = (glyphs.index(key) + delta) % len(glyphs)
        self.digits[self.cursor] = glyphs[i]

    def _toggle_case(self) -> None:
        self.upper = not self.upper
        cur = self.digits[self.cursor]
        if cur is not None and cur.isalpha():
            self.digits[self.cursor] = cur.upper() if self.upper else cur.lower()

    def _move_cursor(self, delta: int) -> None:
        # Require the current cell to be filled before moving or growing.
        # Backspace (B) is the way to retreat from an empty cell.
        if self.digits[self.cursor] is None:
            return
        new = self.cursor + delta
        if new < 0:
            return
        if new >= self.length:
            # Grow: RIGHT on the last *filled* cell appends an empty slot.
            if delta > 0 and self.cursor == self.length - 1 and self.length < self.max_len:
                self.digits.append(None)
                self.length = len(self.digits)
                self.cursor = self.length - 1
            return
        self.cursor = new

    def _confirm_or_advance(self) -> None:
        if self.is_complete():
            self.done = True
            self.result = self.pin_value()
            return
        for i in range(self.cursor + 1, self.length):
            if self.digits[i] is None:
                self.cursor = i
                return
        for i in range(0, self.cursor):
            if self.digits[i] is None:
                self.cursor = i
                return

    def _backspace(self) -> None:
        if self.length > PIN_MIN_LEN:
            # Shrink: remove the current cell, floor at PIN_MIN_LEN.
            del self.digits[self.cursor]
            self.length = len(self.digits)
            if self.cursor >= self.length:
                self.cursor = self.length - 1
            return
        # At minimum length: clear in place (classic behaviour).
        if self.digits[self.cursor] is not None:
            self.digits[self.cursor] = None
        elif self.cursor > 0:
            self.cursor -= 1
            self.digits[self.cursor] = None

    def reset(self, *, keep_cursor: bool = False) -> None:
        self.digits = [None] * PIN_MIN_LEN
        self.length = PIN_MIN_LEN
        if not keep_cursor:
            self.cursor = 0
        else:
            self.cursor = min(self.cursor, self.length - 1)
        self.done = False
        self.result = None
        self.upper = False
        self._last_cycle_at_ms = -(10**9)

    # -- rendering ----------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        title_h = 28
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

        y_meta = title_h + 10
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
            y_meta += 14
        meta_bits = []
        if self.subtitle:
            meta_bits.append(self.subtitle)
        case_hint = "ABC" if self.upper else "abc"
        meta_bits.append(f"{self.length}/{self.max_len}  {case_hint}")
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            y_meta,
            "  ·  ".join(meta_bits),
            size=10,
            color=self.subtitle_color if self.subtitle else COLOR_DIM,
            anchor="mm",
        )

        # ---- cell row (windowed when long) ---------------------------------
        n = self.length
        row_width = n * _CELL_WIDTH + max(0, n - 1) * _CELL_GAP
        max_row = DISPLAY_WIDTH - 8
        y0 = 78
        if row_width <= max_row:
            visible = list(range(n))
            x0 = (DISPLAY_WIDTH - row_width) // 2
        else:
            visible, x0 = self._visible_window(max_row)

        x = x0
        for i in visible:
            self._draw_cell(fb, i, x, y0)
            x += _CELL_WIDTH + _CELL_GAP

        # ---- preview (full PIN, empty as _) --------------------------------
        preview = self.typed_text()
        if self.masked:
            preview = "".join("*" if c != "_" else "_" for c in preview)
        pv = preview
        if len(pv) > 34:
            # Keep ends visible for long PINs.
            pv = pv[:15] + "…" + pv[-15:]
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            148,
            pv,
            size=12,
            color=COLOR_OK if self.is_complete() else COLOR_DIM,
            anchor="mm",
        )

        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 30,
            "UP/DWN char  L/R cell  ● case",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 14,
            "A confirm   B backspace",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )

    def _visible_window(self, max_row: int) -> tuple[list[int], int]:
        """Indices + start_x so the cursor cell stays on-screen."""
        n = self.length
        cur = self.cursor
        first = cur
        last = cur

        def width(lo: int, hi: int) -> int:
            count = hi - lo + 1
            return count * _CELL_WIDTH + max(0, count - 1) * _CELL_GAP

        while True:
            grew = False
            if last + 1 < n and width(first, last + 1) <= max_row:
                last += 1
                grew = True
            if first - 1 >= 0 and width(first - 1, last) <= max_row:
                first -= 1
                grew = True
            if not grew:
                break
        return list(range(first, last + 1)), 4

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
        ch = self.digits[idx]
        if ch is None:
            glyph = "_"
            color = COLOR_DIM
        elif self.masked and not is_cursor:
            glyph = "*"
            color = COLOR_FG
        else:
            glyph = ch
            color = COLOR_FG if not is_cursor else COLOR_ACCENT
        size = 18 if (ch is not None and ch.isalpha()) else 22
        draw_text(
            fb,
            x + _CELL_WIDTH // 2,
            y + _CELL_HEIGHT // 2,
            glyph,
            size=size,
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
