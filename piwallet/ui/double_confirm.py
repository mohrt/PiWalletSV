"""Two-step acknowledgement (double confirm) for destructive or permanent actions."""

from __future__ import annotations

from dataclasses import dataclass

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
from piwallet.ui.widgets import draw_text, wrap_text_lines

# Narrow column (~18 chars) avoids clipped edges on centered 240px text at size 12-14.
_MAX_LINE_BODY: int = 18
_MAX_LINE_WARN_BODY: int = 17
_MAX_LINE_WARN_TITLE: int = 15

# Readable text on burgundy panels (step-2 destructive style).
_STEP2_WARN_FG: tuple[int, int, int] = (255, 228, 222)
_STEP2_BAR_BG: tuple[int, int, int] = (52, 10, 14)
_STEP2_PANEL_BG: tuple[int, int, int] = (40, 10, 12)
_SHADOW: tuple[int, int, int] = (28, 6, 8)


def _emphasized_line(
    fb: FrameBuffer,
    x: int,
    y: int,
    text: str,
    *,
    size: int,
    fg: tuple[int, int, int],
) -> None:
    """Slight faux-bold shadow for legibility on saturated backgrounds."""
    draw_text(fb, x + 1, y + 1, text, size=size, color=_SHADOW, anchor="mm")
    draw_text(fb, x, y, text, size=size, color=fg, anchor="mm")


@dataclass
class DoubleConfirmScreen:
    """Caller sets ``done`` when the operator finishes.

    Both stages require **A** (or SELECT) with **distinct** presses.
    **B** at either stage abandons without confirming (``result`` is ``False``).

    Set ``second_step_warning`` for destructive flows — step two uses red
    header/panel tones and bolder treatment.

    Prompt text uses word-aware wrapping so words are not split at the margins.
    """

    title: str
    first_prompt: str
    second_prompt: str
    second_step_warning: bool = False
    second_title: str | None = None
    step: int = 0  # 0 = first prompt, 1 = second
    done: bool = False
    result: bool | None = None

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.B and k in (EventKind.PRESS, EventKind.LONG):
            self.done = True
            self.result = False
            return
        if k != EventKind.PRESS:
            return
        if b in (Button.A, Button.SELECT):
            if self.step == 0:
                self.step = 1
            else:
                self.done = True
                self.result = True

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        if self.step == 1 and self.second_step_warning:
            self._draw_second_step_warning(fb)
            return
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
        py = 38
        prompt = self.first_prompt if self.step == 0 else self.second_prompt
        for line in wrap_text_lines(prompt, max_chars=_MAX_LINE_BODY):
            if not line.strip():
                py += 8
                continue
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                py,
                line,
                size=12,
                color=COLOR_FG,
                anchor="mm",
            )
            py += 16
        self._draw_footer(fb)

    def _draw_second_step_warning(self, fb: FrameBuffer) -> None:
        bar_title = self.second_title or "Absolutely sure?"
        title_lines = wrap_text_lines(bar_title, max_chars=_MAX_LINE_WARN_TITLE)[:2]
        bar_h = 16 + len(title_lines) * 13
        bar_h = min(max(bar_h, 28), 44)
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, bar_h), fill=_STEP2_BAR_BG)
        ty = 13
        for tl in title_lines:
            _emphasized_line(
                fb,
                DISPLAY_WIDTH // 2,
                ty,
                tl,
                size=13,
                fg=COLOR_DANGER,
            )
            ty += 14

        panel_top = bar_h + 2
        panel_bottom = DISPLAY_HEIGHT - 30
        fb.draw.rectangle(
            (6, panel_top, DISPLAY_WIDTH - 6, panel_bottom),
            outline=COLOR_DANGER,
            width=2,
            fill=_STEP2_PANEL_BG,
        )
        py = panel_top + 11
        for line in wrap_text_lines(self.second_prompt, max_chars=_MAX_LINE_WARN_BODY):
            if not line.strip():
                py += 6
                continue
            _emphasized_line(
                fb,
                DISPLAY_WIDTH // 2,
                py,
                line,
                size=12,
                fg=_STEP2_WARN_FG,
            )
            py += 16
            if py > panel_bottom - 10:
                break
        self._draw_footer(fb)

    def _draw_footer(self, fb: FrameBuffer) -> None:
        if self.step == 0:
            hint = "1/2  A next  B cancel"
            col = COLOR_DIM
        elif self.second_step_warning:
            hint = "2/2  A erases  B cancel"
            col = COLOR_DANGER
        else:
            hint = "2/2  A confirm  B cancel"
            col = COLOR_DIM
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 12,
            hint,
            size=9,
            color=col,
            anchor="mm",
        )
