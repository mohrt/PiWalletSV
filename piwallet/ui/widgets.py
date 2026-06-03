"""Reusable widget primitives for the bonnet UI.

Every widget here is *pure* with respect to the framebuffer: ``draw()``
paints into the supplied :class:`FrameBuffer` and returns ``None``.
State (cursor positions, scroll offsets, accumulated input characters)
lives on the widget instance and is mutated via ``on_event()`` from
events produced by :class:`piwallet.ui.input.InputManager`.

This split keeps widgets testable: a test instantiates the widget,
feeds a scripted sequence of events through ``on_event``, and inspects
the widget's state or the rendered framebuffer pixels for the expected
result.
"""

from __future__ import annotations

from dataclasses import dataclass

from pathlib import Path

from PIL import ImageFont

from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIM,
    COLOR_FG,
    COLOR_OK,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind

# PIL ``load_default(size=…)`` scales a tiny bitmap font; at 10–12 px
# the space glyph often has **zero advance width**, so footers like
# ``"A/B exit"`` render as ``"A/Bexit"``. Prefer DejaVu (installed on
# Pi OS images via ``fonts-dejavu-core``) and fall back only when absent.
_FONT_PATHS: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
)
_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}


def font(size: int = 12) -> ImageFont.ImageFont:
    """Return a cached PIL font sized for the 240x240 panel."""
    cached = _FONT_CACHE.get(size)
    if cached is not None:
        return cached
    for path in _FONT_PATHS:
        if Path(path).is_file():
            font_obj = ImageFont.truetype(path, size)
            _FONT_CACHE[size] = font_obj
            return font_obj
    font_obj = ImageFont.load_default(size=size)
    _FONT_CACHE[size] = font_obj
    return font_obj


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def draw_text(
    fb: FrameBuffer,
    x: int,
    y: int,
    text: str,
    *,
    size: int = 12,
    color: tuple[int, int, int] = COLOR_FG,
    anchor: str = "la",
) -> None:
    """Draw a single line of text onto ``fb``.

    ``anchor`` follows PIL's two-letter convention (``"la"`` = left/
    ascender, ``"ma"`` = middle/ascender, ``"mm"`` = middle/middle,
    etc.).
    """
    fb.draw.text((x, y), text, fill=color, font=font(size), anchor=anchor)


def text_bbox(text: str, *, size: int = 12) -> tuple[int, int, int, int]:
    """Return PIL's ``(left, top, right, bottom)`` for ``text``."""
    return font(size).getbbox(text)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# ListView — scrollable single-column list
# ---------------------------------------------------------------------------


@dataclass
class ListItem:
    label: str
    value: object = None  # opaque payload returned on SELECT
    disabled: bool = False


@dataclass
class ListView:
    """Scrollable vertical list with a single highlighted cursor.

    Up / down move the cursor (with wrap-around). A / SELECT / right
    confirm and return the highlighted ``ListItem.value`` via the
    ``confirmed`` field. B / left is left to the surrounding screen to
    interpret (typically "back").

    Attributes
    ----------
    title : str
        Optional top-bar title.
    items : list[ListItem]
        Rows to draw.
    footer : str
        Optional one-line hint rendered in the bottom strip of the panel
        (e.g. ``"A: select   B: back"``).  Fits in the ~16 px gap that
        remains below 7 rows of 28 px on a 240 px panel.
    cursor : int
        Index into ``items`` of the highlighted row.
    confirmed : object | None
        Set by ``on_event`` when the user confirms. Read once by the
        owning screen and reset to ``None`` to "consume" the action.
    """

    items: list[ListItem]
    title: str = ""
    footer: str = ""
    #: When set, used for the title bar text instead of :data:`COLOR_ACCENT`.
    title_color: tuple[int, int, int] | None = None
    cursor: int = 0
    confirmed: object | None = None
    row_height: int = 28
    title_height: int = 28
    visible_rows: int = 7  # 240 / 28 ≈ 8 minus title bar
    _scroll: int = 0

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("ListView requires at least one item")
        self._clamp_cursor()

    # -- state mutation ----------------------------------------------

    def on_event(self, event: Event) -> None:
        if event.kind not in (EventKind.PRESS, EventKind.REPEAT):
            return
        if event.button == Button.UP:
            self._move(-1)
        elif event.button == Button.DOWN:
            self._move(+1)
        elif event.button in (Button.A, Button.SELECT, Button.RIGHT):
            if event.kind != EventKind.PRESS:
                return
            item = self.items[self.cursor]
            if not item.disabled:
                self.confirmed = item.value

    def _move(self, delta: int) -> None:
        n = len(self.items)
        new = (self.cursor + delta) % n
        # Skip past disabled items in the direction of motion.
        guard = n
        while self.items[new].disabled and guard > 0:
            new = (new + (1 if delta > 0 else -1)) % n
            guard -= 1
        if guard == 0:
            return  # every item disabled
        self.cursor = new
        self._update_scroll()

    def _clamp_cursor(self) -> None:
        if not self.items:
            return
        self.cursor = max(0, min(self.cursor, len(self.items) - 1))
        self._update_scroll()

    def _update_scroll(self) -> None:
        if self.cursor < self._scroll:
            self._scroll = self.cursor
        elif self.cursor >= self._scroll + self.visible_rows:
            self._scroll = self.cursor - self.visible_rows + 1
        max_scroll = max(0, len(self.items) - self.visible_rows)
        self._scroll = min(self._scroll, max_scroll)

    # -- rendering ----------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        y = 0
        if self.title:
            fb.draw.rectangle(
                (0, 0, DISPLAY_WIDTH, self.title_height),
                fill=(20, 20, 32),
            )
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                self.title_height // 2,
                self.title,
                size=14,
                color=self.title_color or COLOR_ACCENT,
                anchor="mm",
            )
            y = self.title_height
        for row_idx in range(self.visible_rows):
            item_idx = self._scroll + row_idx
            if item_idx >= len(self.items):
                break
            item = self.items[item_idx]
            row_y = y + row_idx * self.row_height
            is_cursor = item_idx == self.cursor
            if is_cursor:
                fb.draw.rectangle(
                    (0, row_y, DISPLAY_WIDTH, row_y + self.row_height),
                    fill=(48, 64, 96),
                )
            color = COLOR_DIM if item.disabled else COLOR_FG
            draw_text(fb, 12, row_y + self.row_height // 2, item.label, size=14,
                      color=color, anchor="lm")

        # Tiny scrollbar on the right edge when scrolling is needed.
        if len(self.items) > self.visible_rows:
            track_top = (self.title_height if self.title else 0) + 2
            track_height = DISPLAY_HEIGHT - track_top - 2
            fb.draw.rectangle(
                (DISPLAY_WIDTH - 4, track_top, DISPLAY_WIDTH - 2, track_top + track_height),
                fill=(40, 40, 48),
            )
            thumb_h = max(8, track_height * self.visible_rows // len(self.items))
            overscroll = max(1, len(self.items) - self.visible_rows)
            thumb_y = track_top + (track_height - thumb_h) * self._scroll // overscroll
            fb.draw.rectangle(
                (DISPLAY_WIDTH - 4, thumb_y, DISPLAY_WIDTH - 2, thumb_y + thumb_h),
                fill=COLOR_ACCENT,
            )

        # Footer hint strip — rendered in the ~16 px gap below 7 rows.
        if self.footer:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                DISPLAY_HEIGHT - 5,
                self.footer,
                size=10,
                color=COLOR_DIM,
                anchor="mb",
            )


# ---------------------------------------------------------------------------
# Modal — centered information / confirmation card
# ---------------------------------------------------------------------------


@dataclass
class Modal:
    """A centered card with a title, body text, and footer hint.

    Multi-line ``body`` is wrapped at a fixed character cell. The modal
    itself does not handle dismissal; the caller listens for the
    appropriate event on its own screen state machine.
    """

    title: str
    body: str
    footer: str = ""
    accent: tuple[int, int, int] = COLOR_ACCENT

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        pad = 12
        # Card outline.
        fb.draw.rectangle(
            (pad, pad, DISPLAY_WIDTH - pad, DISPLAY_HEIGHT - pad),
            fill=(16, 16, 24),
            outline=self.accent,
            width=2,
        )
        # Title bar.
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            pad + 18,
            self.title,
            size=16,
            color=self.accent,
            anchor="mm",
        )
        # Body lines.
        body_y = pad + 38
        for line in _wrap_lines(self.body, max_chars=24):
            draw_text(fb, DISPLAY_WIDTH // 2, body_y, line, size=12,
                      color=COLOR_FG, anchor="mm")
            body_y += 16
            if body_y > DISPLAY_HEIGHT - pad - 24:
                break
        # Footer.
        if self.footer:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                DISPLAY_HEIGHT - pad - 12,
                self.footer,
                size=11,
                color=COLOR_DIM,
                anchor="mm",
            )


def wrap_text_lines(text: str, *, max_chars: int) -> list[str]:
    """Greedy word-wrap, preserving explicit newlines.

    Breaks at spaces so words are not split mid-token unless a single
    word exceeds ``max_chars`` (then it is hard-broken).
    """
    out: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            out.append("")
            continue
        words = paragraph.split()
        line = ""
        for word in words:
            candidate = (line + " " + word).strip() if line else word
            if len(candidate) <= max_chars:
                line = candidate
            else:
                if line:
                    out.append(line)
                # If the word itself is too long, hard-break it.
                while len(word) > max_chars:
                    out.append(word[:max_chars])
                    word = word[max_chars:]
                line = word
        if line:
            out.append(line)
    return out


def _wrap_lines(text: str, *, max_chars: int) -> list[str]:
    return wrap_text_lines(text, max_chars=max_chars)


# ---------------------------------------------------------------------------
# ProgressBar — horizontal bar with optional label
# ---------------------------------------------------------------------------


@dataclass
class ProgressBar:
    """Filled horizontal bar for scan / fetch / sign progress.

    ``value`` and ``total`` are integers (or floats); the bar fills the
    fraction ``value / total`` and renders the label centered below.
    """

    label: str = ""
    value: float = 0.0
    total: float = 1.0
    color: tuple[int, int, int] = COLOR_OK
    y: int = DISPLAY_HEIGHT // 2

    def set_progress(self, value: float, total: float | None = None) -> None:
        if total is not None:
            self.total = max(0.0001, total)
        self.value = max(0.0, min(self.total, value))

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        pad = 24
        bar_h = 20
        # Track.
        fb.draw.rectangle(
            (pad, self.y, DISPLAY_WIDTH - pad, self.y + bar_h),
            fill=(40, 40, 48),
            outline=COLOR_DIM,
        )
        # Fill.
        if self.total > 0:
            frac = max(0.0, min(1.0, self.value / self.total))
            fill_width = round((DISPLAY_WIDTH - 2 * pad) * frac)
            if fill_width > 0:
                fb.draw.rectangle(
                    (pad, self.y, pad + fill_width, self.y + bar_h),
                    fill=self.color,
                )
        if self.label:
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                self.y - 12,
                self.label,
                size=12,
                color=COLOR_FG,
                anchor="mm",
            )
        # Percentage badge below the bar.
        if self.total > 0:
            pct = round(100 * self.value / self.total)
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                self.y + bar_h + 16,
                f"{pct}%",
                size=14,
                color=COLOR_FG,
                anchor="mm",
            )
