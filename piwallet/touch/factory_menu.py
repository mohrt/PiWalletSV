"""Touch diagnostics, opened by holding the boot logo.

Same jobs as the Zero menu: device info, software checks, camera,
screen, and restart. This panel has no joystick or A/B buttons.
"""

from __future__ import annotations

import time
from pathlib import Path

from piwallet.bonnet.camera_preview import CameraPreviewState, start_camera_preview_worker
from piwallet.bonnet.diagnostics_sw import collect_software_checks
from piwallet.diag.airgap import checks_for_bonnet_display
from piwallet.bonnet.utility import build_info_rows
from piwallet.bonnet.utility_hw_tests import ScreenPattern
from piwallet.camera_lcd import paste_cover
from piwallet.core.paths import default_terms_path
from piwallet.core.vault import Vault
from piwallet.touch.input import ScriptedTouch, Tap
from piwallet.touch.ui import Hit
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    Display,
    FrameBuffer,
)
from piwallet.ui.widgets import draw_text

_ROW_H = 56
_LIST_TOP = 48
_PATTERNS = tuple(ScreenPattern)
# SPI and the bonnet backlight are Zero hardware. The radio slugs below are
# the same Wi-Fi and Bluetooth checks repeated under different names.
_SKIP_CHECKS = frozenset({
    "spi_device",
    "backlight_gpio",
    "wifi",
    "bluetooth",
    "network",
    "modules",
    "rfkill",
    "interfaces",
    "services",
    "boot_config",
    "blacklist",
})


def touch_software_checks(vault_path: Path) -> list:
    """Camera, vault, and serial, then one row each for Wi-Fi, Bluetooth, and Network."""
    hardware = [
        check
        for check in collect_software_checks(vault_path=vault_path)
        if check.name not in _SKIP_CHECKS
    ]
    return hardware + list(checks_for_bonnet_display())


class DiagnosticsFlow:
    """Factory menu. ``done`` leaves back to boot."""

    def __init__(
        self,
        width: int,
        height: int,
        vault: Vault,
        *,
        terms_path: Path | None = None,
        camera_rotation: int = 0,
    ) -> None:
        self.width = width
        self.height = height
        self.vault = vault
        self.terms_path = terms_path if terms_path is not None else default_terms_path()
        self.camera_rotation = camera_rotation
        self.phase = "menu"
        self.done = False
        self.result: str | None = None
        self._down: str | None = None
        self._checks: list = []
        self._pattern = 0
        self._camera = None

    def on_tap(self, tap: Tap) -> None:
        if self.done:
            return
        choice = self._release(tap, self._hits())
        if choice is None:
            return
        if choice == "cancel":
            self._close_camera()
            if self.phase == "menu":
                self.done = True
                self.result = "back"
            else:
                self.phase = "menu"
            return
        if self.phase == "menu":
            self._open(choice)
        elif self.phase == "checks" and choice == "refresh":
            self._checks = touch_software_checks(self.vault.path)
        elif self.phase == "screen" and choice == "next":
            self._pattern = (self._pattern + 1) % len(_PATTERNS)
        elif self.phase == "restart" and choice == "go":
            self._close_camera(wait=True)
            self.done = True
            self.result = "restart"

    def draw(self, fb: FrameBuffer) -> None:
        if self.phase == "menu":
            self._draw_menu(fb)
        elif self.phase == "info":
            self._draw_info(fb)
        elif self.phase == "checks":
            self._draw_checks(fb)
        elif self.phase == "screen":
            self._draw_screen(fb)
        elif self.phase == "camera":
            self._draw_camera(fb)
        else:
            self._draw_restart(fb)

    def _open(self, choice: str) -> None:
        if choice == "info":
            self.phase = "info"
        elif choice == "checks":
            self._checks = touch_software_checks(self.vault.path)
            self.phase = "checks"
        elif choice == "screen":
            self._pattern = 0
            self.phase = "screen"
        elif choice == "camera":
            self._close_camera(wait=True)
            self._camera = CameraPreviewState()
            start_camera_preview_worker(self._camera, rotation_degrees=self.camera_rotation)
            self.phase = "camera"
        elif choice == "restart":
            self.phase = "restart"

    def _close_camera(self, *, wait: bool = False) -> None:
        state = self._camera
        if state is None:
            return
        with state.lock:
            state.cancel_requested = True
        if not wait:
            return
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with state.lock:
                if state.finished:
                    break
            time.sleep(0.05)
        self._camera = None

    def _hits(self) -> list[Hit]:
        back = Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 36)
        if self.phase == "menu":
            hits = []
            items = ("info", "checks", "camera", "screen", "restart")
            for index, item_id in enumerate(items):
                y0 = _LIST_TOP + index * _ROW_H
                hits.append(Hit(item_id, 8, y0, self.width - 8, y0 + _ROW_H - 8))
            return hits
        if self.phase == "checks":
            return [back, Hit("refresh", 8, self.height - 56, self.width - 8, self.height - 8)]
        if self.phase == "screen":
            mid = self.width // 2
            return [
                Hit("cancel", 8, self.height - 56, mid - 8, self.height - 8),
                Hit("next", mid + 8, self.height - 56, self.width - 8, self.height - 8),
            ]
        if self.phase == "restart":
            return [back, Hit("go", 8, self.height - 56, self.width - 8, self.height - 8)]
        return [back]

    def _release(self, tap: Tap, hits: list[Hit]) -> str | None:
        hit = None
        for item in hits:
            if item.contains(tap.x, tap.y):
                hit = item.id
                break
        if tap.pressed:
            self._down = hit
            return None
        chosen = self._down
        self._down = None
        if chosen is not None and chosen == hit:
            return chosen
        return None

    def _draw_menu(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Diagnostics", size=18, color=COLOR_FG)
        labels = {
            "info": "Device info",
            "checks": "Run all checks",
            "camera": "Test camera",
            "screen": "Test screen",
            "restart": "Restart app",
        }
        for item in self._hits():
            _button(fb, item, labels[item.id], held=self._down == item.id, danger=item.id == "restart")

    def _draw_info(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Device info", size=18, color=COLOR_FG)
        _button(fb, self._hits()[0], "Back", held=self._down == "cancel")
        y = _LIST_TOP
        for label, value in build_info_rows(vault=self.vault, terms_path=self.terms_path):
            draw_text(fb, 16, y, label, size=16, color=COLOR_DIM)
            draw_text(fb, self.width - 16, y, value, size=16, color=COLOR_FG, anchor="ra")
            y += 32

    def _draw_checks(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Checks", size=18, color=COLOR_FG)
        for item in self._hits():
            label = "Back" if item.id == "cancel" else "Refresh"
            _button(fb, item, label, held=self._down == item.id)
        y = _LIST_TOP
        for check in self._checks:
            if y > self.height - 72:
                break
            mark = "OK" if check.ok is True else "!!" if check.ok is False else "--"
            color = COLOR_FG if check.ok is True else COLOR_DANGER if check.ok is False else COLOR_DIM
            name = getattr(check, "display_name", check.name)
            draw_text(fb, 16, y, str(name)[:22], size=15, color=COLOR_FG)
            draw_text(fb, self.width - 16, y, mark, size=15, color=color, anchor="ra")
            y += 28

    def _draw_screen(self, fb: FrameBuffer) -> None:
        _paint(fb, _PATTERNS[self._pattern])
        draw_text(fb, 12, 8, _PATTERNS[self._pattern].value, size=18, color=COLOR_BG)
        for item in self._hits():
            label = "Back" if item.id == "cancel" else "Next"
            _button(fb, item, label, held=self._down == item.id)

    def _draw_camera(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Camera", size=18, color=COLOR_FG)
        _button(fb, self._hits()[0], "Back", held=self._down == "cancel")
        box = (8, 48, self.width - 8, self.height - 8)
        if self._camera is None:
            return
        with self._camera.lock:
            thumb = self._camera.latest_thumb
            error = self._camera.error
        if error:
            draw_text(fb, self.width // 2, self.height // 2, "Camera error", size=16, color=COLOR_DANGER, anchor="mm")
        elif thumb is not None:
            paste_cover(fb.image, thumb, box)

    def _draw_restart(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Restart app?", size=18, color=COLOR_FG)
        body = "The wallet app will restart and continue boot."
        y = 64
        for line in _wrap(body, 28):
            draw_text(fb, 16, y, line, size=16, color=COLOR_DIM)
            y += 22
        for item in self._hits():
            label = "Back" if item.id == "cancel" else "Restart"
            _button(fb, item, label, held=self._down == item.id, danger=item.id == "go")


def run_touch_diagnostics(
    display: Display,
    touch: ScriptedTouch,
    vault: Vault,
    *,
    terms_path: Path | None = None,
    camera_rotation: int = 0,
    sleep: bool = True,
    poll_s: float = 1 / 30,
) -> str | None:
    """Run the menu until Back or a confirmed restart."""
    flow = DiagnosticsFlow(
        display.width,
        display.height,
        vault,
        terms_path=terms_path,
        camera_rotation=camera_rotation,
    )
    fb = FrameBuffer(width=display.width, height=display.height)
    while not flow.done:
        tap = touch.poll()
        if tap is not None:
            flow.on_tap(tap)
        flow.draw(fb)
        display.flip(fb)
        if sleep and not flow.done:
            time.sleep(poll_s)
    return None if flow.result == "back" else flow.result


def _paint(fb: FrameBuffer, pattern: ScreenPattern) -> None:
    width, height = fb.image.size
    if pattern == ScreenPattern.RED:
        fb.clear((180, 32, 32))
    elif pattern == ScreenPattern.GREEN:
        fb.clear((32, 160, 64))
    elif pattern == ScreenPattern.BLUE:
        fb.clear((32, 64, 180))
    elif pattern == ScreenPattern.WHITE:
        fb.clear((220, 220, 220))
    elif pattern == ScreenPattern.CHECKER:
        fb.clear(COLOR_BG)
        step = 16
        for y in range(0, height, step):
            for x in range(0, width, step):
                if ((x // step) + (y // step)) % 2 == 0:
                    fb.draw.rectangle((x, y, x + step - 1, y + step - 1), fill=(48, 48, 56))
    else:
        fb.clear(COLOR_BG)
        for x in range(0, width, 24):
            fb.draw.line((x, 0, x, height), fill=(48, 48, 56))
        for y in range(0, height, 24):
            fb.draw.line((0, y, width, y), fill=(48, 48, 56))


def _wrap(text: str, limit: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if len(candidate) > limit and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def _button(fb: FrameBuffer, item: Hit, label: str, *, held: bool, danger: bool = False) -> None:
    fill = (48, 32, 32) if danger else ((24, 24, 24) if not held else (36, 36, 36))
    outline = COLOR_DANGER if danger else COLOR_ACCENT
    fb.draw.rounded_rectangle((item.x0, item.y0, item.x1, item.y1), radius=8, fill=fill, outline=outline, width=2)
    draw_text(fb, *item.center(), label, size=16, color=COLOR_FG, anchor="mm")
