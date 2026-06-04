"""Bonnet global settings screen.

A minimal value-editor for :class:`piwallet.core.settings.BonnetSettings`.
Two value rows today — Brightness (continuous slider) and Sleep timer
(discrete cycle: 1 min / 5 min / off) — and one action row, "Change
PIN…", which exits the screen with ``result = "change_pin"`` so the
caller can drive the change-PIN sub-flow and then re-open Settings.
The screen is structured as a small row table so future toggles
(panel rotation, target FPS, etc.) drop in without redesign.

Controls
--------
==================  ==================================================
UP/DOWN             Move the cursor between settings rows.
LEFT/RIGHT          Adjust the highlighted *value* row (live preview
                    for brightness; cycles the discrete value for
                    sleep timer). No effect on action rows.
A / SEL on a value  Save the draft and return ``"saved"``.
A / SEL on action   Save the value-row drafts (just like a normal save)
                    AND return the action key (today only
                    ``"change_pin"``) so the caller dispatches.
B PRESS             Discard the draft and return ``"back"``; the
                    caller restores the original brightness on exit.
B LONG              Exit the bonnet app entirely (``"exit"``).
==================  ==================================================

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
- The sleep timer cycles through a discrete preset list rather than a
  free-form slider so operators can't end up with a 17-second timeout
  by accident, and so a future migration can enumerate legal values.
- The screen never persists settings on its own — that's the
  caller's job, so the same flow can be reused when the bonnet boots
  to a settings re-prompt or runs an inline brightness tweak.
- Action rows save the in-progress value drafts on ``A`` so an
  operator who tweaks brightness, then taps "Change PIN…", doesn't
  lose their slider change just because the change-PIN flow happens
  to be a separate sub-screen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from piwallet import __version__ as PIWALLET_VERSION
from piwallet.core.settings import (
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
    MAX_BRIGHTNESS,
    MIN_BRIGHTNESS,
    FrameBuffer,
    clamp_brightness,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import draw_text

SettingsScreenResult = Literal[
    "saved", "back", "exit", "change_pin", "airgap", "usb_backup"
]

#: Step size used by left/right and repeat-events when adjusting brightness.
BRIGHTNESS_STEP: float = 0.05


@dataclass
class SettingsRow:
    """Visual + interaction metadata for a single settings row.

    Two flavours, discriminated by :attr:`is_action`:

    * ``is_action=False`` (default) — a *value* row whose right-hand
      column is the editable value. L/R adjusts the draft; ``A`` on
      this row saves and exits with ``"saved"``.
    * ``is_action=True`` — an *action* row that opens a sub-flow
      when ``A`` is pressed. L/R is a no-op. The screen exits with
      ``result = key`` so the caller can dispatch on the row's key
      (e.g. ``"change_pin"``). Pending value-row drafts are saved
      first so the operator's slider/cycle changes aren't dropped.
    """

    key: str
    label: str
    #: Renderer for the right-hand value column.
    value_text: Callable[[BonnetSettings], str]
    is_action: bool = False


def _brightness_value_text(s: BonnetSettings) -> str:
    return f"{round(s.brightness * 100):d}%"


def _format_sleep_timeout_ms(ms: int) -> str:
    """Operator-readable sleep-timer label.

    ``0`` is the "Off" preset — never blank; positive values render
    in minutes (the only granularity the preset list ships with).
    """
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
    """Right-column glyph for action rows — visual cue that A opens a sub-flow."""
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
    # Surfaces piwallet.diag.airgap as a one-tap "is this device
    # actually quiet on the airwaves right now?" check. Anchored
    # below Change PIN because both are action rows; ordering them
    # together keeps value rows and action rows visually separate.
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
)


#: Vertical space reserved for the two-line footer hint strip.
_FOOTER_RESERVE_PX: int = 36


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
            row = self.rows[self.cursor]
            # Save pending value-row drafts on either path. For
            # action rows this means a tweak made just before
            # tapping the action isn't lost while the sub-flow
            # runs; for value rows it's the long-standing
            # save-and-exit behaviour.
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
            self._adjust(-BRIGHTNESS_STEP)
            return
        if b == Button.RIGHT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._adjust(+BRIGHTNESS_STEP)
            return

    def _adjust(self, delta: float) -> None:
        row = self.rows[self.cursor]
        if row.key == "brightness":
            new_brightness = clamp_brightness(self._draft.brightness + delta)
            if new_brightness == self._draft.brightness:
                return
            self._draft = replace(self._draft, brightness=new_brightness)
            if self.apply_brightness is not None:
                self.apply_brightness(new_brightness)
            return
        if row.key == "sleep_timer":
            self._cycle_sleep_timer(step=1 if delta > 0 else -1)
            return
        if row.key == "camera_type":
            self._cycle_camera_type(step=1 if delta > 0 else -1)
            return

    def _cycle_sleep_timer(self, *, step: int) -> None:
        """Advance the sleep-timer preset by one slot in either direction.

        Wraps at the ends so L/R cycles indefinitely. ``step`` is +1
        for RIGHT, -1 for LEFT. The ``replace`` is unconditional even
        when there's only one preset (currently three) — it keeps the
        ``_draft`` identity stable for callers that diff state.
        """
        options = SLEEP_TIMER_OPTIONS_MS
        if not options:
            return
        try:
            idx = options.index(self._draft.sleep_timeout_ms)
        except ValueError:
            # Drafted value drifted off the preset list (e.g. a hand-
            # edited file that load_settings let through). Snap back
            # to the default index 0 before stepping.
            idx = 0
        new_idx = (idx + step) % len(options)
        new_value = options[new_idx]
        if new_value == self._draft.sleep_timeout_ms:
            return
        self._draft = replace(self._draft, sleep_timeout_ms=new_value)

    def _cycle_camera_type(self, *, step: int) -> None:
        """Advance the camera-type preset by one slot in either direction."""
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
        draw_text(
            fb,
            DISPLAY_WIDTH - 6,
            title_h // 2,
            f"v{PIWALLET_VERSION}",
            size=9,
            color=COLOR_DIM,
            anchor="rm",
        )

        _CYCLER_KEYS = {"sleep_timer", "camera_type"}

        row_y = title_h + 2
        list_bottom = DISPLAY_HEIGHT - _FOOTER_RESERVE_PX
        row_h = min(32, (list_bottom - row_y) // max(1, len(self.rows)))
        row_h = max(row_h, 24)
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
            val = row.value_text(self._draft)
            # Wrap left/right cycler values in < > brackets when selected
            # so the operator sees that LEFT/RIGHT scrolls through options.
            if is_cursor and row.key in _CYCLER_KEYS:
                val = f"< {val} >"
            draw_text(
                fb,
                DISPLAY_WIDTH - 12,
                top + row_h // 2,
                val,
                size=14,
                color=COLOR_FG if is_cursor else COLOR_DIM,
                anchor="rm",
            )

        # Brightness slider lives in the footer gutter below the row list.
        if self.rows[self.cursor].key == "brightness":
            track_top = list_bottom + 4
            self._draw_slider(fb, self._draft.brightness, track_top=track_top)

        # Footer hints — vary by row type.
        cur_row = self.rows[self.cursor]
        on_action = cur_row.is_action
        on_cycler = cur_row.key in _CYCLER_KEYS
        if on_action:
            upper_hint = "U/D row"
        elif on_cycler:
            upper_hint = "< / > cycle   U/D row"
        else:
            upper_hint = "L/R adjust   U/D row"
        a_verb = "open" if on_action else "save"
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 24,
            upper_hint,
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 10,
            f"A {a_verb}   B back   hold B quit",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )

    def _draw_slider(self, fb: FrameBuffer, brightness: float, *, track_top: int) -> None:
        margin = 24
        track_height = 6
        track_bottom = track_top + track_height
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
