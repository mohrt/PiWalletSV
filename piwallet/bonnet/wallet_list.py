"""Wallet list screen.

Renders a :class:`piwallet.ui.widgets.ListView` of :class:`WalletRecord`
entries from an unlocked vault. A confirms the highlighted wallet
(returning its id via ``result``); long-press B exits the bonnet app
(returning ``None``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from piwallet.core.vault import WalletRecord
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import ListItem, ListView


@dataclass
class WalletListScreen:
    """Bonnet ``Screen`` that picks a wallet from the vault."""

    wallets: Sequence[WalletRecord]
    title: str = "Wallets"
    done: bool = False
    # Set to the chosen wallet id on confirm, or None on long-B exit.
    result: object | None = None
    _list: ListView = field(init=False)

    def __post_init__(self) -> None:
        if self.wallets:
            items = [
                ListItem(
                    label=self._format_label(w),
                    value=w.id,
                )
                for w in self.wallets
            ]
        else:
            items = [
                ListItem(label="(no wallets yet)", value=None, disabled=True),
            ]
        self._list = ListView(items=items, title=self.title)

    @staticmethod
    def _format_label(w: WalletRecord) -> str:
        fp4 = w.fingerprint.hex()[:8]
        return f"{w.label}  {fp4}"

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
