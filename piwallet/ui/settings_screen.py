"""Bonnet global settings screen.

A minimal value-editor for :class:`piwallet.core.settings.BonnetSettings`.
Value rows (brightness, sleep timer, camera) cycle with L/R; action rows
open sub-flows on ``A``. The caller persists on save and re-opens this
screen after read-only sub-screens (e.g. airgap status) return.

Controls
--------
==================  ==================================================
UP/DOWN             Move the cursor between settings rows.
LEFT/RIGHT          Cycle the highlighted *value* row. No effect on
                    action rows.
A / SEL on a value  Save the draft and return ``"saved"``.
A / SEL on action   Save value-row drafts and return the action key.
B (short)           Discard draft and return ``"back"``.
==================  ==================================================
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from piwallet import __version__ as PIWALLET_VERSION
from piwallet.core.settings import (
    BRIGHTNESS_OPTIONS,
    CAMERA_TYPE_OPTIONS,
    SLEEP_TIMER_OPTIONS_MS,
    BonnetSettings,
)
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIM,
    COLOR_FG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import draw_text

SettingsScreenResult = Literal[
    "saved", "back", "change_pin", "airgap", "usb_backup", "about", "system_reset"
]

_CYCLER_KEYS = frozenset({"brightness", "sleep_timer", "camera_type"})


@dataclass
class SettingsRow:
    """Visual + interaction metadata for a single settings row."""

    key: str
    label: str
    value_text: Callable[[BonnetSettings], str]
    is_action: bool = False


def _brightness_value_text(s: BonnetSettings) -> str:
    return f"{round(s.brightness * 100):d}%"


def _format_sleep_timeout_ms(ms: int) -> str:
    if ms <= 0:
        return "Off"
    minutes = ms // 60_000
    return f"{minutes} min"


def _sleep_timer_value_text(s: BonnetSettings) -> str:
    return _format_sleep_timeout_ms(s.sleep_timeout_ms)


_CAMERA_TYPE_LABELS: dict[str, str] = {
    "ov5647": "OV5647 Mini",
    "imx708": "CM3 (IMX708)",
    "auto": "Auto-detect",
}


def _camera_type_value_text(s: BonnetSettings) -> str:
    return _CAMERA_TYPE_LABELS.get(s.camera_type, s.camera_type)


def _action_arrow(_s: BonnetSettings) -> str:
    return ">"


SETTINGS_ROWS: tuple[SettingsRow, ...] = (
    SettingsRow(
        key="brightness",
        label="Brightness",
        value_text=_brightness_value_text,
    ),
    SettingsRow(
        key="sleep_timer",
        label="Sleep timer",
        value_text=_sleep_timer_value_text,
    ),
    SettingsRow(
        key="camera_type",
        label="Camera",
        value_text=_camera_type_value_text,
    ),
    SettingsRow(
        key="change_pin",
        label="Change PIN",
        value_text=_action_arrow,
        is_action=True,
    ),
    SettingsRow(
        key="airgap",
        label="Airgap status",
        value_text=_action_arrow,
        is_action=True,
    ),
    SettingsRow(
        key="usb_backup",
        label="USB backup",
        value_text=_action_arrow,
        is_action=True,
    ),
    SettingsRow(
        key="about",
        label="About",
        value_text=_action_arrow,
        is_action=True,
    ),
    SettingsRow(
        key="system_reset",
        label="System reset",
        value_text=_action_arrow,
        is_action=True,
    ),
)

_FOOTER_HINT_TOP_Y = DISPLAY_HEIGHT - 26
_FOOTER_HINT_BOTTOM_Y = DISPLAY_HEIGHT - 12
_LIST_BOTTOM_Y = DISPLAY_HEIGHT - 36


@dataclass
class SettingsScreen:
    """Edit and (optionally) preview :class:`BonnetSettings`."""

    settings: BonnetSettings
    apply_brightness: Callable[[float], None] | None = None
    rows: tuple[SettingsRow, ...] = SETTINGS_ROWS
    cursor: int = 0
    done: bool = False
    result: SettingsScreenResult | None = None
    _draft: BonnetSettings = field(init=False)
    _original: BonnetSettings = field(init=False)
    _b_pressed_here: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("SettingsScreen requires at least one row")
        self._draft = self.settings
        self._original = self.settings

    @property
    def draft(self) -> BonnetSettings:
        return self._draft

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.B:
            if k == EventKind.PRESS:
                self._b_pressed_here = True
                return
            if k == EventKind.RELEASE:
                if self._b_pressed_here:
                    self._restore_preview()
                    self.done = True
                    self.result = "back"
                self._b_pressed_here = False
                return
        if b in (Button.A, Button.SELECT) and k == EventKind.PRESS:
            row = self.rows[self.cursor]
            self.settings = self._draft
            self.done = True
            self.result = row.key if row.is_action else "saved"
            return
        if b == Button.UP and k in (EventKind.PRESS, EventKind.REPEAT):
            self.cursor = (self.cursor - 1) % len(self.rows)
            return
        if b == Button.DOWN and k in (EventKind.PRESS, EventKind.REPEAT):
            self.cursor = (self.cursor + 1) % len(self.rows)
            return
        if b == Button.LEFT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._adjust(-1)
            return
        if b == Button.RIGHT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._adjust(+1)
            return

    def _adjust(self, step: int) -> None:
        row = self.rows[self.cursor]
        if row.key == "brightness":
            self._cycle_brightness(step=step)
        elif row.key == "sleep_timer":
            self._cycle_sleep_timer(step=step)
        elif row.key == "camera_type":
            self._cycle_camera_type(step=step)

    def _cycle_brightness(self, *, step: int) -> None:
        options = BRIGHTNESS_OPTIONS
        if not options:
            return
        try:
            idx = options.index(self._draft.brightness)
        except ValueError:
            idx = 0
        new_idx = (idx + step) % len(options)
        new_value = options[new_idx]
        if new_value == self._draft.brightness:
            return
        self._draft = replace(self._draft, brightness=new_value)
        if self.apply_brightness is not None:
            self.apply_brightness(new_value)

    def _cycle_sleep_timer(self, *, step: int) -> None:
        options = SLEEP_TIMER_OPTIONS_MS
        if not options:
            return
        try:
            idx = options.index(self._draft.sleep_timeout_ms)
        except ValueError:
            idx = 0
        new_idx = (idx + step) % len(options)
        new_value = options[new_idx]
        if new_value == self._draft.sleep_timeout_ms:
            return
        self._draft = replace(self._draft, sleep_timeout_ms=new_value)

    def _cycle_camera_type(self, *, step: int) -> None:
        options = CAMERA_TYPE_OPTIONS
        if not options:
            return
        try:
            idx = options.index(self._draft.camera_type)
        except ValueError:
            idx = 0
        new_idx = (idx + step) % len(options)
        new_value = options[new_idx]
        if new_value == self._draft.camera_type:
            return
        self._draft = replace(self._draft, camera_type=new_value)

    def _restore_preview(self) -> None:
        if (
            self.apply_brightness is not None
            and self._draft.brightness != self._original.brightness
        ):
            self.apply_brightness(self._original.brightness)
        self._draft = self._original

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
        draw_text(
            fb,
            DISPLAY_WIDTH - 6,
            title_h // 2,
            f"v{PIWALLET_VERSION}",
            size=9,
            color=COLOR_DIM,
            anchor="rm",
        )

        row_y = title_h + 2
        row_h = min(
            28,
            max(22, (_LIST_BOTTOM_Y - row_y) // max(1, len(self.rows))),
        )
        for idx, row in enumerate(self.rows):
            is_cursor = idx == self.cursor
            top = row_y + idx * row_h
            bottom = min(top + row_h, _LIST_BOTTOM_Y)
            if is_cursor:
                fb.draw.rectangle(
                    (0, top, DISPLAY_WIDTH, bottom),
                    fill=(48, 64, 96),
                )
            draw_text(
                fb,
                12,
                top + (bottom - top) // 2,
                row.label,
                size=14,
                color=COLOR_FG,
                anchor="lm",
            )
            val = row.value_text(self._draft)
            if is_cursor and row.key in _CYCLER_KEYS:
                val = f"< {val} >"
            draw_text(
                fb,
                DISPLAY_WIDTH - 12,
                top + (bottom - top) // 2,
                val,
                size=14,
                color=COLOR_FG if is_cursor else COLOR_DIM,
                anchor="rm",
            )

        cur_row = self.rows[self.cursor]
        on_action = cur_row.is_action
        on_cycler = cur_row.key in _CYCLER_KEYS
        if on_action:
            upper_hint = "U/D row"
        elif on_cycler:
            upper_hint = "< / > cycle   U/D row"
        else:
            upper_hint = "L/R adjust   U/D row"
        a_verb = "select" if on_action else "save"
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            _FOOTER_HINT_TOP_Y,
            upper_hint,
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            _FOOTER_HINT_BOTTOM_Y,
            f"A {a_verb}   B back",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
