"""HD derivation-path chooser screens for the create-wallet flow.

The bonnet defaults to BSV's SLIP-44 BIP44 path (``m/44'/236'/0'``);
the screens here let an operator pick a different account or coin
type without changing the seed.

UX
--
1. :class:`HdPathPresetChooser` is shown first. It offers two rows:

   - ``BSV default (m/44'/236'/0')`` — pre-selected so a single A press
     keeps the default for the common case.
   - ``Advanced…`` — opens :class:`CustomHdPathScreen` for arbitrary
     ``coin_type`` / ``account_index`` integers.

2. :class:`CustomHdPathScreen` shows the two integer fields with a
   live ``m/44'/<coin>'/<account>'`` preview. ``UP`` / ``DOWN`` move
   between fields, ``LEFT`` / ``RIGHT`` adjust the highlighted field
   by ±1 (with REPEAT for fast scrolling), ``A`` / ``SELECT`` confirm,
   ``B PRESS`` returns to the preset chooser, ``B LONG`` cancels the
   create flow.

The two screens are independent — :func:`run_hd_path_chooser` glues
them together.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from piwallet.core import derivation as deriv
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIM,
    COLOR_FG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    Display,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind, InputManager
from piwallet.ui.widgets import ListItem, ListView, draw_text

#: A single concrete BIP44 account selection.
HdPathChoice = tuple[int, int]  # (coin_type, account_index)

#: Maximum index either field will accept. BIP32 limits these to 31 bits
#: of unhardened space; we cap the picker much lower because numbers
#: above ~10 are almost never hit in practice and an unbounded picker
#: invites accidental bricked-feeling wallets.
_MAX_FIELD_VALUE: int = 999


# ---------------------------------------------------------------------------
# Preset chooser
# ---------------------------------------------------------------------------


HdPathPresetResult = Literal["bsv-default", "advanced", "back"]


@dataclass
class HdPathPresetChooser:
    """First screen: BSV default vs Advanced editor.

    ``result`` is one of:
      * ``"bsv-default"`` — operator accepted ``m/44'/236'/0'``.
      * ``"advanced"``    — operator wants the custom editor.
      * ``"back"``        — operator long-pressed B to bail.
    """

    title: str = "HD path"
    done: bool = False
    result: HdPathPresetResult | None = None
    _list: ListView = field(init=False)

    def __post_init__(self) -> None:
        self._list = ListView(
            title=self.title,
            items=[
                ListItem(
                    label=f"BSV default ({deriv.account_path()})",
                    value="bsv-default",
                ),
                ListItem(label="Advanced…", value="advanced"),
            ],
        )

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if event.button == Button.B and event.kind == EventKind.LONG:
            self.done = True
            self.result = "back"
            return
        self._list.on_event(event)
        chosen = self._list.confirmed
        if chosen in ("bsv-default", "advanced"):
            self.done = True
            self.result = chosen  # type: ignore[assignment]

    def draw(self, fb: FrameBuffer) -> None:
        self._list.draw(fb)
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 10,
            "A confirm   hold B cancel",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )


# ---------------------------------------------------------------------------
# Custom editor
# ---------------------------------------------------------------------------


CustomHdPathResult = Literal["confirmed", "back", "cancel"]


@dataclass
class CustomHdPathScreen:
    """Edit ``coin_type`` and ``account_index`` integers."""

    coin_type: int = deriv.BSV_COIN_TYPE
    account_index: int = deriv.DEFAULT_ACCOUNT_INDEX
    cursor: int = 0  # 0 = coin_type, 1 = account_index
    done: bool = False
    result: CustomHdPathResult | None = None
    title: str = "Custom path"

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.B and k == EventKind.LONG:
            self.done = True
            self.result = "cancel"
            return
        if b == Button.B and k == EventKind.PRESS:
            self.done = True
            self.result = "back"
            return
        if b in (Button.A, Button.SELECT) and k == EventKind.PRESS:
            self.done = True
            self.result = "confirmed"
            return
        if b == Button.UP and k in (EventKind.PRESS, EventKind.REPEAT):
            self.cursor = (self.cursor - 1) % 2
            return
        if b == Button.DOWN and k in (EventKind.PRESS, EventKind.REPEAT):
            self.cursor = (self.cursor + 1) % 2
            return
        if b == Button.LEFT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._adjust(-1)
            return
        if b == Button.RIGHT and k in (EventKind.PRESS, EventKind.REPEAT):
            self._adjust(+1)
            return

    def _adjust(self, delta: int) -> None:
        if self.cursor == 0:
            self.coin_type = max(0, min(_MAX_FIELD_VALUE, self.coin_type + delta))
        else:
            self.account_index = max(
                0, min(_MAX_FIELD_VALUE, self.account_index + delta)
            )

    @property
    def path(self) -> str:
        return deriv.account_path(self.coin_type, self.account_index)

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        title_h = 26
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

        rows = (
            ("coin_type", str(self.coin_type)),
            ("account",   str(self.account_index)),
        )
        row_h = 36
        row_y = title_h + 14
        for idx, (label, value) in enumerate(rows):
            top = row_y + idx * row_h
            is_cursor = idx == self.cursor
            if is_cursor:
                fb.draw.rectangle(
                    (0, top, DISPLAY_WIDTH, top + row_h),
                    fill=(48, 64, 96),
                )
            draw_text(fb, 14, top + row_h // 2, label, size=14, color=COLOR_FG, anchor="lm")
            draw_text(
                fb,
                DISPLAY_WIDTH - 14,
                top + row_h // 2,
                value,
                size=16,
                color=COLOR_FG if is_cursor else COLOR_DIM,
                anchor="rm",
            )

        # Live path preview, centered just above the footer.
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 50,
            self.path,
            size=12,
            color=COLOR_ACCENT,
            anchor="mm",
        )
        # Footer hints.
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 24,
            "L/R adjust   U/D field",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 10,
            "A confirm   B back   hold B cancel",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_hd_path_chooser(
    display: Display,
    input_mgr: InputManager,
    *,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
    run_screen_fn: Callable[..., object] | None = None,
) -> HdPathChoice | None:
    """Drive the preset chooser → optional custom editor.

    Returns the chosen ``(coin_type, account_index)`` tuple, or ``None``
    when the operator cancels (long-B at any layer).

    ``run_screen_fn`` lets tests inject a stub run-screen so the
    chooser logic can be exercised without an event loop. Defaults
    to :func:`piwallet.ui.app.run_screen` in production.
    """
    runner = run_screen_fn if run_screen_fn is not None else run_screen
    while True:
        preset = HdPathPresetChooser()
        runner(display, input_mgr, preset, target_fps=target_fps, idle_wake=idle_wake)
        if preset.result == "back" or preset.result is None:
            return None
        if preset.result == "bsv-default":
            return (deriv.BSV_COIN_TYPE, deriv.DEFAULT_ACCOUNT_INDEX)
        # advanced
        editor = CustomHdPathScreen()
        runner(display, input_mgr, editor, target_fps=target_fps, idle_wake=idle_wake)
        if editor.result == "confirmed":
            return (editor.coin_type, editor.account_index)
        if editor.result == "cancel":
            return None
        # editor.result == "back" → re-show the preset chooser
