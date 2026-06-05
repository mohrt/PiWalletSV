"""Automated software checks for factory diagnostics."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from piwallet.diag import display as diag_display
from piwallet.diag.airgap import (
    CheckResult,
    check_airgap,
    check_no_bluetooth_modules,
    check_no_wifi_modules,
    check_rfkill_all_blocked,
)
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
from piwallet.ui.widgets import draw_text

COLOR_OK = (96, 192, 96)
COLOR_FAIL = (224, 80, 80)


def _status_glyph(ok: bool | None) -> str:
    if ok is True:
        return "OK"
    if ok is False:
        return "!!"
    return "--"

SwChecksResult = Literal["back"]

def collect_software_checks(*, vault_path: Path) -> list[CheckResult]:
    """Run passive software/hardware readiness checks (no display reopen).

    Input GPIO is exercised via the interactive joystick/button test
    menu items — do not probe pins here (``RPi.GPIO`` fights Blinka).
    """
    results: list[CheckResult] = []
    for check_fn in (
        diag_display.check_spi_device,
        diag_display.check_backlight_gpio,
        _check_camera_stack,
        lambda: _check_vault_dir_writable(vault_path),
        _check_pi_serial,
    ):
        results.append(_run_check_safe(check_fn))
    try:
        report = check_airgap()
        results.extend(_factory_airgap_checks(report))
    except Exception as exc:
        results.append(
            CheckResult("airgap", False, f"check failed: {exc}"[:48])
        )
    return results


def _factory_airgap_checks(report: object) -> list[CheckResult]:
    """Airgap rows for the LCD — split radio modules, friendly names."""
    checks = list(getattr(report, "checks", ()))
    out: list[CheckResult] = []
    for check in checks:
        if check.name == "modules":
            out.append(_soften_radio_for_factory(check_no_wifi_modules()))
            out.append(_soften_radio_for_factory(check_no_bluetooth_modules()))
            continue
        if check.name == "interfaces":
            check = CheckResult("network", check.ok, check.detail)
        out.append(check)
    return out


def _soften_radio_for_factory(check: CheckResult) -> CheckResult:
    """Loaded radio modules are OK at factory QA when rfkill blocks them all."""
    if check.ok is not False:
        return check
    rfkill = check_rfkill_all_blocked()
    if rfkill.ok is True:
        return CheckResult(check.name, True, "loaded, rfkill blocked")
    return check


def _run_check_safe(fn: object) -> CheckResult:
    try:
        result = fn()  # type: ignore[operator]
    except Exception as exc:
        name = getattr(fn, "__name__", "check").removeprefix("_check_")
        return CheckResult(name, False, str(exc)[:48])
    return _normalize_check(result)


def _normalize_check(result: object) -> CheckResult:
    if isinstance(result, CheckResult):
        return result
    name = getattr(result, "name", None)
    ok = getattr(result, "ok", None)
    detail = getattr(result, "detail", None)
    if isinstance(name, str) and isinstance(detail, str):
        return CheckResult(name, ok, detail)
    raise TypeError(f"unexpected check result: {result!r}")


def _check_camera_stack() -> CheckResult:
    try:
        from piwallet.qr.camera_scan import _import_camera_stack

        _import_camera_stack()
    except Exception as exc:
        return CheckResult("camera", False, str(exc)[:48])
    return CheckResult("camera", True, "picamera2 import ok")


def _check_vault_dir_writable(vault_path: Path) -> CheckResult:
    parent = vault_path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CheckResult("vault_dir", False, f"mkdir failed: {exc}")
    if not os.access(parent, os.W_OK):
        return CheckResult("vault_dir", False, f"{parent} not writable")
    return CheckResult("vault_dir", True, f"{parent} writable")


def _check_pi_serial() -> CheckResult:
    serial = read_pi_serial()
    if not serial:
        return CheckResult("serial", None, "serial unavailable")
    return CheckResult("serial", True, serial[:24])


@dataclass
class SoftwareChecksScreen:
    """Read-only pass/fail table of automated checks."""

    vault_path: Path
    checks: list[CheckResult] = field(default_factory=list)
    done: bool = False
    result: SwChecksResult | None = None
    _ran: bool = False

    def _refresh(self) -> None:
        self.checks = collect_software_checks(vault_path=self.vault_path)

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        b = event.button
        k = event.kind
        if b == Button.B and k == EventKind.PRESS:
            self.done = True
            self.result = "back"
            return
        if b in (Button.A, Button.SELECT) and k == EventKind.PRESS:
            self._refresh()

    def draw(self, fb: FrameBuffer) -> None:
        if not self._ran:
            self._refresh()
            self._ran = True

        fb.clear(COLOR_BG)
        title_h = 26
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, title_h), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            title_h // 2,
            "Software checks",
            size=13,
            color=COLOR_ACCENT,
            anchor="mm",
        )

        y = title_h + 10
        row_step = 18
        visible = (DISPLAY_HEIGHT - title_h - 36) // row_step
        for check in self.checks[:visible]:
            row_color = (
                COLOR_OK
                if check.ok is True
                else COLOR_FAIL
                if check.ok is False
                else COLOR_DIM
            )
            draw_text(
                fb, 10, y, check.display_name, size=10, color=COLOR_FG, anchor="lm"
            )
            draw_text(
                fb,
                DISPLAY_WIDTH - 10,
                y,
                _status_glyph(check.ok),
                size=10,
                color=row_color,
                anchor="rm",
            )
            y += row_step

        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 10,
            "A refresh   B back",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
