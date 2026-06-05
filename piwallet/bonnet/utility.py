"""Bonnet diagnostics menu (factory entry from boot splash).

Hold **B** for five seconds on the boot logo to reach diagnostics
before terms, vault setup, or PIN. Operators can view device info,
run automated software checks, and exercise hardware interactively.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

from piwallet import __version__ as PIWALLET_VERSION
from piwallet.bonnet.camera_preview import start_camera_preview_worker
from piwallet.bonnet.diagnostics_sw import SoftwareChecksScreen
from piwallet.bonnet.utility_hw_tests import (
    ButtonsTestScreen,
    CameraTestScreen,
    JoystickTestScreen,
    ScreenTestScreen,
)
from piwallet.core.vault import Vault
from piwallet.firstboot.terms import load_state
from piwallet.platform.pi_serial import read_pi_serial
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DIM,
    COLOR_FG,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    Display,
    FrameBuffer,
)
from piwallet.ui.double_confirm import DoubleConfirmScreen
from piwallet.ui.input import Button, Event, EventKind, InputManager
from piwallet.ui.widgets import ListItem, ListView, Modal, draw_text

log = logging.getLogger(__name__)

DiagnosticsMenuResult = Literal["back"]
DiagnosticsFlowResult = Literal["restart"] | None


class DiagnosticsAction(Enum):
    INFO = "info"
    SOFTWARE_CHECKS = "software"
    TEST_JOYSTICK = "joystick"
    TEST_BUTTONS = "buttons"
    TEST_CAMERA = "camera"
    TEST_SCREEN = "screen"
    RESTART = "restart"


@dataclass
class DiagnosticsInfoScreen:
    """Static device / vault snapshot."""

    rows: list[tuple[str, str]]
    done: bool = False
    result: Literal["back"] | None = None

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
            "Device info",
            size=14,
            color=COLOR_ACCENT,
            anchor="mm",
        )
        y = title_h + 14
        for key, value in self.rows:
            draw_text(fb, 12, y, key, size=10, color=COLOR_DIM, anchor="la")
            draw_text(
                fb,
                DISPLAY_WIDTH - 12,
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


@dataclass
class DiagnosticsMenuScreen:
    """Diagnostics hub — info, software checks, and hardware tests."""

    done: bool = False
    result: DiagnosticsAction | DiagnosticsMenuResult | None = None
    _list: ListView = field(init=False)
    _b_pressed_here: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self._list = ListView(
            items=[
                ListItem(label="Device info", value=DiagnosticsAction.INFO),
                ListItem(
                    label="Run all checks",
                    value=DiagnosticsAction.SOFTWARE_CHECKS,
                ),
                ListItem(
                    label="Test joystick",
                    value=DiagnosticsAction.TEST_JOYSTICK,
                ),
                ListItem(
                    label="Test buttons",
                    value=DiagnosticsAction.TEST_BUTTONS,
                ),
                ListItem(label="Test camera", value=DiagnosticsAction.TEST_CAMERA),
                ListItem(label="Test screen", value=DiagnosticsAction.TEST_SCREEN),
                ListItem(label="Restart app", value=DiagnosticsAction.RESTART),
            ],
            title="Diagnostics",
            footer="A: select   B: back",
        )

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if event.button == Button.B:
            if event.kind == EventKind.PRESS:
                self._b_pressed_here = True
                return
            if event.kind == EventKind.RELEASE:
                if self._b_pressed_here:
                    self.done = True
                    self.result = "back"
                self._b_pressed_here = False
                return
        self._list.on_event(event)
        if self._list.confirmed is not None:
            self.done = True
            self.result = self._list.confirmed

    def draw(self, fb: FrameBuffer) -> None:
        self._list.draw(fb)


def build_info_rows(
    *,
    vault: Vault,
    terms_path: Path | None = None,
) -> list[tuple[str, str]]:
    terms = load_state(terms_path)
    terms_label = f"v{terms.terms_version}" if terms is not None else "—"
    unlock_tries = (
        str(vault.attempts_remaining) if vault.is_initialized else "—"
    )
    return [
        ("Version", f"v{PIWALLET_VERSION}"),
        ("Vault", _vault_status(vault)),
        ("Unlock tries", unlock_tries),
        ("Terms", terms_label),
        ("Serial", _truncate(read_pi_serial() or "—", 16)),
        ("Host", _truncate(_hostname(), 16)),
    ]


def run_diagnostics_flow(
    display: Display,
    input_mgr: InputManager,
    vault: Vault,
    *,
    terms_path: Path | None = None,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
) -> DiagnosticsFlowResult:
    """Run diagnostics until the operator backs out or requests a restart."""
    while True:
        menu = DiagnosticsMenuScreen()
        chosen = run_screen(
            display,
            input_mgr,
            menu,
            target_fps=target_fps,
            idle_wake=idle_wake,
        )
        if chosen is None or chosen == "back":
            return
        assert isinstance(chosen, DiagnosticsAction)
        if chosen is DiagnosticsAction.INFO:
            info = DiagnosticsInfoScreen(
                rows=build_info_rows(vault=vault, terms_path=terms_path),
            )
            run_screen(
                display,
                input_mgr,
                info,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
        elif chosen is DiagnosticsAction.SOFTWARE_CHECKS:
            run_screen(
                display,
                input_mgr,
                SoftwareChecksScreen(vault_path=vault.path),
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
        elif chosen is DiagnosticsAction.TEST_JOYSTICK:
            run_screen(
                display,
                input_mgr,
                JoystickTestScreen(),
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
        elif chosen is DiagnosticsAction.TEST_BUTTONS:
            run_screen(
                display,
                input_mgr,
                ButtonsTestScreen(),
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
        elif chosen is DiagnosticsAction.TEST_SCREEN:
            run_screen(
                display,
                input_mgr,
                ScreenTestScreen(),
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
        elif chosen is DiagnosticsAction.TEST_CAMERA:
            cam = CameraTestScreen(start_worker=start_camera_preview_worker)
            run_screen(
                display,
                input_mgr,
                cam,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
        elif chosen is DiagnosticsAction.RESTART:
            if run_diagnostics_restart(
                display,
                input_mgr,
                target_fps=target_fps,
                idle_wake=idle_wake,
            ):
                return "restart"


def run_diagnostics_restart(
    display: Display,
    input_mgr: InputManager,
    *,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
    toast_seconds: float = 1.0,
) -> bool:
    """Confirm and exit so systemd restarts the bonnet service (``Restart=always``)."""
    confirm = DoubleConfirmScreen(
        title="Restart app?",
        first_prompt=(
            "The wallet app will restart and continue boot. "
            "Press A for the final step."
        ),
        second_prompt="Press A to restart now or B to cancel.",
    )
    run_screen(
        display,
        input_mgr,
        confirm,
        target_fps=target_fps,
        idle_wake=idle_wake,
    )
    if confirm.result is not True:
        return False

    fb = FrameBuffer(display.width, display.height)
    Modal(
        title="Restarting",
        body="Continuing boot…",
        footer="",
        accent=(96, 192, 96),
    ).draw(fb)
    display.flip(fb)
    try:
        display.set_backlight(False)
    except Exception as exc:  # pragma: no cover
        log.warning("display.set_backlight(False) before restart failed: %s", exc)
    time.sleep(toast_seconds)
    return True


def _vault_status(vault: Vault) -> str:
    if not vault.exists:
        return "missing"
    if not vault.is_initialized:
        return "empty"
    return "ready"


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
