"""Wallet list screen.

Renders a :class:`piwallet.ui.widgets.ListView` of :class:`WalletRecord`
entries from an unlocked vault, plus two CTA rows ("+ New wallet" and
"+ Restore wallet"). ``A`` confirms the highlighted row; long-press
B (the only otherwise-unused gesture at this top level) opens the
global Settings screen, keeping it out of the row list so it doesn't
masquerade as a wallet.

There is intentionally no "quit the app" gesture here — the bonnet is
a service the operator just powers down; an in-UI exit was a usability
trap (it competed with the long-press SELECT we used for Settings, and
operators kept hitting it by accident).

``result`` semantics:

* ``str``                    — a wallet id (operator drilled into a wallet).
* :class:`WalletListAction`  — operator picked New, Restore, or Settings.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from piwallet.core.vault import WalletRecord
from piwallet.ui.display import COLOR_DIM, DISPLAY_HEIGHT, DISPLAY_WIDTH, FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import ListItem, ListView, draw_text


class WalletListAction(Enum):
    """Non-wallet rows / gestures exposed by :class:`WalletListScreen`."""

    NEW = "new"
    RESTORE = "restore"
    #: Reached via long-press B, *not* a list row. The enum stays
    #: in case future UX surfaces it as an item again, and to keep the
    #: bonnet boot loop's dispatch type stable.
    SETTINGS = "settings"


@dataclass
class WalletListScreen:
    """Bonnet ``Screen`` that picks a wallet (or an action) from the vault.

    Settings is *not* a list row — it would visually masquerade as a
    wallet next to real wallet labels. Instead, **long-press B** jumps
    to the Settings screen. We picked B-long because:

    * Short-press SELECT must keep its existing semantics ("confirm the
      highlighted row → open this wallet"). On an STK1 joystick the
      input layer fires PRESS first and LONG only on hold; if SELECT
      were the settings gesture the screen would commit to opening the
      highlighted wallet before LONG ever fired.
    * B has nowhere to "go back" to from the top level, so a long-press
      B is otherwise idle here.
    """

    wallets: Sequence[WalletRecord]
    title: str = "Wallets"
    done: bool = False
    # Wallet id (str) or :class:`WalletListAction`.
    result: object | None = None
    _list: ListView = field(init=False)

    def __post_init__(self) -> None:
        items: list[ListItem] = [
            ListItem(label=self._format_label(w), value=w.id)
            for w in self.wallets
        ]
        # CTA rows always present so the user can always create or
        # restore — even on a fresh vault (empty wallets list).
        items.append(ListItem(label="+ New wallet", value=WalletListAction.NEW))
        items.append(ListItem(label="+ Restore wallet", value=WalletListAction.RESTORE))
        self._list = ListView(items=items, title=self.title, footer="A: select   B: exit")

    @staticmethod
    def _format_label(w: WalletRecord) -> str:
        fp8 = w.fingerprint.hex()[:8]
        return f"{w.label}  {fp8}"

    @property
    def cursor(self) -> int:
        return self._list.cursor

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if event.button == Button.B and event.kind == EventKind.LONG:
            self.done = True
            self.result = WalletListAction.SETTINGS
            return
        self._list.on_event(event)
        if self._list.confirmed is not None:
            self.done = True
            self.result = self._list.confirmed

    def draw(self, fb: FrameBuffer) -> None:
        self._list.draw(fb)
        # Two muted footer hints: settings gesture + fingerprint legend.
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 22,
            "hold B  settings",
            size=9,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 9,
            "8 hex chars = xpub fingerprint",
            size=9,
            color=COLOR_DIM,
            anchor="mm",
        )
