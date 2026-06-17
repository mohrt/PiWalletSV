"""Early-boot panel status — show activity before the full bonnet app starts.

``piwallet-boot-status.service`` runs this during first-boot package purge
and other multi-user startup work so the TFT is not dark for 60–120 s.

The main ``piwallet-bonnet`` unit stops this service before opening the
display for the logo splash / disclaimer flow.
"""

from __future__ import annotations

import signal
import sys
import time

from piwallet.ui.display import COLOR_BG, COLOR_DIM, COLOR_FG, Display, FrameBuffer, open_display
from piwallet.ui.widgets import draw_text


def paint_boot_status(
    display: Display,
    fb: FrameBuffer,
    *,
    title: str = "PiWalletSV",
    subtitle: str = "Booting",
    anim_frame: int = 0,
) -> None:
    """Draw the boot status screen into ``fb`` and push it to ``display``."""
    fb.clear(COLOR_BG)
    draw_text(fb, 120, 96, title, size=14, color=COLOR_FG, anchor="mm")
    dots = "." * (anim_frame % 4)
    draw_text(fb, 120, 122, f"{subtitle}{dots}", size=12, color=COLOR_DIM, anchor="mm")
    display.flip(fb)


def show_boot_status(display: Display, *, subtitle: str = "Booting") -> None:
    """Paint one boot-status frame (used by ``run_bonnet`` after display open)."""
    fb = FrameBuffer()
    paint_boot_status(display, fb, subtitle=subtitle, anim_frame=0)


def run_boot_status_loop(
    display: Display,
    *,
    subtitle: str = "Booting",
    frame_interval_s: float = 0.25,
) -> None:
    """Animate boot status until SIGTERM/SIGINT."""
    running = True

    def _stop(*_args: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    display.set_backlight(True)
    display.set_brightness(1.0)
    frame = 0
    fb = FrameBuffer()
    try:
        while running:
            paint_boot_status(display, fb, subtitle=subtitle, anim_frame=frame)
            frame += 1
            time.sleep(frame_interval_s)
    finally:
        display.set_backlight(False)
        display.close()


def main() -> int:
    try:
        display = open_display("st7789")
    except RuntimeError as exc:
        print(f"boot-status: display init failed: {exc}", file=sys.stderr)
        return 1
    run_boot_status_loop(display)
    return 0


if __name__ == "__main__":
    sys.exit(main())
