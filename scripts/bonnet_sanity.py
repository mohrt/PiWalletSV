#!/usr/bin/env python3
"""Bonnet display + input bring-up smoke test.

Run this on the Pi BEFORE `piwallet bonnet` to confirm:

1. SPI is enabled and the ST7789 panel paints.
2. The joystick + A/B buttons map to the expected logical buttons.

Usage::

    .venv/bin/python scripts/bonnet_sanity.py
    .venv/bin/python scripts/bonnet_sanity.py --display-only
    .venv/bin/python scripts/bonnet_sanity.py --input-only

Press CTRL-C to exit.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time

from piwallet.ui.app import make_input_manager
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_FG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FrameBuffer,
    open_display,
)
from piwallet.ui.input import open_input
from piwallet.ui.widgets import draw_text


def _color_bars(display) -> None:
    fb = FrameBuffer()
    bar_w = DISPLAY_WIDTH // 6
    colors = [
        (255, 0, 0), (255, 165, 0), (255, 255, 0),
        (0, 200, 0), (0, 120, 255), (180, 0, 255),
    ]
    for i, c in enumerate(colors):
        x0 = i * bar_w
        fb.draw.rectangle((x0, 0, x0 + bar_w, DISPLAY_HEIGHT), fill=c)
    draw_text(
        fb,
        DISPLAY_WIDTH // 2,
        DISPLAY_HEIGHT - 16,
        "color bars - press CTRL-C to exit",
        size=11,
        color=(0, 0, 0),
        anchor="mm",
    )
    display.flip(fb)


def _crosshair(display) -> None:
    fb = FrameBuffer()
    fb.clear(COLOR_BG)
    cx, cy = DISPLAY_WIDTH // 2, DISPLAY_HEIGHT // 2
    fb.draw.line((0, cy, DISPLAY_WIDTH, cy), fill=COLOR_FG)
    fb.draw.line((cx, 0, cx, DISPLAY_HEIGHT), fill=COLOR_FG)
    fb.draw.rectangle((0, 0, DISPLAY_WIDTH - 1, DISPLAY_HEIGHT - 1), outline=COLOR_ACCENT, width=2)
    draw_text(fb, cx, 20, "crosshair test", size=12, color=COLOR_ACCENT, anchor="mm")
    draw_text(
        fb,
        cx,
        DISPLAY_HEIGHT - 18,
        "if you see a + and a border, SPI + ST7789 work",
        size=10,
        color=COLOR_FG,
        anchor="mm",
    )
    display.flip(fb)


def _open(display_kind: str, rotation: int):
    """Build an ST7789 display with a tunable rotation, or whatever the
    `open_display` factory picks for non-st7789 kinds."""
    if display_kind == "st7789":
        from piwallet.ui.display import ST7789Display
        return ST7789Display(rotation=rotation)
    if display_kind == "auto":
        try:
            from piwallet.ui.display import ST7789Display
            return ST7789Display(rotation=rotation)
        except RuntimeError:
            return open_display("headless")
    return open_display(display_kind)


def run_display_test(display_kind: str, rotation: int) -> None:
    print(f"opening display: {display_kind} (rotation={rotation})")
    display = _open(display_kind, rotation)
    try:
        for name, fn in (("color bars", _color_bars), ("crosshair", _crosshair)):
            print(f"  painting: {name}")
            fn(display)
            time.sleep(2.0)
    finally:
        display.close()


def run_input_test(input_kind: str, display_kind: str | None, rotation: int) -> None:
    print(f"opening input backend: {input_kind}")
    backend = open_input(input_kind)
    mgr = make_input_manager(backend, repeat_ms=120, long_ms=700)

    display = _open(display_kind, rotation) if display_kind else None
    fb = FrameBuffer() if display else None

    last_label = "(press any button)"
    print("waiting for input events (CTRL-C to exit)...")
    try:
        while True:
            events = mgr.poll()
            for ev in events:
                tag = f"{ev.button.name:<6} {ev.kind.name:<8} at {ev.at_ms:>6} ms"
                print(tag)
                last_label = f"{ev.button.name} {ev.kind.name}"
            if fb is not None and display is not None:
                fb.clear(COLOR_BG)
                draw_text(
                    fb,
                    DISPLAY_WIDTH // 2,
                    DISPLAY_HEIGHT // 2 - 8,
                    "last event:",
                    size=12,
                    color=COLOR_FG,
                    anchor="mm",
                )
                draw_text(
                    fb,
                    DISPLAY_WIDTH // 2,
                    DISPLAY_HEIGHT // 2 + 14,
                    last_label,
                    size=14,
                    color=COLOR_ACCENT,
                    anchor="mm",
                )
                display.flip(fb)
            time.sleep(0.03)
    except KeyboardInterrupt:
        pass
    finally:
        if display is not None:
            display.close()
        with contextlib.suppress(Exception):
            backend.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display-only", action="store_true")
    parser.add_argument("--input-only", action="store_true")
    parser.add_argument("--display", default="auto", choices=["auto", "st7789", "headless"])
    parser.add_argument("--input", default="auto", choices=["auto", "bonnet", "fake"])
    parser.add_argument(
        "--rotation",
        type=int,
        default=180,
        choices=[0, 90, 180, 270],
        help="ST7789 panel rotation in degrees (default: 180 for Adafruit 4506).",
    )
    args = parser.parse_args()

    if args.input_only:
        run_input_test(args.input, args.display, args.rotation)
        return
    run_display_test(args.display, args.rotation)
    if not args.display_only:
        run_input_test(args.input, args.display, args.rotation)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
