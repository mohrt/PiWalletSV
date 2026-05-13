"""Wallet list screen.

Renders a :class:`piwallet.ui.widgets.ListView` of :class:`WalletRecord`
entries from an unlocked vault, plus two action rows ("+ New wallet"
/ "+ Restore wallet"). ``A`` confirms the highlighted row; long-press
B exits the bonnet app.

``result`` semantics:

* ``str``                    — a wallet id (operator drilled into a wallet).
* :class:`WalletListAction`  — operator picked the New or Restore action.
* ``None``                   — long-press B exit.
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
    """Non-wallet rows exposed by :class:`WalletListScreen`."""

    NEW = "new"
    RESTORE = "restore"


@dataclass
class WalletListScreen:
    """Bonnet ``Screen`` that picks a wallet (or an action) from the vault."""

    wallets: Sequence[WalletRecord]
    title: str = "Wallets"
    done: bool = False
    # Wallet id (str), WalletListAction, or None on long-B exit.
    result: object | None = None
    _list: ListView = field(init=False)

    def __post_init__(self) -> None:
        items: list[ListItem] = [
            ListItem(label=self._format_label(w), value=w.id)
            for w in self.wallets
        ]
        # Action rows always present so the user can always create or
        # restore -- even on a fresh vault (empty wallets list).
        items.append(ListItem(label="+ New wallet", value=WalletListAction.NEW))
        items.append(ListItem(label="+ Restore wallet", value=WalletListAction.RESTORE))
        self._list = ListView(items=items, title=self.title)

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
            self.result = None
            return
        self._list.on_event(event)
        if self._list.confirmed is not None:
            self.done = True
            self.result = self._list.confirmed

    def draw(self, fb: FrameBuffer) -> None:
        self._list.draw(fb)
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 9,
            "8 hex chars = xpub fingerprint",
            size=9,
            color=COLOR_DIM,
            anchor="mm",
        )
