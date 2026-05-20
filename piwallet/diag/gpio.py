"""GPIO / input hardware diagnostic.

Verifies that the Adafruit 1.3" TFT bonnet's joystick and A/B buttons
are wired to the expected BCM pins and that each pin can be read without
error.  The check is *passive*: it reads the current logic level rather
than generating input events, so it can run without a human pressing
anything.

BCM pin map (from :mod:`piwallet.ui.input.BonnetInputBackend`):

=======  =========  ============================================
BCM pin  Button     Notes
=======  =========  ============================================
5        UP         Joystick up
6        DOWN       Joystick down
16       LEFT       Joystick left
24       RIGHT      Joystick right
17       CENTER     Joystick center press
23       A          A button (confirm)
22       B          B button (back / cancel)
=======  =========  ============================================

Results use the same :class:`~piwallet.diag.display.CheckResult` type.
``ok=None`` is returned when the ``RPi.GPIO`` or ``gpiod`` backend is
unavailable (developer Mac), distinguishing "can't check" from a real
failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CheckOk = Literal[True, False, None]


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single diagnostic sub-check."""

    name: str
    ok: CheckOk
    detail: str


#: Expected BCM pin → button name mapping (must match BonnetInputBackend._PINS).
_EXPECTED_PINS: dict[int, str] = {
    5: "UP",
    6: "DOWN",
    16: "LEFT",
    24: "RIGHT",
    17: "CENTER",
    23: "A",
    22: "B",
}


def check_gpio_pins() -> list[CheckResult]:
    """Read each bonnet GPIO pin and confirm no IOError is raised.

    Uses ``RPi.GPIO`` in BCM mode if available; falls back to
    ``gpiod``; returns ``ok=None`` on a non-Pi host.
    """
    try:
        import RPi.GPIO as GPIO  # type: ignore[import-untyped]
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
    except (ImportError, RuntimeError):
        return [
            CheckResult(
                name=f"gpio_{name.lower()}",
                ok=None,
                detail="RPi.GPIO unavailable — not running on Pi",
            )
            for name in _EXPECTED_PINS.values()
        ]

    results: list[CheckResult] = []
    for pin, name in _EXPECTED_PINS.items():
        try:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            level = GPIO.input(pin)
            results.append(
                CheckResult(
                    name=f"gpio_{name.lower()}",
                    ok=True,
                    detail=f"BCM {pin} reads {'HIGH' if level else 'LOW'} (not pressed = HIGH)",
                )
            )
        except Exception as exc:
            results.append(
                CheckResult(
                    name=f"gpio_{name.lower()}",
                    ok=False,
                    detail=f"BCM {pin}: {exc}",
                )
            )

    try:
        GPIO.cleanup()
    except Exception:
        pass

    return results


def run_all() -> list[CheckResult]:
    """Run all GPIO checks and return results in pin order."""
    return check_gpio_pins()
