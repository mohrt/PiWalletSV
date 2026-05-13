"""Wallet list screen.

Renders a :class:`piwallet.ui.widgets.ListView` of :class:`WalletRecord`
entries from an unlocked vault, plus two CTA rows ("+ New wallet" and
"+ Restore wallet"). ``A`` confirms the highlighted row; long-press B
exits the bonnet app; long-press SELECT (joystick centre) opens the
global Settings screen so it doesn't take up a list row alongside the
operator's actual wallets.

``result`` semantics:

* ``str``                    — a wallet id (operator drilled into a wallet).
* :class:`WalletListAction`  — operator picked New, Restore, or Settings
                               (the latter via SELECT long-press).
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
    """Non-wallet rows / gestures exposed by :class:`WalletListScreen`."""

    NEW = "new"
    RESTORE = "restore"
    #: Reached via long-press SELECT, *not* a list row. The enum stays
    #: in case future UX surfaces it as an item again, and to keep the
    #: bonnet boot loop's dispatch type stable.
    SETTINGS = "settings"


@dataclass
class WalletListScreen:
    """Bonnet ``Screen`` that picks a wallet (or an action) from the vault.

    Settings is *not* a list row — it would visually masquerade as a
    wallet next to real wallet labels. Instead, long-pressing the
    joystick centre (SELECT) jumps to the Settings screen. This keeps
    the wallet list unambiguous and uses an otherwise-idle gesture
    (regular SELECT already confirms the highlighted row).
    """

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
        # CTA rows always present so the user can always create or
        # restore — even on a fresh vault (empty wallets list).
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
        if event.button == Button.SELECT and event.kind == EventKind.LONG:
            self.done = True
            self.result = WalletListAction.SETTINGS
            return
        self._list.on_event(event)
        if self._list.confirmed is not None:
            self.done = True
            self.result = self._list.confirmed

    def draw(self, fb: FrameBuffer) -> None:
        self._list.draw(fb)
        # Two muted footer hints: top one is the ambient gestures
        # (settings + quit) so they're discoverable without crowding
        # the row labels; bottom one keeps the existing fp legend.
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 22,
            "hold SEL settings   hold B quit",
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
