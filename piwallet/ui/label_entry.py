"""Bonnet wallet label (name) editor.

Single-phase editor: the user types the name letter by letter and either
saves with **A** or cancels with **hold B**. There is no follow-on
confirm screen — the manage flow already gates destructive actions
elsewhere (delete uses :class:`piwallet.ui.double_confirm.DoubleConfirmScreen`),
and renaming is recoverable, so a single A press commits.

Controls
--------
==========  ================================================================
UP/DOWN     Cycle the letter at the cursor inside the fixed glyph set
            (wraps). When the cursor is on the trailing "new slot" past
            the last letter, UP/DOWN auto-appends a new letter and cycles
            it (subject to ``max_len``).
LEFT        Move cursor one slot left (clamped at 0).
RIGHT       Move cursor one slot right; can land on a "new slot" past the
            last letter so the user can grow the name. ``max_len`` blocks
            growth past the cap (cursor capped at last letter when the
            buffer is already full).
B PRESS     Delete the letter currently under the cursor. Cursor stays
            in place; if the deleted letter was the last one, the cursor
            decrements to the new last letter. When the cursor sits on
            the trailing "new slot", B deletes the last letter (matching
            a typical text-editor "Delete" key at end-of-string). The
            buffer is never allowed to drop below one letter.
B LONG      Cancel/skip the editor entirely (result = None). Callers
            interpret this as "use the suggested default" (create flow)
            or "abort the rename" (rename flow).
A / SELECT  Save the typed name (result = stripped buffer). Blocked when
            the name is blank after stripping.
==========  ================================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
from piwallet.ui.widgets import draw_text, text_bbox

#: Allowed glyphs (in UP/DOWN cycle order). Lowercase only — the bonnet
#: knob is too coarse for case hunting on a 1.3" panel.
_LABEL_GLYPHS: tuple[str, ...] = (
    " ",
    *tuple("abcdefghijklmnopqrstuvwxyz"),
    *tuple("0123456789"),
    "-",
    "_",
)

_LABEL_POS: dict[str, int] = {c: i for i, c in enumerate(_LABEL_GLYPHS)}

LABEL_MAX_CHARS: int = 24


def _sanitize_visible(s: str, *, maxlen: int) -> str:
    """Keep allowed glyphs only, lowercase, clamp length."""
    return "".join(c for c in s.lower() if c in _LABEL_POS)[:maxlen]


def _glyph_text(c: str) -> str:
    """Visual representation of a glyph (space rendered as underscore)."""
    return "_" if c == " " else c


@dataclass
class WalletLabelEntryScreen:
    """Edit a printable wallet ``label``. See module docstring for the model."""

    title: str = "Name wallet"
    max_len: int = LABEL_MAX_CHARS
    suggested_default: str = ""
    done: bool = False
    result: str | None = None
    transient_error: str | None = None

    buffer: list[str] = field(default_factory=list)
    cursor: int = 0

    # -- construction -------------------------------------------------

    def __post_init__(self) -> None:
        if self.max_len < 1:
            raise ValueError("max_len must be positive")
        sug = _sanitize_visible(self.suggested_default, maxlen=self.max_len)
        if sug:
            self.buffer = list(sug)
            # Land cursor on the last letter so the user can extend with R
            # or edit the last char in place.
            self.cursor = len(self.buffer) - 1
        else:
            self.buffer = ["a"]
            self.cursor = 0

    # -- helpers ------------------------------------------------------

    def typed_text(self) -> str:
        """The full label currently in the buffer (no cursor effect)."""
        return "".join(self.buffer)

    def _on_new_slot(self) -> bool:
        return self.cursor == len(self.buffer)

    def _can_grow(self) -> bool:
        return len(self.buffer) < self.max_len

    # -- edit-phase mutators -----------------------------------------

    def _cycle(self, delta: int) -> None:
        self.transient_error = None
        if self._on_new_slot():
            if not self._can_grow():
                self.transient_error = "Max length reached"
                return
            # Materialise a new letter starting at the first glyph.
            new_glyph = _LABEL_GLYPHS[0]
            self.buffer.append(new_glyph)
        i = (_LABEL_POS[self.buffer[self.cursor]] + delta) % len(_LABEL_GLYPHS)
        self.buffer[self.cursor] = _LABEL_GLYPHS[i]

    def _move_cursor(self, delta: int) -> None:
        self.transient_error = None
        new = self.cursor + delta
        if new < 0:
            return
        # Allow cursor to land on the "new slot" (one past the last letter)
        # only while there's room to grow. When the buffer is at max_len we
        # cap the cursor at the last letter.
        max_cursor = len(self.buffer) if self._can_grow() else len(self.buffer) - 1
        if new > max_cursor:
            return
        self.cursor = new

    def _backspace(self) -> None:
        """Delete the letter currently under the cursor.

        Behaviour summary:

        * cursor on an existing letter -> remove that letter; the next
          letter (if any) slides into its place under the cursor.
        * cursor on the trailing "new slot" -> remove the last letter
          (typical "Delete at end of line" behaviour).
        * buffer of length 1 -> no-op (the editor always keeps at least
          one letter so the user can cycle a glyph at it).
        """
        self.transient_error = None
        if self._on_new_slot():
            target = self.cursor - 1
        else:
            target = self.cursor
        if target < 0:
            return
        if len(self.buffer) <= 1:
            return
        del self.buffer[target]
        # Always land the cursor on a real letter after delete; the user
        # can press RIGHT to reach the trailing "new slot" again.
        if self.cursor >= len(self.buffer):
            self.cursor = len(self.buffer) - 1

    def _try_save(self) -> None:
        """Commit the typed name (A / SELECT) when not blank."""
        name = "".join(self.buffer).strip()
        if not name:
            self.transient_error = "Can't be blank"
            return
        self.transient_error = None
        self.done = True
        self.result = name

    # -- driver -------------------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.UP and k in (EventKind.PRESS, EventKind.REPEAT):
            self._cycle(-1)
        elif b == Button.DOWN and k in (EventKind.PRESS, EventKind.REPEAT):
            self._cycle(+1)
        elif b == Button.LEFT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._move_cursor(-1)
        elif b == Button.RIGHT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._move_cursor(+1)
        elif b == Button.B and k == EventKind.PRESS:
            self._backspace()
        elif b == Button.B and k == EventKind.LONG:
            self.done = True
            self.result = None
        elif b in (Button.A, Button.SELECT) and k == EventKind.PRESS:
            self._try_save()

    # -- rendering ----------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        self._draw_edit(fb)

    def _draw_edit(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, 26), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            13,
            self.title,
            size=14,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        nchars = len(self.buffer)
        usage = (
            "hold B skip = default" if self.suggested_default else "hold B cancel"
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            36,
            f"{nchars}/{self.max_len} chars  {usage}",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )

        # ---- letter row ----------------------------------------------------
        # Layout: render each buffer letter in sequence with a small gap;
        # box the cursor letter. If cursor is on the new slot, draw an empty
        # box at the end of the row.
        fz = 18
        gap_px = 4
        pad_x, pad_y = 4, 4
        text_y = 84

        char_widths: list[int] = []
        for c in self.buffer:
            bb = text_bbox(_glyph_text(c), size=fz)
            char_widths.append(max(bb[2] - bb[0], 8))
        new_slot_w = max(text_bbox("a", size=fz)[2] - text_bbox("a", size=fz)[0], 8)

        slots: list[int] = list(char_widths)
        if self._on_new_slot():
            slots.append(new_slot_w)

        cluster_w = sum(w + 2 * pad_x for w in slots) + gap_px * max(0, len(slots) - 1)
        max_cluster_w = DISPLAY_WIDTH - 8
        # Center horizontally, but if the row overflows the display, anchor
        # the row so the cursor stays visible (windowed view).
        if cluster_w <= max_cluster_w:
            start_x = (DISPLAY_WIDTH - cluster_w) // 2
            visible_slice = list(range(len(slots)))
        else:
            visible_slice, start_x = self._compute_visible_window(
                slots, char_widths, pad_x, gap_px, max_cluster_w
            )

        x = start_x
        for slot_idx in visible_slice:
            slot_w = slots[slot_idx] + 2 * pad_x
            box_h = max(text_bbox("M", size=fz)[3] - text_bbox("M", size=fz)[1], 18) + 2 * pad_y
            top = text_y - box_h // 2
            is_cursor = slot_idx == self.cursor
            is_new = slot_idx == len(self.buffer)  # only true if on new slot
            outline = COLOR_ACCENT if is_cursor else None
            fill = (28, 32, 48) if is_cursor else COLOR_BG
            if is_cursor:
                fb.draw.rectangle((x, top, x + slot_w, top + box_h), outline=outline,
                                  width=2, fill=fill)
            if not is_new:
                ch = self.buffer[slot_idx]
                draw_text(
                    fb,
                    x + slot_w // 2,
                    text_y,
                    _glyph_text(ch),
                    size=fz,
                    color=COLOR_ACCENT if is_cursor else COLOR_FG,
                    anchor="mm",
                )
            else:
                draw_text(
                    fb,
                    x + slot_w // 2,
                    text_y,
                    "·",
                    size=fz,
                    color=COLOR_DIM,
                    anchor="mm",
                )
            x += slot_w + gap_px

        # ---- preview line --------------------------------------------------
        preview_y = 138
        line = self.typed_text()
        pv = "".join("_" if c == " " else c for c in line)
        if len(pv) > 34:
            pv = pv[:31] + "..."
        preview_color = COLOR_OK if line.strip() else COLOR_DIM
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            preview_y,
            pv or "",
            size=12,
            color=preview_color,
            anchor="mm",
        )

        if self.transient_error:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                162,
                self.transient_error,
                size=11,
                color=COLOR_DANGER,
                anchor="mm",
            )

        # ---- footer hints --------------------------------------------------
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 28,
            "UP/DWN letter   L/R move",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 12,
            "A OK   B DEL   hold B X",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )

    def _compute_visible_window(
        self,
        slots: list[int],
        char_widths: list[int],
        pad_x: int,
        gap_px: int,
        max_cluster_w: int,
    ) -> tuple[list[int], int]:
        """Pick a contiguous slice of ``slots`` that fits ``max_cluster_w``
        and contains the cursor. Returns (slice indices, start_x)."""
        # Start with cursor; expand outward while we have room.
        n = len(slots)
        cur = max(0, min(self.cursor, n - 1))
        first = cur
        last = cur

        def slice_width(lo: int, hi: int) -> int:
            ws = [slots[i] + 2 * pad_x for i in range(lo, hi + 1)]
            return sum(ws) + gap_px * max(0, len(ws) - 1)

        while True:
            grew = False
            if last + 1 < n and slice_width(first, last + 1) <= max_cluster_w:
                last += 1
                grew = True
            if first - 1 >= 0 and slice_width(first - 1, last) <= max_cluster_w:
                first -= 1
                grew = True
            if not grew:
                break

        start_x = (DISPLAY_WIDTH - slice_width(first, last)) // 2
        return list(range(first, last + 1)), start_x
