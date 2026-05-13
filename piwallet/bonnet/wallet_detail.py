"""Wallet detail screen.

Shows the current receive address (text + on-screen QR), the
derivation path, and the BIP32 index. The user can step the index
with the joystick and copy the next address to the companion via
phone-camera scanning of the QR.

Derivation is performed via an injected callback so this screen
doesn't need to know about the PIN cache: the bonnet entry point
hands it ``derive_address(change, index) -> str``.

Controls
--------
=========  ==================================================
LEFT       Previous receive index (clamped at 0).
RIGHT      Next receive index.
A          Same as RIGHT (advance to a fresh address).
SELECT     Same as B PRESS (back to manage menu).
B PRESS    Back to the manage menu.
B LONG     Exit the bonnet app (returned to caller).
=========  ==================================================
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
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
from piwallet.ui.qr_render import paste_qr, render_qr
from piwallet.ui.widgets import draw_text

#: Branch index for the external (receive) chain under
#: ``m/44'/236'/0'/<change>/<index>``. 0 = external, 1 = change.
RECEIVE_BRANCH: int = 0

WalletDetailResult = Literal["back", "exit"]


@dataclass
class WalletDetailScreen:
    """Bonnet ``Screen`` for a single wallet's receive address."""

    wallet: WalletRecord
    derive_address: Callable[[int, int], str]
    index: int = 0
    done: bool = False
    result: WalletDetailResult | None = None
    qr_target_px: int = 132
    _addr_cache: dict[int, str] = field(default_factory=dict)

    # -- input handling ----------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.LEFT and k in (EventKind.PRESS, EventKind.REPEAT):
            if self.index > 0:
                self.index -= 1
        elif b in (Button.RIGHT, Button.A) and k == EventKind.PRESS:
            self.index += 1
        elif b == Button.SELECT and k == EventKind.PRESS:
            self.done = True
            self.result = "back"
        elif b == Button.B and k == EventKind.PRESS:
            self.done = True
            self.result = "back"
        elif b == Button.B and k == EventKind.LONG:
            self.done = True
            self.result = "exit"

    # -- helpers -----------------------------------------------------

    def current_address(self) -> str:
        cached = self._addr_cache.get(self.index)
        if cached is not None:
            return cached
        addr = self.derive_address(RECEIVE_BRANCH, self.index)
        self._addr_cache[self.index] = addr
        return addr

    # -- rendering ---------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        # Title bar.
        title_h = 26
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, title_h), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            title_h // 2,
            self.wallet.label or "wallet",
            size=14,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        # Receive index subtitle.
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            title_h + 10,
            f"receive #{self.index}",
            size=11,
            color=COLOR_DIM,
            anchor="mm",
        )

        # QR (centered horizontally, below subtitle).
        try:
            address = self.current_address()
        except Exception as exc:  # pragma: no cover (derivation failure)
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                DISPLAY_HEIGHT // 2,
                f"derive failed: {exc}",
                size=11,
                color=COLOR_DIM,
                anchor="mm",
            )
            return

        qr_img = render_qr(address, target_px=self.qr_target_px, border=2)
        qr_x = (DISPLAY_WIDTH - self.qr_target_px) // 2
        qr_y = title_h + 22
        paste_qr(fb.image, qr_img, x=qr_x, y=qr_y)

        # Address text below the QR — wrap into two short lines if needed.
        addr_y = qr_y + self.qr_target_px + 6
        half = len(address) // 2
        line1 = address[:half]
        line2 = address[half:]
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            addr_y,
            line1,
            size=10,
            color=COLOR_FG,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            addr_y + 12,
            line2,
            size=10,
            color=COLOR_FG,
            anchor="mm",
        )

        # Footer hints.
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 24,
            "L/R index   A next",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 10,
            "B back   hold B quit app",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
