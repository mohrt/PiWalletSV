"""Touch controls: an icon grid and an on-screen alphabet keyboard.

The Waveshare 3.5 inch LCD (F) is portrait, 320×480, so the wallet
list can show more rows. The older LCD (A) is 480×320. There is no
joystick. Every control is a rectangle the finger hits.
"""

from __future__ import annotations

from dataclasses import dataclass

from piwallet.core.mnemonic import BIP39_WORDLIST, words_starting_with
from piwallet.core.vault import WalletRecord
from piwallet.touch.input import Tap
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    COLOR_OK,
    FrameBuffer,
)
from piwallet.ui.widgets import draw_text, font, text_bbox

_WORD_SET = frozenset(BIP39_WORDLIST)

_HOME_ACTIONS: tuple[tuple[str, str], ...] = (
    ("wallets", "Wallets"),
    ("new", "New"),
    ("restore", "Restore"),
    ("settings", "Settings"),
)

_LETTER_ROWS: tuple[str, ...] = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_NAME_ROWS: tuple[str, ...] = ("1234567890",) + _LETTER_ROWS
_CANCEL_BOX = (112, 28)
# Text choices stay a finger-sized row. The rest of a tall panel is left
# open for help text instead of stretching one row to the bottom edge.
_CHOICE_BUTTON_H = 56


@dataclass(frozen=True, slots=True)
class Hit:
    id: str
    x0: int
    y0: int
    x1: int
    y1: int

    def contains(self, x: int, y: int) -> bool:
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1

    def center(self) -> tuple[int, int]:
        return ((self.x0 + self.x1) // 2, (self.y0 + self.y1) // 2)


class IconGrid:
    """Tappable action tiles. ``on_tap`` returns the action id on a press."""

    def __init__(
        self,
        width: int,
        height: int,
        actions: tuple[tuple[str, str], ...] = _HOME_ACTIONS,
        *,
        title: str = "Pi Wallet",
        show_icons: bool = True,
        top: int = 36,
    ) -> None:
        self.width = width
        self.height = height
        self.actions = actions
        self.title = title
        self.show_icons = show_icons
        self.top = top
        self.status = ""
        self.down: str | None = None
        self._hits = self._layout()

    def _tiles(self) -> tuple[tuple[str, str], ...]:
        return tuple(item for item in self.actions if item[0] != "cancel")

    def _cancel_hit(self) -> Hit | None:
        if not any(action_id == "cancel" for action_id, _label in self.actions):
            return None
        w, h = _CANCEL_BOX
        return Hit("cancel", self.width - 8 - w, 4, self.width - 8, 4 + h)

    def _layout(self) -> list[Hit]:
        tiles = self._tiles()
        cols = 2 if len(tiles) <= 4 else 3
        rows = (len(tiles) + cols - 1) // cols
        top = self.top
        gap = 8
        cell_w = (self.width - gap * (cols + 1)) // cols
        cell_h = (self.height - top - gap * (rows + 1)) // max(1, rows)
        if not self.show_icons:
            cell_h = min(cell_h, _CHOICE_BUTTON_H)
        hits: list[Hit] = []
        for i, (action_id, _label) in enumerate(tiles):
            col = i % cols
            row = i // cols
            x0 = gap + col * (cell_w + gap)
            y0 = top + gap + row * (cell_h + gap)
            hits.append(Hit(action_id, x0, y0, x0 + cell_w, y0 + cell_h))
        cancel = self._cancel_hit()
        if cancel is not None:
            hits.append(cancel)
        return hits

    def hit(self, action_id: str) -> Hit:
        for item in self._hits:
            if item.id == action_id:
                return item
        raise KeyError(action_id)

    def _at(self, x: int, y: int) -> str | None:
        for item in self._hits:
            if item.contains(x, y):
                return item.id
        return None

    def on_tap(self, tap: Tap) -> str | None:
        if tap.pressed:
            self.down = self._at(tap.x, tap.y)
            return None
        chosen = self.down
        self.down = None
        if chosen is not None and chosen == self._at(tap.x, tap.y):
            return chosen
        return None

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, self.title, size=18, color=COLOR_FG)
        if self.status:
            draw_text(fb, 140, 10, self.status, size=14, color=COLOR_DIM)
        labels = dict(self.actions)
        for item in self._hits:
            held = item.id == self.down
            fb.draw.rounded_rectangle(
                (item.x0, item.y0, item.x1 - 1, item.y1 - 1),
                radius=8,
                fill=COLOR_ACCENT if held else (24, 24, 24),
                outline=COLOR_FG if held else COLOR_ACCENT,
                width=3 if held else 2,
            )
            label = labels[item.id]
            cx, cy = item.center()
            ink = COLOR_BG if held else COLOR_FG
            if item.id == "cancel":
                draw_text(fb, cx, cy, label, size=16, color=ink, anchor="mm")
                continue
            if self.show_icons:
                mark = COLOR_BG if held else COLOR_ACCENT
                _draw_icon(fb.draw, item.id, cx, cy - 18, mark)
                draw_text(fb, cx, cy + 28, label, size=16, color=ink, anchor="mm")
            else:
                draw_text(fb, cx, cy, label, size=16, color=ink, anchor="mm")


def _text_width(text: str, size: int) -> int:
    left, _top, right, _bottom = text_bbox(text, size=size)
    return right - left


def _fit_text(text: str, px: int, size: int) -> str:
    if _text_width(text, size) <= px:
        return text
    trimmed = text
    while trimmed and _text_width(trimmed + "...", size) > px:
        trimmed = trimmed[:-1]
    return (trimmed + "...") if trimmed else ""


def _draw_icon(
    draw,
    action_id: str,
    cx: int,
    cy: int,
    color: tuple[int, int, int] = COLOR_ACCENT,
    *,
    scale: float = 1.0,
) -> None:
    """Stroke icon centered on ``(cx, cy)``. Full size is about 32px tall."""

    def p(n: float) -> int:
        return int(round(n * scale))

    stroke = max(1, p(3))
    if action_id == "wallets":
        draw.rounded_rectangle((cx - p(16), cy - p(4), cx + p(8), cy + p(16)), radius=p(3), outline=color, width=stroke)
        draw.rounded_rectangle((cx - p(8), cy - p(16), cx + p(16), cy + p(4)), radius=p(3), outline=color, width=stroke)
    elif action_id == "receive":
        draw.line((cx, cy - p(16), cx, cy + p(2)), fill=color, width=stroke)
        draw.polygon([(cx - p(9), cy - p(2)), (cx + p(9), cy - p(2)), (cx, cy + p(12))], fill=color)
        draw.line((cx - p(14), cy + p(16), cx + p(14), cy + p(16)), fill=color, width=stroke)
    elif action_id == "send":
        draw.line((cx, cy + p(16), cx, cy - p(2)), fill=color, width=stroke)
        draw.polygon([(cx - p(9), cy + p(2)), (cx + p(9), cy + p(2)), (cx, cy - p(12))], fill=color)
        draw.line((cx - p(14), cy - p(16), cx + p(14), cy - p(16)), fill=color, width=stroke)
    elif action_id == "new":
        draw.line((cx - p(14), cy, cx + p(14), cy), fill=color, width=max(2, p(4)))
        draw.line((cx, cy - p(14), cx, cy + p(14)), fill=color, width=max(2, p(4)))
    elif action_id == "restore":
        draw.arc((cx - p(16), cy - p(16), cx + p(16), cy + p(16)), start=30, end=300, fill=color, width=stroke)
        draw.polygon([(cx + p(8), cy - p(18)), (cx + p(18), cy - p(8)), (cx + p(4), cy - p(6))], fill=color)
    elif action_id == "settings":
        for index, yoff in enumerate((-12, 0, 12)):
            y = cy + p(yoff)
            draw.line((cx - p(16), y, cx + p(16), y), fill=color, width=stroke)
            knob = cx + p(-8 + index * 8)
            draw.ellipse((knob - p(4), y - p(4), knob + p(4), y + p(4)), fill=color)
    else:
        draw.ellipse((cx - p(8), cy - p(8), cx + p(8), cy + p(8)), outline=color, width=stroke)


def _draw_left_arrow(draw, cx: int, cy: int, color: tuple[int, int, int]) -> None:
    """Header back control: a left-pointing arrow."""
    draw.line((cx + 7, cy, cx - 5, cy), fill=color, width=2)
    draw.line((cx - 5, cy, cx + 1, cy - 6), fill=color, width=2)
    draw.line((cx - 5, cy, cx + 1, cy + 6), fill=color, width=2)


def _draw_delete_mark(draw, cx: int, cy: int, color: tuple[int, int, int]) -> None:
    """iPhone erase key: a left-pointing outline with an × inside."""
    x0, x1 = cx - 13, cx + 13
    y0, y1 = cy - 9, cy + 9
    body = x0 + 8
    stroke = 2
    pts = ((x0, cy), (body, y0), (x1, y0), (x1, y1), (body, y1))
    for start, end in zip(pts, pts[1:] + pts[:1]):
        draw.line((*start, *end), fill=color, width=stroke)
    left, right = body + 4, x1 - 4
    draw.line((left, cy - 4, right, cy + 4), fill=color, width=stroke)
    draw.line((left, cy + 4, right, cy - 4), fill=color, width=stroke)


class WalletHome:
    """Unlocked home: Add, Restore, and Settings across the top, then a
    Wallets heading over the list."""

    _heading_y = 48
    # Leaves eight rows on the 320×480 panel without a scrollbar.
    _list_top = 76
    _row_h = 48
    _bar_w = 16

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.wallets: list[WalletRecord] = []
        self.down: str | None = None
        self.message = ""
        self._scroll = 0
        self._dragged = False
        self._on_scrollbar = False
        self._press_id: str | None = None

    def set_wallets(self, wallets: list[WalletRecord]) -> None:
        self.wallets = list(wallets)
        self._scroll = min(self._scroll, self._max_scroll())

    def _visible(self) -> int:
        return max(1, (self.height - self._list_top - 8) // self._row_h)

    def _max_scroll(self) -> int:
        return max(0, len(self.wallets) - self._visible())

    def _bar_box(self) -> tuple[int, int, int, int] | None:
        if self._max_scroll() == 0:
            return None
        return (self.width - 8 - self._bar_w, self._list_top, self.width - 8, self.height - 8)

    def hit(self, action_id: str) -> Hit:
        for item in self._hits():
            if item.id == action_id:
                return item
        raise KeyError(action_id)

    def _hits(self) -> list[Hit]:
        hits: list[Hit] = []
        gap = 8
        actions = ("add", "restore", "settings")
        cell_w = (self.width - gap * (len(actions) + 1)) // len(actions)
        for i, action_id in enumerate(actions):
            x0 = gap + i * (cell_w + gap)
            hits.append(Hit(action_id, x0, 6, x0 + cell_w, 40))
        right = self.width - gap
        if self._bar_box() is not None:
            right = self.width - 12 - self._bar_w
        y0 = self._list_top
        window = self.wallets[self._scroll : self._scroll + self._visible()]
        for wallet in window:
            hits.append(Hit(wallet.id, gap, y0, right, y0 + self._row_h - 6))
            y0 += self._row_h
        return hits

    def _at(self, x: int, y: int) -> str | None:
        for item in self._hits():
            if item.contains(x, y):
                return item.id
        return None

    def on_tap(self, tap: Tap) -> str | None:
        if tap.pressed:
            if not self._dragged and self.down is None:
                self._press_id = self._at(tap.x, tap.y)
                self._on_scrollbar = self._on_bar(tap.x, tap.y)
            if self._on_scrollbar:
                self._dragged = True
                self.down = None
                self._scroll_to(tap.y)
            elif self._press_id in ("add", "restore", "settings"):
                self.down = self._press_id
            else:
                self.down = self._at(tap.x, tap.y)
            return None
        chosen = self.down
        self.down = None
        dragged = self._dragged
        self._dragged = False
        self._on_scrollbar = False
        press_id = self._press_id
        self._press_id = None
        if dragged:
            return None
        if press_id in ("add", "restore", "settings") and self._near(press_id, tap.x, tap.y):
            return press_id
        if chosen is not None and chosen == self._at(tap.x, tap.y):
            return chosen
        return None

    def _near(self, action_id: str, x: int, y: int) -> bool:
        box = self.hit(action_id)
        return box.x0 - 24 <= x < box.x1 + 24 and box.y0 - 16 <= y < box.y1 + 28

    def _on_bar(self, x: int, y: int) -> bool:
        box = self._bar_box()
        if box is None:
            return False
        x0, y0, x1, y1 = box
        return x0 <= x < x1 and y0 <= y < y1

    def _scroll_to(self, y: int) -> None:
        limit = self._max_scroll()
        if limit == 0:
            self._scroll = 0
            return
        track_h = max(1, self.height - 8 - self._list_top)
        frac = (y - self._list_top) / track_h
        self._scroll = max(0, min(limit, round(frac * limit)))

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        labels = {"add": "Add", "restore": "Restore", "settings": "Settings"}
        names = {w.id: f"{w.label}  {w.fingerprint.hex()[:8]}" for w in self.wallets}
        draw_text(fb, 12, self._heading_y, "Wallets", size=18, color=COLOR_FG)
        for item in self._hits():
            held = item.id == self.down
            fb.draw.rounded_rectangle(
                (item.x0, item.y0, item.x1 - 1, item.y1 - 1),
                radius=8,
                fill=COLOR_ACCENT if held else (24, 24, 24),
                outline=COLOR_FG if held else COLOR_ACCENT,
                width=3 if held else 2,
            )
            cx, cy = item.center()
            ink = COLOR_BG if held else COLOR_FG
            if item.id in labels:
                mark = COLOR_BG if held else COLOR_ACCENT
                _draw_icon(
                    fb.draw,
                    "new" if item.id == "add" else item.id,
                    item.x0 + 18,
                    cy,
                    mark,
                    scale=0.45,
                )
                draw_text(fb, cx + 12, cy, labels[item.id], size=16, color=ink, anchor="mm")
            elif self.width < 400:
                self._draw_portrait_row(fb, item, ink)
            else:
                draw_text(fb, item.x0 + 12, cy, names.get(item.id, item.id), size=16, color=ink, anchor="lm")
                wallet = next((w for w in self.wallets if w.id == item.id), None)
                net = "testnet" if wallet is not None and wallet.network == "test" else "mainnet"
                draw_text(fb, item.x1 - 12, cy, net, size=14, color=ink, anchor="rm")
        if not self.wallets:
            empty_y = (self._list_top + self.height) // 2 if self.height > self.width else 140
            draw_text(fb, self.width // 2, empty_y, "No wallets", size=18, color=COLOR_DIM, anchor="mm")
        box = self._bar_box()
        if box is not None:
            x0, y0, x1, y1 = box
            fb.draw.rectangle((x0, y0, x1, y1), fill=(40, 40, 48))
            track_h = y1 - y0
            thumb_h = max(24, track_h * self._visible() // len(self.wallets))
            span = max(1, track_h - thumb_h)
            thumb_y = y0 + span * self._scroll // self._max_scroll()
            fb.draw.rectangle((x0, thumb_y, x1, thumb_y + thumb_h), fill=COLOR_ACCENT)
        if self.message:
            draw_text(fb, 12, self.height - 18, self.message, size=14, color=COLOR_DIM)

    def _draw_portrait_row(self, fb: FrameBuffer, item: Hit, ink: tuple[int, int, int]) -> None:
        """Name on the first line, fingerprint and network under it.

        A 320-wide row cannot hold a long name, an 8-character
        fingerprint, and "testnet" on one baseline.
        """
        wallet = next((w for w in self.wallets if w.id == item.id), None)
        _cx, cy = item.center()
        label = wallet.label if wallet is not None else item.id
        draw_text(
            fb,
            item.x0 + 12,
            cy - 9,
            _fit_text(label, item.x1 - item.x0 - 24, 16),
            size=16,
            color=ink,
            anchor="lm",
        )
        if wallet is None:
            return
        meta = COLOR_BG if ink == COLOR_BG else COLOR_DIM
        net = "testnet" if wallet.network == "test" else "mainnet"
        draw_text(fb, item.x0 + 12, cy + 9, wallet.fingerprint.hex()[:8], size=14, color=meta, anchor="lm")
        draw_text(fb, item.x1 - 12, cy + 9, net, size=14, color=ink, anchor="rm")


class AlphabetKeyboard:
    """Full alphabet for a BIP39 word or a free-text name.

    Letter keys append. A matching BIP39 word in the suggestion strip
    can be tapped to accept it. Backspace deletes. OK accepts the
    current text when it is a real word (word mode) or any non-empty
    name (name mode). Cancel returns None.
    """

    def __init__(
        self,
        width: int,
        height: int,
        *,
        mode: str,
        title: str,
        word_back: bool = False,
    ) -> None:
        if mode not in ("word", "name"):
            raise ValueError(mode)
        self.width = width
        self.height = height
        self.mode = mode
        self.title = title
        self.word_back = word_back
        self.text = ""
        self.message = ""
        self.done = False
        self.result: str | None = None
        self.went_back = False
        self.down: str | None = None
        self._hits = self._layout()

    def _rows(self) -> tuple[str, ...]:
        return _LETTER_ROWS if self.mode == "word" else _NAME_ROWS

    def _key_geom(self) -> tuple[int, int, int]:
        key_top = 84
        gap = 3
        rows = len(self._rows()) + (2 if self.mode == "name" else 1)
        available = self.height - key_top - 8
        row_h = (available - gap * (rows - 1)) // rows
        return key_top, max(28, min(row_h, 48)), gap

    def _layout(self) -> list[Hit]:
        hits: list[Hit] = []
        key_top, row_h, gap = self._key_geom()
        rows = self._rows()
        # One key size for every letter. Shorter rows are centered instead
        # of stretching each key to fill the width.
        longest = max(len(row) for row in rows)
        key_w = (self.width - gap * (longest + 1)) // longest
        for row_i, letters in enumerate(rows):
            row_span = len(letters) * key_w + gap * (len(letters) - 1)
            x_start = (self.width - row_span) // 2
            y0 = key_top + row_i * (row_h + gap)
            for col, ch in enumerate(letters):
                x0 = x_start + col * (key_w + gap)
                hits.append(Hit(ch, x0, y0, x0 + key_w, y0 + row_h))
        bar_y = key_top + len(rows) * (row_h + gap)
        if self.mode == "name":
            y0 = bar_y
            side = key_w
            hits.append(Hit("-", gap, y0, gap + side, y0 + row_h))
            hits.append(Hit(" ", gap + side + gap, y0, self.width - gap - side - gap, y0 + row_h))
            hits.append(Hit("_", self.width - gap - side, y0, self.width - gap, y0 + row_h))
            bar_y = y0 + row_h + gap
        half = (self.width - gap * 3) // 2
        hits.append(Hit("back", gap, bar_y, gap + half, bar_y + row_h))
        hits.append(Hit("ok", gap * 2 + half, bar_y, self.width - gap, bar_y + row_h))
        w, h = _CANCEL_BOX
        cancel_x0 = self.width - 8 - w
        hits.append(Hit("cancel", cancel_x0, 4, self.width - 8, 4 + h))
        if self.word_back:
            arrow_w = 40
            gap_x = 6
            hits.append(Hit("prev", cancel_x0 - gap_x - arrow_w, 4, cancel_x0 - gap_x, 4 + h))
        return hits

    def hit(self, key_id: str) -> Hit:
        for item in self._hits:
            if item.id == key_id:
                return item
        raise KeyError(key_id)

    def suggestions(self) -> list[str]:
        if self.mode != "word" or not self.text:
            return []
        return words_starting_with(self.text)[:4]

    def _suggestion_boxes(self) -> list[tuple[int, int, int, int, str]]:
        words = self.suggestions()
        if not words:
            return []
        gap = 6
        left = 8
        usable = self.width - left * 2
        chip_w = (usable - gap * (len(words) - 1)) // len(words)
        boxes: list[tuple[int, int, int, int, str]] = []
        x = left
        for word in words:
            boxes.append((x, 54, x + chip_w, 80, word))
            x += chip_w + gap
        return boxes

    def _at(self, x: int, y: int) -> str | None:
        for x0, y0, x1, y1, word in self._suggestion_boxes():
            if x0 <= x < x1 and y0 <= y < y1:
                return f"suggest:{word}"
        for item in self._hits:
            if item.contains(x, y):
                return item.id
        return None

    def on_tap(self, tap: Tap) -> None:
        if self.done:
            return
        if tap.pressed:
            self.down = self._at(tap.x, tap.y)
            return
        chosen = self.down
        self.down = None
        if chosen is None or chosen != self._at(tap.x, tap.y):
            return
        if chosen.startswith("suggest:"):
            self._accept(chosen.removeprefix("suggest:"))
            return
        if chosen == "prev":
            self.done = True
            self.result = None
            self.went_back = True
        elif chosen == "back":
            self.text = self.text[:-1]
            self.message = ""
        elif chosen == "cancel":
            self.done = True
            self.result = None
        elif chosen == "ok":
            self._try_ok()
        elif len(chosen) == 1:
            self.text += chosen
            self.message = ""

    def _try_ok(self) -> None:
        if self.mode == "word":
            if self.text in _WORD_SET:
                self._accept(self.text)
            return
        name = self.text.strip()
        if not name:
            self.message = "Enter a name"
            return
        self._accept(name)

    def _accept(self, value: str) -> None:
        self.text = value
        self.done = True
        self.result = value

    def _draw_cursor(self, fb: FrameBuffer, x: int, y: int) -> None:
        # textlength, not bbox, so a trailing space moves the cursor.
        end = x + int(fb.draw.textlength(self.text, font=font(18)))
        cx = min(end + 2, self.width - 4)
        fb.draw.rectangle((cx, y + 2, cx + 1, y + 21), fill=COLOR_ACCENT)

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 8, 6, self.title, size=16, color=COLOR_FG)
        if self.mode == "name":
            draw_text(fb, 8, 26, self.text, size=18, color=COLOR_FG)
            self._draw_cursor(fb, 8, 26)
        else:
            shown = self.text or "—"
            color = COLOR_OK if self.text in _WORD_SET else COLOR_FG
            draw_text(fb, 8, 26, shown, size=18, color=color)
        if self.mode == "name" and self.message:
            draw_text(fb, 8, 48, self.message, size=14, color=COLOR_DANGER)
        for x0, y0, x1, y1, word in self._suggestion_boxes():
            held = self.down == f"suggest:{word}"
            fb.draw.rounded_rectangle(
                (x0, y0, x1 - 1, y1 - 1),
                radius=6,
                fill=COLOR_ACCENT if held else (24, 24, 24),
                outline=COLOR_FG if held else COLOR_ACCENT,
                width=2,
            )
            draw_text(fb, x0 + 6, y0 + 4, word, size=14, color=COLOR_BG if held else COLOR_ACCENT)
        labels = {"ok": "OK", "cancel": "Cancel", " ": "space"}
        for item in self._hits:
            held = item.id == self.down
            fb.draw.rounded_rectangle(
                (item.x0, item.y0, item.x1 - 1, item.y1 - 1),
                radius=6,
                fill=COLOR_ACCENT if held else (24, 24, 24),
                outline=COLOR_FG if held else COLOR_ACCENT,
                width=2,
            )
            cx, cy = item.center()
            ink = COLOR_BG if held else COLOR_FG
            if item.id == "back":
                _draw_delete_mark(fb.draw, cx, cy, ink)
                continue
            if item.id == "prev":
                _draw_left_arrow(fb.draw, cx, cy, ink)
                continue
            label = labels.get(item.id, item.id)
            draw_text(fb, cx, cy, label, size=16, color=ink, anchor="mm")
