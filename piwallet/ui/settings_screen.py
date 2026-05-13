"""Bonnet global settings screen.

A minimal value-editor for :class:`piwallet.core.settings.BonnetSettings`.
Today the only setting is screen brightness; the screen is structured
as a small row table so future toggles (sleep timeout, panel rotation,
target FPS) drop in without redesign.

Controls
--------
=========  ==================================================
UP/DOWN    Move the cursor between settings rows.
LEFT/RIGHT Adjust the highlighted row's value (live preview).
A / SEL    Save the draft and return ``"saved"``.
B PRESS    Discard the draft and return ``"back"``; the
           caller restores the original brightness on exit.
B LONG     Exit the bonnet app entirely (``"exit"``).
=========  ==================================================

Design notes
------------
- The screen accepts an optional ``apply_brightness`` callback so
  changes can be previewed live on the panel as the user adjusts the
  slider. Tests pass a stub recorder; production wires it to
  ``display.set_brightness``.
- The brightness step (5 percentage points) is small enough to feel
  responsive and large enough that ten or so left/rights span the full
  legal range. Holding the joystick triggers ``REPEAT`` events which
  step at the bonnet's repeat cadence.
- The screen never persists settings on its own — that's the
  caller's job, so the same flow can be reused when the bonnet boots
  to a settings re-prompt or runs an inline brightness tweak.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from piwallet.core.settings import BonnetSettings
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIM,
    COLOR_FG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    MAX_BRIGHTNESS,
    MIN_BRIGHTNESS,
    FrameBuffer,
    clamp_brightness,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import draw_text

SettingsScreenResult = Literal["saved", "back", "exit"]

#: Step size used by left/right and repeat-events when adjusting brightness.
BRIGHTNESS_STEP: float = 0.05


@dataclass
class SettingsRow:
    """Visual + interaction metadata for a single editable setting."""

    key: str
    label: str
    #: Renderer for the right-hand value column.
    value_text: Callable[[BonnetSettings], str]


def _brightness_value_text(s: BonnetSettings) -> str:
    return f"{round(s.brightness * 100):d}%"


SETTINGS_ROWS: tuple[SettingsRow, ...] = (
    SettingsRow(
        key="brightness",
        label="Brightness",
        value_text=_brightness_value_text,
    ),
)


@dataclass
class SettingsScreen:
    """Edit and (optionally) preview :class:`BonnetSettings`."""

    settings: BonnetSettings
    apply_brightness: Callable[[float], None] | None = None
    rows: tuple[SettingsRow, ...] = SETTINGS_ROWS
    cursor: int = 0
    done: bool = False
    result: SettingsScreenResult | None = None
    #: Working copy mutated by left/right; saved into ``settings`` on A.
    _draft: BonnetSettings = field(init=False)
    _original: BonnetSettings = field(init=False)

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("SettingsScreen requires at least one row")
        self._draft = self.settings
        self._original = self.settings

    @property
    def draft(self) -> BonnetSettings:
        """Read-only view of the in-progress edits (for tests + caller)."""
        return self._draft

    # -- input -------------------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.B and k == EventKind.LONG:
            self._restore_preview()
            self.done = True
            self.result = "exit"
            return
        if b == Button.B and k == EventKind.PRESS:
            self._restore_preview()
            self.done = True
            self.result = "back"
            return
        if b in (Button.A, Button.SELECT) and k == EventKind.PRESS:
            self.settings = self._draft
            self.done = True
            self.result = "saved"
            return
        if b == Button.UP and k in (EventKind.PRESS, EventKind.REPEAT):
            self.cursor = (self.cursor - 1) % len(self.rows)
            return
        if b == Button.DOWN and k in (EventKind.PRESS, EventKind.REPEAT):
            self.cursor = (self.cursor + 1) % len(self.rows)
            return
        if b == Button.LEFT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._adjust(-BRIGHTNESS_STEP)
            return
        if b == Button.RIGHT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._adjust(+BRIGHTNESS_STEP)
            return

    def _adjust(self, delta: float) -> None:
        row = self.rows[self.cursor]
        if row.key != "brightness":
            return
        new_brightness = clamp_brightness(self._draft.brightness + delta)
        if new_brightness == self._draft.brightness:
            return
        self._draft = replace(self._draft, brightness=new_brightness)
        if self.apply_brightness is not None:
            self.apply_brightness(new_brightness)

    def _restore_preview(self) -> None:
        if (
            self.apply_brightness is not None
            and self._draft.brightness != self._original.brightness
        ):
            self.apply_brightness(self._original.brightness)
        self._draft = self._original

    # -- render ------------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        title_h = 28
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, title_h), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            title_h // 2,
            "Settings",
            size=14,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        row_y = title_h + 4
        row_h = 32
        for idx, row in enumerate(self.rows):
            is_cursor = idx == self.cursor
            top = row_y + idx * row_h
            if is_cursor:
                fb.draw.rectangle(
                    (0, top, DISPLAY_WIDTH, top + row_h),
                    fill=(48, 64, 96),
                )
            draw_text(
                fb,
                12,
                top + row_h // 2,
                row.label,
                size=14,
                color=COLOR_FG,
                anchor="lm",
            )
            draw_text(
                fb,
                DISPLAY_WIDTH - 12,
                top + row_h // 2,
                row.value_text(self._draft),
                size=14,
                color=COLOR_FG if is_cursor else COLOR_DIM,
                anchor="rm",
            )

        # Brightness slider preview (only when on the brightness row).
        if self.rows[self.cursor].key == "brightness":
            self._draw_slider(fb, self._draft.brightness)

        # Footer hints.
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 24,
            "L/R adjust   U/D row",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 10,
            "A save   B back   hold B quit",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )

    def _draw_slider(self, fb: FrameBuffer, brightness: float) -> None:
        margin = 24
        track_top = DISPLAY_HEIGHT - 64
        track_bottom = track_top + 8
        # Track.
        fb.draw.rectangle(
            (margin, track_top, DISPLAY_WIDTH - margin, track_bottom),
            fill=(40, 40, 48),
            outline=COLOR_DIM,
        )
        # Fill, mapped to the legal [MIN_BRIGHTNESS, MAX_BRIGHTNESS] band.
        denom = max(1e-6, MAX_BRIGHTNESS - MIN_BRIGHTNESS)
        frac = max(0.0, min(1.0, (brightness - MIN_BRIGHTNESS) / denom))
        fill_w = round((DISPLAY_WIDTH - 2 * margin) * frac)
        if fill_w > 0:
            fb.draw.rectangle(
                (margin, track_top, margin + fill_w, track_bottom),
                fill=COLOR_ACCENT,
            )
