"""Bonnet "Wallet info" read-only metadata screen.

Surfaces a wallet's HD derivation path, xpub fingerprint, BIP39 word
count, and creation timestamp. Reachable from the wallet manage menu;
it never derives keys or touches the encrypted xprv, so opening it
costs nothing and doesn't require the PIN.

The screen is deliberately read-only. Editing a wallet's HD path
*after* creation would silently re-derive every address — every
on-chain UTXO at the old path would become invisible to the
companion until manually rescanned at the new path, and balances
would appear to vanish. Picking the path is therefore confined to
the create-wallet flow; this screen exists so operators can audit
*which* path a wallet is using.

Controls
--------
=========  ==================================================
B PRESS    Back to the manage menu.
B LONG     Exit the bonnet app entirely.
A / SEL    Same as B PRESS — back.
=========  ==================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from piwallet.core.vault import WalletRecord
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

WalletInfoResult = Literal["back", "exit"]


@dataclass
class WalletInfoScreen:
    """Static wallet-metadata viewer."""

    wallet: WalletRecord
    done: bool = False
    result: WalletInfoResult | None = None

    # -- input -------------------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.B and k == EventKind.LONG:
            self.done = True
            self.result = "exit"
            return
        if (b == Button.B and k == EventKind.PRESS) or (
            b in (Button.A, Button.SELECT) and k == EventKind.PRESS
        ):
            self.done = True
            self.result = "back"

    # -- render ------------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        title_h = 26
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, title_h), fill=(20, 20, 32))
        label = self.wallet.label.strip() or "wallet"
        stub = label[:18] + ("…" if len(label) > 18 else "")
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            title_h // 2,
            stub,
            size=14,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        # Two-column layout: label on the left, value on the right.
        rows: list[tuple[str, str]] = [
            ("HD path", self.wallet.derivation_path),
            ("Fingerprint", self.wallet.fingerprint.hex()),
            ("Words", str(self.wallet.word_count)),
            ("Created", self._format_created_at(self.wallet.created_at)),
        ]

        y = title_h + 14
        for key, value in rows:
            draw_text(fb, 14, y, key, size=12, color=COLOR_DIM, anchor="lm")
            draw_text(
                fb,
                DISPLAY_WIDTH - 14,
                y,
                value,
                size=12,
                color=COLOR_FG,
                anchor="rm",
            )
            y += 26

        # Footer hints.
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 24,
            "Path is fixed at create time",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 10,
            "A / B back   hold B quit app",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )

    @staticmethod
    def _format_created_at(iso: str) -> str:
        """Trim ISO 8601 to the calendar date for compact display."""
        # Show just the YYYY-MM-DD prefix; the full timestamp is too
        # long for the column width and the time-of-day isn't useful
        # to the operator at this point.
        return iso.split("T", 1)[0] if "T" in iso else iso[:10]
