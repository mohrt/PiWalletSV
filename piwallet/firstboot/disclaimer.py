"""Bonnet disclaimer screen.

The flow is three pages of plain-English warnings. The user navigates
left/right with the joystick and accepts on the final page by *holding*
button A. Holding B at any point cancels the flow (returning ``False``).

The "hold to accept" interaction mirrors the PWA's checkbox: it's a
deliberate, two-handed gesture the user can't trip over while
fumbling the device.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import Modal, draw_text


@dataclass(frozen=True, slots=True)
class DisclaimerPage:
    title: str
    body: str
    footer: str


DEFAULT_DISCLAIMER_PAGES: tuple[DisclaimerPage, ...] = (
    DisclaimerPage(
        title="Alpha software",
        body=(
            "PiWalletSV is alpha. Expect bugs. Use only with funds "
            "you can afford to lose."
        ),
        footer="JOYSTICK > next",
    ),
    DisclaimerPage(
        title="Your mnemonic",
        body=(
            "Your seed phrase is the ONLY way to recover funds. "
            "Keep it offline. Don't share. Don't photograph."
        ),
        footer="< back   |   next >",
    ),
    DisclaimerPage(
        title="No liability",
        body=(
            "Authors disclaim all liability. Use at your own risk. "
            "Commercial kit/case resale needs permission (@PiWalletSV). "
            "Hold A to accept."
        ),
        footer="< back   |   HOLD A to accept",
    ),
)


def _default_clock_ms() -> int:
    return time.monotonic_ns() // 1_000_000


@dataclass
class DisclaimerScreen:
    """Bonnet ``Screen`` for the three-page disclaimer.

    Attributes
    ----------
    pages : sequence of :class:`DisclaimerPage`
        Pages to walk through. Defaults to :data:`DEFAULT_DISCLAIMER_PAGES`.
    clock_ms : callable
        Returns monotonic milliseconds. Injected for tests.
    hold_target_ms : int
        How long button A must be held on the final page. Must match
        the :class:`InputManager`'s ``long_ms`` setting so the visual
        progress bar fills in lockstep with the LONG event firing.
    """

    pages: tuple[DisclaimerPage, ...] = DEFAULT_DISCLAIMER_PAGES
    clock_ms: Callable[[], int] = field(default=_default_clock_ms)
    hold_target_ms: int = 700

    page: int = 0
    done: bool = False
    result: object | None = None  # True on accept, False on bail, None while live

    # Internal: when did the user start holding A on the final page?
    _a_pressed_at: int | None = field(default=None, repr=False)

    # -- input handling -----------------------------------------------

    def on_event(self, event: Event) -> None:
        b = event.button
        k = event.kind
        last_page = len(self.pages) - 1

        if b == Button.RIGHT and k in (EventKind.PRESS, EventKind.REPEAT):
            if self.page < last_page:
                self.page += 1
                self._a_pressed_at = None
        elif b == Button.LEFT and k in (EventKind.PRESS, EventKind.REPEAT):
            if self.page > 0:
                self.page -= 1
                self._a_pressed_at = None
        elif b == Button.A:
            if k == EventKind.PRESS and self.page == last_page:
                self._a_pressed_at = event.at_ms
            elif k == EventKind.RELEASE:
                self._a_pressed_at = None
            elif k == EventKind.LONG and self.page == last_page:
                self.done = True
                self.result = True
        elif b == Button.B and k == EventKind.LONG:
            # Long-press B from any page bails the flow.
            self.done = True
            self.result = False

    # -- rendering ----------------------------------------------------

    def hold_progress(self) -> float:
        """Fraction (0..1) of the way through the hold-A gesture."""
        if self._a_pressed_at is None or self.page != len(self.pages) - 1:
            return 0.0
        elapsed = self.clock_ms() - self._a_pressed_at
        return max(0.0, min(1.0, elapsed / max(1, self.hold_target_ms)))

    def draw(self, fb: FrameBuffer) -> None:
        last_page = len(self.pages) - 1
        page = self.pages[self.page]
        accent = COLOR_DANGER if self.page == last_page else COLOR_ACCENT

        Modal(
            title=page.title,
            body=page.body,
            footer=page.footer,
            accent=accent,
        ).draw(fb)

        # Page indicator dots above the footer.
        self._draw_dots(fb)

        # Hold-A progress bar on the final page.
        if self.page == last_page:
            self._draw_hold_progress(fb)

    def _draw_dots(self, fb: FrameBuffer) -> None:
        dot_y = DISPLAY_HEIGHT - 40
        spacing = 14
        dot_r = 4
        total = len(self.pages)
        x0 = DISPLAY_WIDTH // 2 - (total - 1) * spacing // 2
        for i in range(total):
            color = COLOR_ACCENT if i == self.page else COLOR_DIM
            x = x0 + i * spacing
            fb.draw.ellipse(
                (x - dot_r, dot_y - dot_r, x + dot_r, dot_y + dot_r),
                fill=color,
            )

    def _draw_hold_progress(self, fb: FrameBuffer) -> None:
        progress = self.hold_progress()
        if progress <= 0:
            return
        pad = 20
        bar_y = DISPLAY_HEIGHT - 56
        bar_h = 6
        fb.draw.rectangle(
            (pad, bar_y, DISPLAY_WIDTH - pad, bar_y + bar_h),
            fill=(40, 40, 48),
            outline=COLOR_DIM,
        )
        fill_w = round((DISPLAY_WIDTH - 2 * pad) * progress)
        if fill_w > 0:
            fb.draw.rectangle(
                (pad, bar_y, pad + fill_w, bar_y + bar_h),
                fill=COLOR_DANGER,
            )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            bar_y - 8,
            "holding...",
            size=10,
            color=COLOR_FG,
            anchor="mm",
        )
