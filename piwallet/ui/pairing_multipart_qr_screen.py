"""Rotate PW1 multipart lines as full-screen QR codes for companion pairing.

Each frame encodes one ``PW1|...`` barcode string (:mod:`piwallet.qr.multipart`).
The companion app scans an animated sequence; this screen advances
automatically between frames.

Layout note
-----------
Title bar and footer are kept intentionally tiny so the QR ink can fill
~196 px of the 240 x 240 panel. With 100-char chunks and error="L" each
frame lands at QR version 7 (45 modules, 45+4=49 bordered) rendered at
floor(200/49)=4 px per module — comfortably above the threshold a phone
camera needs to autofocus through the TFT's backlight glow.

Controls
--------
========= ==================================================
UP / DOWN Brighter / dimmer QR background (saved for next time).
A / B Back to the parent screen.
SELECT Same as A / B.
========= ==================================================
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIM,
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
    qr_footer_y,
)
from piwallet.ui.qr_render import (
    fill_qr_panel_background,
    paste_qr_matte,
    qr_panel_content_bottom_y,
    render_qr,
)
from piwallet.ui.widgets import draw_text

PairingMultipartQrResult = Literal["back"]


def _wall_mono_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _max_qr_px_for_footer(*, qr_top_y: int, first_footer_center_y: int, gap_px: int) -> int:
    """Keep QR bottom edge at least ``gap_px`` below the ink of the first footer line.

    Footer lines use ``anchor=mm``; reserve ~6 px below the QR for descenders/gap.
    """
    margin = 6
    limit_y = first_footer_center_y - margin - gap_px
    return max(32, min(DISPLAY_HEIGHT, limit_y) - qr_top_y)


@dataclass
class PairingMultipartQrScreen:
    """Show ``pw1_frames`` as QR tiles with timed auto-advance.

    ``qr_target_px`` is large by design: phone cameras have to
    autofocus through the bonnet's TFT glow, and the difference
    between a v6 QR rendered at 3 px/module vs 4 px/module is the
    difference between "scans on every frame" and "doesn't scan at
    all" at arm's length. The screen squeezes the title bar and
    collapses the three control hints into a single footer line so
    the QR ink can fill ~196 px of the 240 px panel.
    """

    pw1_frames: list[str]
    title: str = "Pair companion"
    # 700 ms / frame leaves the phone scanner enough time to autofocus
    # on a fresh QR, decode it, and update its received-frame set
    # before the panel rotates. The earlier 420 ms default produced
    # cycles too fast for arm's-length scanning under indoor light.
    auto_advance_ms: int = 700
    qr_target_px: int = 200
    qr_background: int = DEFAULT_QR_BACKGROUND
    on_qr_background_changed: Callable[[int], None] | None = None
    idx: int = 0
    done: bool = False
    result: PairingMultipartQrResult | None = None
    clock_ms: Callable[[], int] | None = None
    _next_advance_after_ms: int = field(init=False, repr=False)
    _mono: Callable[[], int] = field(init=False, repr=False)
    _brightness_hint: QrBrightnessHint = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.pw1_frames:
            raise ValueError("pw1_frames must be non-empty")
        self._mono = self.clock_ms if self.clock_ms is not None else _wall_mono_ms
        now = self._mono()
        self._next_advance_after_ms = now + self.auto_advance_ms
        self._brightness_hint = QrBrightnessHint(clock_ms=self._mono)

    # -- Input -------------------------------------------------------

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        new_level = try_qr_brightness_event(
            event,
            self.qr_background,
            on_changed=self.on_qr_background_changed,
        )
        if new_level is not None:
            self.qr_background = new_level
            self._brightness_hint.refresh()
            # Restart the sequence so the phone gets fresh frames at the
            # new contrast after a brightness change.
            self.idx = 0
            self._next_advance_after_ms = self._mono() + self.auto_advance_ms
            return
        if (b == Button.B and k == EventKind.PRESS) or (
            b in (Button.A, Button.SELECT) and k == EventKind.PRESS
        ):
            self.done = True
            self.result = "back"

    # -- Render -------------------------------------------------------

    def draw(self, fb: FrameBuffer) -> None:
        now = self._mono()
        n = len(self.pw1_frames)
        hint_visible = self._brightness_hint.visible()
        if n > 1 and not hint_visible and now >= self._next_advance_after_ms:
            self.idx = (self.idx + 1) % n
            self._next_advance_after_ms = now + self.auto_advance_ms

        fb.clear(COLOR_BG)
        title_h = 18
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, title_h), fill=(20, 20, 32))
        # Single header line so most vertical space goes to the QR.
        head = f"{self.title} {self.idx + 1} / {n}"
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            title_h // 2,
            head,
            size=11,
            color=COLOR_ACCENT,
            anchor="mm",
        )
        qr_y = title_h + 4
        footer_y = qr_footer_y()
        matte_rgb = qr_background_rgb(self.qr_background)
        fill_qr_panel_background(fb, top_y=title_h, matte_color=matte_rgb)
        eff_px = min(
            self.qr_target_px,
            _max_qr_px_for_footer(
                qr_top_y=qr_y,
                first_footer_center_y=footer_y,
                gap_px=6,
            ),
        )
        line = self.pw1_frames[self.idx]
        try:
            qr_img = render_qr(
                line,
                target_px=eff_px,
                border=2,
                error="L",
                bg=matte_rgb,
            )
            qr_x = (DISPLAY_WIDTH - eff_px) // 2
            paste_qr_matte(
                fb.image,
                qr_img,
                x=qr_x,
                y=qr_y,
                matte_pad=8,
                matte_color=matte_rgb,
            )
        except Exception as exc:  # pragma: no cover (segno edge)
            draw_text(
                fb,
                DISPLAY_WIDTH // 2,
                qr_y + eff_px // 2,
                f"QR error:\n{exc!s}"[:96],
                size=10,
                color=COLOR_DIM,
                anchor="mm",
            )

        if hint_visible:
            draw_qr_brightness_toast(fb, bottom_y=qr_panel_content_bottom_y())

        draw_qr_screen_footer(fb)
