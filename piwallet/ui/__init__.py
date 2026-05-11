"""PiWalletSV bonnet UI stack.

This package contains the display driver wrapper, input event
dispatcher, widget primitives, and the small main-loop helper used by
the bonnet-side flows (first-boot disclaimer, vault unlock, wallet
list, word entry, send/receive, etc.).

The implementation is split so that everything above ``display.py`` and
``input.py`` is platform-agnostic: widgets and screens accept a
``FrameBuffer`` and an injectable input stream, which lets the same
code run against the real ST7789 + GPIO buttons on a Raspberry Pi *and*
against the headless backends used in unit tests on a developer's
laptop.

See ``piwallet/ui/app.py`` for the canonical wiring example.
"""

from piwallet.ui.display import (
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    Display,
    FrameBuffer,
    HeadlessDisplay,
    open_display,
)
from piwallet.ui.input import (
    Button,
    Event,
    EventKind,
    FakeInputBackend,
    InputBackend,
    InputManager,
    open_input,
)
from piwallet.ui.pin_entry import PinEntryScreen, attempts_subtitle

__all__ = [
    "DISPLAY_HEIGHT",
    "DISPLAY_WIDTH",
    "Button",
    "Display",
    "Event",
    "EventKind",
    "FakeInputBackend",
    "FrameBuffer",
    "HeadlessDisplay",
    "InputBackend",
    "InputManager",
    "PinEntryScreen",
    "attempts_subtitle",
    "open_display",
    "open_input",
]
