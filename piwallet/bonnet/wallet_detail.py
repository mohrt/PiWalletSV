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
UP / DOWN  Brighter / dimmer QR background (saved for next time).
A / B      Back to the manage menu.
SELECT     Same as A / B.
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
from piwallet.ui.qr_brightness import (
    DEFAULT_QR_BACKGROUND,
    qr_background_rgb,
    try_qr_brightness_event,
)
from piwallet.ui.qr_brightness_ui import (
    QrBrightnessHint,
    draw_qr_brightness_toast,
    draw_qr_screen_footer,
)
from piwallet.ui.qr_render import fill_qr_panel_background, paste_qr_matte, render_qr
from piwallet.ui.widgets import draw_text

#: Branch index for the external (receive) chain under
#: ``m/44'/236'/0'/<change>/<index>``. 0 = external, 1 = change.
RECEIVE_BRANCH: int = 0

WalletDetailResult = Literal["back"]


@dataclass
class WalletDetailScreen:
    """Bonnet ``Screen`` for a single wallet's receive address."""

    wallet: WalletRecord
    derive_address: Callable[[int, int], str]
    index: int = 0
    done: bool = False
    result: WalletDetailResult | None = None
    qr_target_px: int = 148
    qr_background: int = DEFAULT_QR_BACKGROUND
    on_qr_background_changed: Callable[[int], None] | None = None
    _addr_cache: dict[int, str] = field(default_factory=dict)
    _brightness_hint: QrBrightnessHint = field(default_factory=QrBrightnessHint)

    # -- input handling ----------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.LEFT and k in (EventKind.PRESS, EventKind.REPEAT):
            if self.index > 0:
                self.index -= 1
        elif b == Button.RIGHT and k in (EventKind.PRESS, EventKind.REPEAT):
            self.index += 1
        else:
            new_level = try_qr_brightness_event(
                event,
                self.qr_background,
                on_changed=self.on_qr_background_changed,
            )
            if new_level is not None:
                self.qr_background = new_level
                self._brightness_hint.refresh()
                return
        if (b == Button.B and k == EventKind.PRESS) or (
            b in (Button.A, Button.SELECT) and k == EventKind.PRESS
        ):
            self.done = True
            self.result = "back"

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
        # Receive index — right-aligned inside the title bar so it's always
        # visible against the dark title background (not the QR matte).
        draw_text(
            fb,
            DISPLAY_WIDTH - 6,
            title_h // 2,
            f"#{self.index}",
            size=11,
            color=COLOR_DIM,
            anchor="rm",
        )

        matte_rgb = qr_background_rgb(self.qr_background)
        fill_qr_panel_background(fb, top_y=title_h, matte_color=matte_rgb)

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

        qr_img = render_qr(
            address,
            target_px=self.qr_target_px,
            border=2,
            bg=qr_background_rgb(self.qr_background),
        )
        qr_x = (DISPLAY_WIDTH - self.qr_target_px) // 2
        qr_y = title_h + 22
        paste_qr_matte(
            fb.image,
            qr_img,
            x=qr_x,
            y=qr_y,
            matte_color=matte_rgb,
        )

        if self._brightness_hint.visible():
            draw_qr_brightness_toast(fb, bottom_y=qr_y + self.qr_target_px + 36)

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

        draw_qr_screen_footer(fb, back_label="L/R index   A/B back")
