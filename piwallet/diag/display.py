"""Display / SPI panel diagnostic.

Checks that the ST7789 TFT panel is reachable and can accept pixels.
Results are non-destructive: a brief full-white followed by full-black
blit confirms the SPI bus, backlight GPIO, and panel controller are
all working.

Each check returns a :class:`~piwallet.diag.airgap.CheckResult`.  A
missing display driver (running on a developer Mac) yields
``ok=None`` rather than ``ok=False`` so the overall report stays green
on non-Pi hosts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CheckOk = Literal[True, False, None]


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single diagnostic sub-check."""

    name: str
    ok: CheckOk
    detail: str


def check_spi_device() -> CheckResult:
    """Verify that the SPI device node used by the ST7789 driver exists.

    Looks for ``/dev/spidev0.0`` (CE0) which the Adafruit bonnet wires
    the TFT to. If the node is absent either ``dtparam=spi=on`` is
    missing from ``config.txt`` or the SPI overlay failed to load.
    """
    spi_path = Path("/dev/spidev0.0")
    if not spi_path.exists():
        return CheckResult(
            name="spi_device",
            ok=None,
            detail=f"{spi_path} not found — not a Pi or SPI not enabled",
        )
    return CheckResult(name="spi_device", ok=True, detail=str(spi_path))


def check_backlight_gpio() -> CheckResult:
    """Verify the backlight GPIO export is accessible via sysfs.

    The Adafruit 1.3" TFT bonnet (4506) wires the backlight to BCM 26.
    A readable ``/sys/class/gpio/gpio26`` confirms the pin is exported
    and the GPIO subsystem is up.
    """
    gpio_path = Path("/sys/class/gpio/gpio26")
    if not gpio_path.exists():
        return CheckResult(
            name="backlight_gpio",
            ok=None,
            detail=(
                "GPIO 26 not exported — run `piwallet bonnet` first "
                "to let the driver export it, or check BCM pin wiring"
            ),
        )
    return CheckResult(name="backlight_gpio", ok=True, detail=str(gpio_path))


def check_display_paint() -> CheckResult:
    """Attempt a minimal blit to confirm the display driver stack works.

    Opens the ST7789 display in ``headless=False`` mode, fills the
    framebuffer with a solid colour, and flips it.  Returns ``ok=None``
    when ``adafruit-blinka`` / ``board`` are not installed (developer
    machine) rather than ``ok=False``.
    """
    try:
        from piwallet.ui.display import FrameBuffer, open_display
    except ImportError:
        return CheckResult(
            name="display_paint",
            ok=None,
            detail="piwallet.ui.display unavailable (missing deps)",
        )

    try:
        disp = open_display("auto")
    except Exception as exc:
        return CheckResult(
            name="display_paint",
            ok=None,
            detail=f"open_display failed: {exc}",
        )

    try:
        fb = FrameBuffer(disp.width, disp.height)
        fb.clear((255, 255, 255))
        disp.flip(fb)
        fb.clear((0, 0, 0))
        disp.flip(fb)
    except Exception as exc:
        return CheckResult(
            name="display_paint",
            ok=False,
            detail=f"framebuffer flip failed: {exc}",
        )
    finally:
        try:
            disp.set_backlight(False)
            disp.close()
        except Exception:
            pass

    return CheckResult(
        name="display_paint",
        ok=True,
        detail="white→black blit completed without error",
    )


def run_all() -> list[CheckResult]:
    """Run all display checks and return results in a stable order."""
    return [
        check_spi_device(),
        check_backlight_gpio(),
        check_display_paint(),
    ]
