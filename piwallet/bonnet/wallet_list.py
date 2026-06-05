"""Wallet list screen.

Renders a :class:`piwallet.ui.widgets.ListView` of :class:`WalletRecord`
entries from an unlocked vault, plus two CTA rows ("+ New wallet" and
"+ Restore wallet"). ``A`` confirms the highlighted row; a short ``B`` opens Settings.

``result`` semantics:

* ``str``                    — a wallet id (operator drilled into a wallet).
* :class:`WalletListAction`  — operator picked New, Restore, or Settings.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from piwallet.core.vault import WalletRecord
from piwallet.ui.display import DISPLAY_HEIGHT, DISPLAY_WIDTH, FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import ListItem, ListView


class WalletListAction(Enum):
    """Non-wallet rows / gestures exposed by :class:`WalletListScreen`."""

    NEW = "new"
    RESTORE = "restore"
    SETTINGS = "settings"


@dataclass
class WalletListScreen:
    """Bonnet ``Screen`` that picks a wallet (or an action) from the vault."""

    wallets: Sequence[WalletRecord]
    title: str = "Wallets"
    done: bool = False
    # Wallet id (str) or :class:`WalletListAction`.
    result: object | None = None
    _list: ListView = field(init=False)
    _b_pressed_here: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        items: list[ListItem] = [
            ListItem(label=self._format_label(w), value=w.id)
            for w in self.wallets
        ]
        items.append(ListItem(label="+ New wallet", value=WalletListAction.NEW))
        items.append(ListItem(label="+ Restore wallet", value=WalletListAction.RESTORE))
        self._list = ListView(
            items=items,
            title=self.title,
            footer="A: select   B: settings",
        )

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
        if event.button == Button.B:
            if event.kind == EventKind.PRESS:
                self._b_pressed_here = True
                return
            if event.kind == EventKind.RELEASE:
                if self._b_pressed_here:
                    self.done = True
                    self.result = WalletListAction.SETTINGS
                self._b_pressed_here = False
                return
        self._list.on_event(event)
        if self._list.confirmed is not None:
            self.done = True
            self.result = self._list.confirmed

    def draw(self, fb: FrameBuffer) -> None:
        self._list.draw(fb)
