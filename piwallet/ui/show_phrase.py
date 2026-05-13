"""Bonnet "write this down" screen for a freshly-generated BIP39 phrase.

Shown immediately after the Pi generates a mnemonic, before the user
is asked to re-type each word in the create-confirm flow. The phrase
is paginated into pages of N words (default 4) so it fits cleanly on
the 240x240 panel without truncation.

Controls
--------
=========  =================================================================
LEFT       Previous page (clamped at 0).
RIGHT      Next page; on the LAST page, advance to confirmation.
A          Same as RIGHT - drives the flow forward.
B PRESS    Same as LEFT - back one page.
B LONG     Cancel the whole flow (result=False, done=True).
=========  =================================================================

The phrase itself is **never** logged, persisted, or rendered into
the headless-display history of a real production session. Callers
must hold the phrase as a local variable and zero / discard it as
soon as the create-confirm step is done.
"""

from __future__ import annotations

from collections.abc import Sequence
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


@dataclass
class ShowPhraseScreen:
    """Display a BIP39 phrase one page at a time.

    ``result`` outcomes:

    * ``True``   - operator completed the read-through.
    * ``False``  - operator long-pressed B to cancel.
    """

    words: Sequence[str]
    per_page: int = 4
    page: int = 0
    done: bool = False
    result: bool | None = None
    _pages: list[list[str]] = field(init=False)

    def __post_init__(self) -> None:
        if not self.words:
            raise ValueError("words must be non-empty")
        if self.per_page <= 0:
            raise ValueError("per_page must be positive")
        self._pages = [
            list(self.words[i : i + self.per_page])
            for i in range(0, len(self.words), self.per_page)
        ]
        self.page = max(0, min(self.page, len(self._pages) - 1))

    # -- driver --------------------------------------------------------

    @property
    def num_pages(self) -> int:
        return len(self._pages)

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b in (Button.LEFT, Button.B) and k == EventKind.PRESS:
            if self.page > 0:
                self.page -= 1
        elif b in (Button.RIGHT, Button.A, Button.SELECT) and k == EventKind.PRESS:
            if self.page < self.num_pages - 1:
                self.page += 1
            else:
                self.done = True
                self.result = True
        elif b == Button.B and k == EventKind.LONG:
            self.done = True
            self.result = False

    # -- rendering -----------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        # Warning banner
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, 30), fill=(48, 16, 16))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            10,
            "WRITE THIS DOWN",
            size=12,
            color=COLOR_DANGER,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            22,
            f"page {self.page + 1} of {self.num_pages}",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )

        # Words on this page, numbered for cross-reference
        start_idx = self.page * self.per_page
        y = 56
        for offset, w in enumerate(self._pages[self.page]):
            n = start_idx + offset + 1
            draw_text(
                fb,
                40,
                y,
                f"{n:>2}.",
                size=14,
                color=COLOR_DIM,
                anchor="lm",
            )
            draw_text(
                fb,
                72,
                y,
                w,
                size=18,
                color=COLOR_FG,
                anchor="lm",
            )
            y += 30

        # Page dots
        dot_y = DISPLAY_HEIGHT - 36
        dot_pitch = 10
        dots_w = self.num_pages * dot_pitch
        dot_x = (DISPLAY_WIDTH - dots_w) // 2
        for i in range(self.num_pages):
            color = COLOR_ACCENT if i == self.page else COLOR_DIM
            fb.draw.ellipse(
                (dot_x, dot_y, dot_x + 6, dot_y + 6),
                fill=color,
            )
            dot_x += dot_pitch

        # Footer
        if self.page < self.num_pages - 1:
            footer = "L back   R/A next   hold B cancel"
        else:
            footer = "L back   A done   hold B cancel"
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 14,
            footer,
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
