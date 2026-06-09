"""Bonnet About screen — device and build metadata.

Reachable from Settings → **Maintenance** → **About**. Shows the
PiWalletSV logo, a short product blurb, software version, website,
wallet count, Pi board serial, and hostname.

Controls
--------
=========  ==================================================
B PRESS    Back to Maintenance.
A / SEL    Same as B PRESS — back.
=========  ==================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from PIL import Image

from piwallet import __version__ as PIWALLET_VERSION
from piwallet.bonnet.splash import load_logo
from piwallet.platform.pi_serial import read_pi_serial
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
from piwallet.ui.widgets import draw_text, wrap_text_lines

AboutResult = Literal["back"]

ABOUT_TAGLINE = "Offline BSV signing wallet."
ABOUT_WEBSITE = "https://piwalletsv.com"
ABOUT_TWITTER = "@PiWalletSV"

# Side-by-side header: logo in the left column beside name / links.
_ABOUT_LOGO_MAX = 56
_HEADER_X = 12
_TEXT_X = 76
_TAGLINE_MAX_CHARS = 28


@dataclass
class AboutScreen:
    """Read-only device / build information."""

    version: str
    tagline: str
    website: str
    twitter: str
    rows: list[tuple[str, str]]
    done: bool = False
    result: AboutResult | None = None
    _logo: Image.Image = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._logo = load_logo(max_w=_ABOUT_LOGO_MAX, max_h=_ABOUT_LOGO_MAX)

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if (b == Button.B and k == EventKind.PRESS) or (
            b in (Button.A, Button.SELECT) and k == EventKind.PRESS
        ):
            self.done = True
            self.result = "back"

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        title_h = 26
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, title_h), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            title_h // 2,
            "About",
            size=14,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        logo_y = title_h + 6
        fb.image.paste(self._logo, (_HEADER_X, logo_y))

        name_y = logo_y + 2
        draw_text(
            fb,
            _TEXT_X,
            name_y,
            "PiWalletSV",
            size=12,
            color=COLOR_ACCENT,
            anchor="la",
        )
        draw_text(
            fb,
            _TEXT_X,
            name_y + 14,
            self.version,
            size=10,
            color=COLOR_DIM,
            anchor="la",
        )
        draw_text(
            fb,
            _TEXT_X,
            name_y + 28,
            self.website,
            size=9,
            color=COLOR_DIM,
            anchor="la",
        )
        draw_text(
            fb,
            _TEXT_X,
            name_y + 40,
            self.twitter,
            size=9,
            color=COLOR_DIM,
            anchor="la",
        )

        header_bottom = max(logo_y + self._logo.height, name_y + 52)
        y = header_bottom + 6
        for line in wrap_text_lines(self.tagline, max_chars=_TAGLINE_MAX_CHARS):
            draw_text(fb, _HEADER_X, y, line, size=9, color=COLOR_DIM, anchor="la")
            y += 13

        y += 4
        for key, value in self.rows:
            draw_text(fb, _HEADER_X, y, key, size=10, color=COLOR_DIM, anchor="la")
            draw_text(
                fb,
                DISPLAY_WIDTH - _HEADER_X,
                y,
                value,
                size=10,
                color=COLOR_FG,
                anchor="ra",
            )
            y += 22

        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 10,
            "A/B: back",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )


def build_about_screen(*, wallet_count: int) -> AboutScreen:
    """Construct an :class:`AboutScreen` from live device state."""
    serial = read_pi_serial()
    rows: list[tuple[str, str]] = [
        ("Wallets", str(wallet_count)),
        ("Serial", _truncate(serial or "—", 16)),
        ("Host", _truncate(_hostname(), 16)),
    ]
    return AboutScreen(
        version=f"v{PIWALLET_VERSION}",
        tagline=ABOUT_TAGLINE,
        website=ABOUT_WEBSITE,
        twitter=ABOUT_TWITTER,
        rows=rows,
    )


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _hostname() -> str:
    try:
        import platform

        return platform.node() or "—"
    except Exception:
        return "—"
