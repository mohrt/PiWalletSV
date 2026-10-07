"""Touch settings: the same Preferences and Maintenance items as the Zero.

Brightness and the sleep timer are saved as they change. Maintenance
opens change-PIN, airgap status, USB backup, about, and factory reset.
"""

from __future__ import annotations

import time
from pathlib import Path

from piwallet import __version__ as PIWALLET_VERSION
from piwallet.backup.bundle import (
    BackupBundleError,
    export_backup,
    import_backup,
    list_backup_summaries,
    stick_backups_root,
)
from piwallet.backup.usb import (
    DEFAULT_USB_MOUNT_POINT,
    UsbMountError,
    UsbVolume,
    ensure_mounted,
    list_usb_volumes,
    parent_disk,
)
from piwallet.bonnet.about import ABOUT_TAGLINE, ABOUT_TWITTER, ABOUT_WEBSITE
from piwallet.bonnet.splash import load_logo
from piwallet.bonnet.usb_backup import release_usb_session
from piwallet.core.factory_reset import factory_reset
from piwallet.core.paths import default_settings_path, default_terms_path
from piwallet.core.settings import (
    BRIGHTNESS_OPTIONS,
    BonnetSettings,
    load_settings,
    save_settings,
)
from piwallet.core.vault import Vault, VaultError, VaultWipedError, WrongPinError
from piwallet.diag.airgap import check_airgap, checks_for_bonnet_display
from piwallet.platform.pi_serial import read_pi_serial
from piwallet.touch.create import PinPad
from piwallet.touch.input import Tap
from piwallet.touch.ui import Hit
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    COLOR_OK,
    Display,
    FrameBuffer,
)
from piwallet.ui.widgets import draw_text

_ROW_H = 48
_LIST_TOP = 48
_HEAD_H = 28
_USB_HELP: tuple[str, ...] = (
    "Backup saves an encrypted copy of your wallets and settings to a USB drive.",
    "Restore replaces the wallets on this device with a backup. You'll need the PIN "
    "that was set when the backup was made.",
    "The USB backup is useful to transfer your wallets and settings between devices, "
    "or to back up your device in case it is lost or damaged. The seed phrase is "
    "used to restore individual wallets. Keep USB backups safe, same as seed phrases.",
)


class SettingsFlow:
    """Settings hub. ``done`` returns to the wallet list."""

    def __init__(
        self,
        width: int,
        height: int,
        vault: Vault,
        pin: str,
        *,
        display: Display | None = None,
        settings: BonnetSettings | None = None,
        settings_path: Path | None = None,
        terms_path: Path | None = None,
        list_volumes=list_usb_volumes,
        hardware: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.width = width
        self.hardware = hardware
        self._about_logo = None
        self.height = height
        self.vault = vault
        self.pin = pin
        self.display = display
        self.settings_path = settings_path if settings_path is not None else default_settings_path()
        self.terms_path = terms_path if terms_path is not None else default_terms_path()
        self.settings = settings if settings is not None else load_settings(self.settings_path)
        self._list_volumes = list_volumes
        self.phase = "hub"
        self.done = False
        self.wiped = False
        self.factory_reset = False
        self.restored = False
        self.new_pin: str | None = None
        self._down: str | None = None
        self._pad: PinPad | None = None
        self._pending_pin = ""
        self._message_title = ""
        self._message_body = ""
        self._message_error = False
        self._message_back = "maintenance"
        self._airgap: tuple | None = None
        self._airgap_ok = True
        self._volumes: list[UsbVolume] = []
        self._usb_mode = ""
        self._stick: Path | None = None
        self._backups: list = []
        self._backup_dir: Path | None = None
        self._import_settings = False
        self._brightness_draft = self.settings.brightness
        self._sleep_draft = self.settings.sleep_timeout_ms
        self._usb_scan_at = 0.0

    def on_tap(self, tap: Tap) -> None:
        if self.done:
            return
        if self._pad is not None:
            self._on_pad(tap)
            return
        choice = self._release(tap, self._hits())
        if choice is None:
            return
        if self.phase == "hub":
            self._on_hub(choice)
        elif self.phase == "preferences":
            self._on_preferences(choice)
        elif self.phase == "brightness":
            self._on_brightness(choice)
        elif self.phase == "sleep":
            self._on_sleep(choice)
        elif self.phase == "maintenance":
            self._on_maintenance(choice)
        elif self.phase == "airgap":
            if choice == "cancel":
                self.phase = "maintenance"
            elif choice == "refresh":
                self._load_airgap()
        elif self.phase == "about":
            if choice == "cancel":
                self.phase = "maintenance"
        elif self.phase == "usb":
            self._on_usb_menu(choice)
        elif self.phase == "usb_wait":
            if choice == "cancel":
                self.phase = "usb"
        elif self.phase == "volumes":
            self._on_volume(choice)
        elif self.phase == "backups":
            self._on_backup(choice)
        elif self.phase == "replace":
            self._on_replace(choice)
        elif self.phase == "reset1":
            self._on_reset(choice, final=False)
        elif self.phase == "reset2":
            self._on_reset(choice, final=True)
        elif self.phase == "message":
            if choice == "cancel":
                self.phase = self._message_back

    def draw(self, fb: FrameBuffer) -> None:
        if self._pad is not None:
            self._pad.draw(fb)
            back = Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32)
            _button(fb, back, "Cancel", held=self._down == "cancel")
            return
        if self.phase == "hub":
            self._draw_rows(fb, "Settings", (("preferences", "Preferences"), ("maintenance", "Maintenance")))
        elif self.phase == "preferences":
            self._draw_preferences(fb)
        elif self.phase == "brightness":
            self._draw_brightness(fb)
        elif self.phase == "sleep":
            self._draw_sleep(fb)
        elif self.phase == "maintenance":
            self._draw_rows(
                fb,
                "Maintenance",
                (
                    ("change_pin", "Change PIN"),
                    ("airgap", "Airgap status"),
                    ("usb", "USB backup"),
                    ("about", "About"),
                    ("reset", "Factory reset"),
                ),
            )
        elif self.phase == "airgap":
            self._draw_airgap(fb)
        elif self.phase == "about":
            self._draw_about(fb)
        elif self.phase == "usb":
            self._draw_usb_menu(fb)
        elif self.phase == "usb_wait":
            self._draw_usb_wait(fb)
        elif self.phase == "volumes":
            self._draw_volumes(fb)
        elif self.phase == "backups":
            self._draw_backups(fb)
        elif self.phase in ("replace", "reset1", "reset2"):
            self._draw_warning(fb)
        elif self.phase == "message":
            self._draw_message(fb)

    def _on_hub(self, choice: str) -> None:
        if choice == "cancel":
            self.done = True
            return
        if choice in ("preferences", "maintenance"):
            self.phase = choice

    def _on_preferences(self, choice: str) -> None:
        if choice == "cancel":
            self.phase = "hub"
            return
        if choice == "brightness":
            self._brightness_draft = self.settings.brightness
            self.phase = "brightness"
            return
        if choice == "sleep":
            self._sleep_draft = self.settings.sleep_timeout_ms
            self.phase = "sleep"
            return

    def _on_brightness(self, choice: str) -> None:
        options = BRIGHTNESS_OPTIONS
        current = min(options, key=lambda level: abs(level - self._brightness_draft))
        index = options.index(current)
        if choice == "dim" and index > 0:
            self._brightness_draft = options[index - 1]
            self._preview_brightness()
            return
        if choice == "bright" and index + 1 < len(options):
            self._brightness_draft = options[index + 1]
            self._preview_brightness()
            return
        if choice == "save":
            self.settings = self.settings.with_brightness(self._brightness_draft)
            self._preview_brightness()
            self._save()
            self.phase = "preferences"
            return
        if choice == "cancel":
            self._brightness_draft = self.settings.brightness
            self._preview_brightness()
            self.phase = "preferences"

    def _on_sleep(self, choice: str) -> None:
        choices = {"off": 0, "min1": 60_000, "min5": 300_000}
        if choice in choices:
            self._sleep_draft = choices[choice]
            return
        if choice == "save":
            self.settings = self.settings.with_sleep_timeout_ms(self._sleep_draft)
            self._save()
            self.phase = "preferences"
            return
        if choice == "cancel":
            self._sleep_draft = self.settings.sleep_timeout_ms
            self.phase = "preferences"

    def _preview_brightness(self) -> None:
        if self.display is not None:
            self.display.set_brightness(self._brightness_draft)

    def _on_maintenance(self, choice: str) -> None:
        if choice == "cancel":
            self.phase = "hub"
            return
        if choice == "change_pin":
            self._usb_mode = ""
            self._open_pad("Current PIN", masked=True)
            self.phase = "pin_current"
            return
        if choice == "airgap":
            self._load_airgap()
            self.phase = "airgap"
            return
        if choice == "usb":
            self.phase = "usb"
            return
        if choice == "about":
            self.phase = "about"
            return
        if choice == "reset":
            self.phase = "reset1"

    def _on_usb_menu(self, choice: str) -> None:
        if choice == "cancel":
            self._usb_mode = ""
            self._release_usb()
            self.phase = "maintenance"
            return
        if choice in ("backup", "restore"):
            self._usb_mode = choice
            self._open_volumes()

    def tick(self) -> bool:
        """Keep looking for a USB drive while the wait or volume screen is up."""
        if self.phase not in ("usb_wait", "volumes"):
            return False
        if time.monotonic() - self._usb_scan_at < 1.0:
            return False
        previous = [volume.device for volume in self._volumes]
        self._scan_volumes()
        if self._volumes and self.phase == "usb_wait":
            self.phase = "volumes"
            return True
        if not self._volumes and self.phase == "volumes":
            self.phase = "usb_wait"
            return True
        return [volume.device for volume in self._volumes] != previous

    def _open_volumes(self) -> None:
        self._scan_volumes()
        self.phase = "volumes" if self._volumes else "usb_wait"

    def _scan_volumes(self) -> None:
        self._usb_scan_at = time.monotonic()
        self._volumes = list(self._list_volumes())

    def _on_volume(self, choice: str) -> None:
        if choice == "cancel":
            self.phase = "usb"
            return
        if not choice.startswith("vol:"):
            return
        volume = self._volumes[int(choice.split(":", 1)[1])]
        try:
            self._stick = ensure_mounted(volume, DEFAULT_USB_MOUNT_POINT)
        except (UsbMountError, OSError) as exc:
            self._note("Mount failed", str(exc), error=True, back="usb")
            return
        if self._usb_mode == "backup":
            self._open_pad("Confirm PIN", masked=True)
            self.phase = "usb_pin"
            return
        self._backups = list_backup_summaries(self._stick)
        if not self._backups:
            self._note("No backups", "Nothing under PiWalletSV/backups/.", error=True, back="usb")
            return
        self.phase = "backups"

    def _on_backup(self, choice: str) -> None:
        if choice == "cancel":
            self.phase = "volumes"
            return
        if not choice.startswith("bak:"):
            return
        manifest = self._backups[int(choice.split(":", 1)[1])]
        assert self._stick is not None
        self._backup_dir = stick_backups_root(self._stick) / manifest.backup_dir_name
        self._import_settings = manifest.has_settings
        try:
            replace = self.vault.is_initialized and bool(self.vault.list_wallets())
        except VaultError:
            replace = False
        if replace:
            self.phase = "replace"
            return
        self._begin_restore_pin()

    def _on_replace(self, choice: str) -> None:
        if choice == "cancel":
            self.phase = "backups"
            return
        if choice == "erase":
            self._begin_restore_pin()

    def _begin_restore_pin(self) -> None:
        """Current PIN first, so another backup cannot replace this device."""
        try:
            protected = self.vault.exists and self.vault.is_initialized
        except VaultError:
            protected = False
        if protected:
            self._open_pad("Current PIN", masked=True)
            self.phase = "restore_device_pin"
            return
        self._open_pad("Backup PIN", masked=True)
        self.phase = "restore_pin"

    def _accept_device_pin(self, entered: str) -> None:
        try:
            self.vault.check_pin(entered)
        except WrongPinError as exc:
            assert self._pad is not None
            self._pad.digits = ""
            self._pad.message = f"Wrong PIN. {exc.attempts_remaining} left"
            self._pad.message_error = True
            return
        except VaultWipedError:
            self.wiped = True
            self.done = True
            return
        except VaultError as exc:
            self._pad = None
            self._note("PIN failed", str(exc), error=True, back="usb")
            return
        self._open_pad("Backup PIN", masked=True)
        self.phase = "restore_pin"

    def _on_reset(self, choice: str, *, final: bool) -> None:
        if choice == "cancel":
            self.phase = "maintenance"
            return
        if choice != "erase":
            return
        if not final:
            self.phase = "reset2"
            return
        self._open_pad("Verify PIN", masked=True)
        self.phase = "reset_pin"

    def _on_pad(self, tap: Tap) -> None:
        assert self._pad is not None
        back = Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32)
        if back.contains(tap.x, tap.y):
            if tap.pressed:
                self._down = "cancel"
                return
            pressed_here = self._down == "cancel"
            self._down = None
            if pressed_here:
                self._leave_pad()
            return
        self._pad.on_tap(tap)
        if not self._pad.result:
            return
        entered = self._pad.result
        self._pad.result = None
        if self.phase == "pin_current":
            self._check_current(entered)
        elif self.phase == "pin_new":
            self._pending_pin = entered
            self._open_pad("Confirm PIN", masked=False)
            self.phase = "pin_confirm"
        elif self.phase == "pin_confirm":
            self._finish_pin(entered)
        elif self.phase == "usb_pin":
            self._finish_backup(entered)
        elif self.phase == "restore_device_pin":
            self._accept_device_pin(entered)
        elif self.phase == "restore_pin":
            self._finish_restore(entered)
        elif self.phase == "reset_pin":
            self._finish_reset(entered)

    def _check_current(self, entered: str) -> None:
        try:
            self.vault.check_pin(entered)
        except WrongPinError as exc:
            assert self._pad is not None
            self._pad.digits = ""
            self._pad.message = f"Wrong PIN. {exc.attempts_remaining} left"
            self._pad.message_error = True
            return
        except VaultWipedError:
            self.wiped = True
            self.done = True
            return
        except VaultError as exc:
            self._note("PIN failed", str(exc), error=True, back="maintenance")
            self._pad = None
            return
        self.pin = entered
        self._open_pad("New PIN", masked=False)
        self.phase = "pin_new"

    def _finish_pin(self, entered: str) -> None:
        if entered != self._pending_pin:
            self._open_pad("Confirm PIN", masked=False)
            assert self._pad is not None
            self._pad.message = "PINs do not match"
            self._pad.message_error = True
            return
        if entered == self.pin:
            self._pad = None
            self._note("No change", "New PIN matches the current one.", error=True, back="maintenance")
            return
        try:
            self.vault.change_pin(self.pin, entered)
        except (WrongPinError, VaultError) as exc:
            self._pad = None
            self._note("PIN failed", str(exc), error=True, back="maintenance")
            return
        self.pin = entered
        self.new_pin = entered
        self._pad = None
        self._pending_pin = ""
        self._note("PIN changed", "The new PIN unlocks this device.", error=False, back="maintenance")

    def _finish_backup(self, entered: str) -> None:
        try:
            self.vault.check_pin(entered)
        except WrongPinError as exc:
            assert self._pad is not None
            self._pad.digits = ""
            self._pad.message = f"Wrong PIN. {exc.attempts_remaining} left"
            self._pad.message_error = True
            return
        except VaultWipedError:
            self.wiped = True
            self.done = True
            return
        except VaultError as exc:
            self._pad = None
            self._note("PIN failed", str(exc), error=True, back="usb")
            return
        self._pad = None
        if self._stick is None:
            self._note("Backup failed", "No USB drive.", error=True, back="usb")
            return
        try:
            result = export_backup(
                self._stick,
                vault_path=self.vault.path,
                settings_path=self.settings_path,
                include_settings=True,
            )
        except (BackupBundleError, OSError) as exc:
            self._note("Backup failed", str(exc), error=True, back="usb")
            return
        error = self._eject_usb()
        if error:
            self._note("Backup failed", error, error=True, back="usb")
            return
        self._note("Backup saved", result.backup_dir.name, error=False, back="usb")

    def _finish_restore(self, entered: str) -> None:
        self._pad = None
        if self._backup_dir is None:
            self._note("Restore failed", "No backup selected.", error=True, back="usb")
            return
        try:
            import_backup(
                self._backup_dir,
                vault_path=self.vault.path,
                settings_path=self.settings_path,
                import_settings=self._import_settings,
                pin=entered,
            )
        except BackupBundleError as exc:
            self._note("Restore failed", str(exc), error=True, back="usb")
            return
        self._release_usb()
        self.new_pin = entered
        self.restored = True
        self.done = True

    def _finish_reset(self, entered: str) -> None:
        try:
            self.vault.check_pin(entered)
        except WrongPinError as exc:
            assert self._pad is not None
            self._pad.digits = ""
            self._pad.message = f"Wrong PIN. {exc.attempts_remaining} left"
            self._pad.message_error = True
            return
        except VaultWipedError:
            self.wiped = True
            self.done = True
            return
        except VaultError as exc:
            self._pad = None
            self._note("PIN failed", str(exc), error=True, back="maintenance")
            return
        self._pad = None
        try:
            factory_reset(
                vault_path=self.vault.path,
                settings_path=self.settings_path,
                terms_path=self.terms_path,
            )
        except OSError as exc:
            self._note("Reset failed", str(exc), error=True, back="maintenance")
            return
        self.factory_reset = True
        self.done = True

    def _load_airgap(self) -> None:
        report = check_airgap()
        self._airgap_ok = report.ok
        self._airgap = checks_for_bonnet_display()

    def _open_pad(self, title: str, *, masked: bool) -> None:
        self._pad = PinPad(self.width, self.height, title=title, masked=masked)

    def _save(self) -> None:
        save_settings(self.settings, self.settings_path)

    def _note(self, title: str, body: str, *, error: bool, back: str) -> None:
        self._message_title = title
        self._message_body = body.replace("\n", " ")[:120]
        self._message_error = error
        self._message_back = back
        self.phase = "message"

    def _release_usb(self) -> None:
        self._stick = None
        try:
            release_usb_session()
        except Exception:
            return

    def _eject_usb(self) -> str | None:
        """Unmount so the backup is on the stick before we say it saved."""
        self._stick = None
        try:
            release_usb_session()
        except Exception as exc:
            text = str(exc).strip()
            return text or "Could not eject the USB drive."
        return None

    def _leave_pad(self) -> None:
        self._pad = None
        self._pending_pin = ""
        if self.phase in ("restore_pin", "restore_device_pin"):
            self.phase = "backups"
        elif self.phase == "usb_pin":
            self.phase = "usb"
        else:
            self.phase = "maintenance"

    def _hits(self) -> list[Hit]:
        if self.phase in ("hub", "preferences", "maintenance", "usb"):
            return self._menu_hits(self._menu_items())
        if self.phase == "usb_wait":
            return [Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32)]
        if self.phase == "volumes":
            return self._volume_blocks()[1]
        if self.phase == "backups":
            return self._indexed_hits("bak", len(self._backups))
        if self.phase == "brightness":
            gap = 8
            mid = self.width // 2
            y = 168
            return [
                Hit("dim", 8, y, mid - gap, y + 56),
                Hit("bright", mid + gap, y, self.width - 8, y + 56),
                Hit("cancel", 8, self.height - 64, mid - gap, self.height - 8),
                Hit("save", mid + gap, self.height - 64, self.width - 8, self.height - 8),
            ]
        if self.phase == "sleep":
            gap = 8
            mid = self.width // 2
            top = 56
            step = 64
            return [
                Hit("off", 8, top, self.width - 8, top + 56),
                Hit("min1", 8, top + step, self.width - 8, top + step + 56),
                Hit("min5", 8, top + step * 2, self.width - 8, top + step * 2 + 56),
                Hit("cancel", 8, self.height - 64, mid - gap, self.height - 8),
                Hit("save", mid + gap, self.height - 64, self.width - 8, self.height - 8),
            ]
        if self.phase == "airgap":
            return [
                Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32),
                Hit("refresh", 8, self.height - 48, self.width - 8, self.height - 6),
            ]
        if self.phase in ("replace", "reset1", "reset2"):
            return [
                Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32),
                Hit("erase", 8, self.height - 48, self.width - 8, self.height - 6),
            ]
        return [Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32)]

    def _menu_items(self) -> tuple[tuple[str, str], ...]:
        if self.phase == "hub":
            return (("preferences", "Preferences"), ("maintenance", "Maintenance"))
        if self.phase == "preferences":
            return (("brightness", "Brightness"), ("sleep", "Sleep timer"))
        if self.phase == "usb":
            return (("backup", "Backup to USB"), ("restore", "Restore from USB"))
        return (
            ("change_pin", "Change PIN"),
            ("airgap", "Airgap status"),
            ("usb", "USB backup"),
            ("about", "About"),
            ("reset", "Factory reset"),
        )

    def _menu_hits(self, items: tuple[tuple[str, str], ...]) -> list[Hit]:
        hits = [Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32)]
        for index, (action_id, _label) in enumerate(items):
            y0 = _LIST_TOP + index * _ROW_H
            hits.append(Hit(action_id, 8, y0, self.width - 8, y0 + _ROW_H - 8))
        return hits

    def _indexed_hits(self, prefix: str, count: int) -> list[Hit]:
        hits = [Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32)]
        for index in range(count):
            y0 = _LIST_TOP + index * _ROW_H
            if y0 > self.height - 16:
                break
            hits.append(Hit(f"{prefix}:{index}", 8, y0, self.width - 8, y0 + _ROW_H - 8))
        return hits

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

    def _draw_rows(self, fb: FrameBuffer, title: str, items: tuple[tuple[str, str], ...]) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, title, size=18, color=COLOR_FG)
        for item in self._menu_hits(items):
            label = "Back" if item.id == "cancel" else dict(items)[item.id]
            _button(fb, item, label, held=self._down == item.id)

    def _draw_usb_menu(self, fb: FrameBuffer) -> None:
        items = self._menu_items()
        self._draw_rows(fb, "USB backup", items)
        y = _LIST_TOP + len(items) * _ROW_H + 8
        for paragraph in _USB_HELP:
            for line in _wrap(paragraph, (self.width - 32) // 8):
                draw_text(fb, 16, y, line, size=15, color=COLOR_DIM)
                y += 20
            y += 8

    def _draw_preferences(self, fb: FrameBuffer) -> None:
        self._draw_rows(fb, "Preferences", (("brightness", "Brightness"), ("sleep", "Sleep timer")))
        values = {
            "brightness": f"{round(self.settings.brightness * 100):d}%",
            "sleep": _sleep_label(self.settings.sleep_timeout_ms),
        }
        for item in self._hits():
            if item.id not in values:
                continue
            draw_text(fb, item.x1 - 16, item.center()[1], values[item.id], size=16, color=COLOR_DIM, anchor="rm")

    def _draw_brightness(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Brightness", size=18, color=COLOR_FG)
        percent = f"{round(self._brightness_draft * 100):d}%"
        draw_text(fb, self.width // 2, 100, percent, size=36, color=COLOR_FG, anchor="mm")
        labels = {"cancel": "Cancel", "save": "Save"}
        for item in self._hits():
            held = self._down == item.id
            if item.id in ("dim", "bright"):
                _button(fb, item, "", held=held)
                ink = COLOR_BG if held else COLOR_FG
                _draw_sun(fb.draw, *item.center(), ink, rays=item.id == "bright")
            else:
                _button(fb, item, labels[item.id], held=held)

    def _draw_sleep(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Sleep timer", size=18, color=COLOR_FG)
        selected = {0: "off", 60_000: "min1", 300_000: "min5"}.get(self._sleep_draft, "min5")
        labels = {"off": "Off", "min1": "1 min", "min5": "5 min", "cancel": "Cancel", "save": "Save"}
        for item in self._hits():
            held = self._down == item.id or item.id == selected
            _button(fb, item, labels[item.id], held=held)

    def _draw_airgap(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        ok = self._airgap_ok
        draw_text(fb, 12, 8, "Air-gapped" if ok else "BREACH", size=18, color=COLOR_OK if ok else COLOR_DANGER)
        _button(fb, self._hits()[0], "Back", held=self._down == "cancel")
        y = 52
        for row in self._airgap or ():
            color = COLOR_OK if row.ok is True else COLOR_DANGER if row.ok is False else COLOR_DIM
            draw_text(fb, 16, y, row.display_name, size=16, color=COLOR_FG)
            draw_text(fb, self.width - 16, y, row.bonnet_status, size=16, color=color, anchor="ra")
            y += 28
        refresh = self._hits()[1]
        _button(fb, refresh, "Refresh", held=self._down == "refresh")

    def _about_rows(self) -> tuple[tuple[str, str], ...]:
        serial = read_pi_serial() or "—"
        try:
            import platform

            host = platform.node() or "—"
        except Exception:
            host = "—"
        return (
            ("Version", f"v{PIWALLET_VERSION} Pro"),
            *self.hardware,
            ("Wallets", str(len(self.vault.list_wallets()))),
            ("Serial", serial[:18]),
            ("Host", host[:18]),
            ("Web", ABOUT_WEBSITE.replace("https://", "")),
            ("", ABOUT_TWITTER),
        )

    def _draw_about(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "About", size=18, color=COLOR_FG)
        _button(fb, self._hits()[0], "Back", held=self._down == "cancel")
        if self._about_logo is None:
            self._about_logo = load_logo(max_w=200, max_h=150)
        logo = self._about_logo
        fb.image.paste(logo, ((self.width - logo.width) // 2, 44))
        y = 44 + logo.height + 10
        for label, value in self._about_rows():
            if label:
                draw_text(fb, 16, y, label, size=16, color=COLOR_DIM)
            draw_text(fb, self.width - 16, y, value, size=16, color=COLOR_FG, anchor="ra")
            y += 28
        if y + 28 <= self.height:
            draw_text(fb, 16, y + 8, ABOUT_TAGLINE, size=15, color=COLOR_DIM)

    def _draw_usb_wait(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        title = "Backup" if self._usb_mode == "backup" else "Restore"
        draw_text(fb, 12, 8, title, size=18, color=COLOR_FG)
        _button(fb, self._hits()[0], "Back", held=self._down == "cancel")
        draw_text(fb, self.width // 2, 140, "No USB drive", size=18, color=COLOR_DANGER, anchor="mm")
        y = 180
        for line in _wrap("Insert a FAT32 or exFAT drive.", 28):
            draw_text(fb, self.width // 2, y, line, size=16, color=COLOR_DIM, anchor="mm")
            y += 24
        draw_text(fb, self.width // 2, y + 12, "Waiting for device…", size=16, color=COLOR_FG, anchor="mm")

    def _grouped_volumes(self) -> list[tuple[str, list[int]]]:
        groups: list[tuple[str, list[int]]] = []
        slots: dict[str, int] = {}
        for index, volume in enumerate(self._volumes):
            device = str(getattr(volume, "device", "") or "")
            disk = parent_disk(device) if device else ""
            title = str(getattr(volume, "model", "") or "") or disk or "USB"
            slot = slots.get(disk or title)
            if slot is None:
                slots[disk or title] = len(groups)
                groups.append((title, [index]))
            else:
                groups[slot][1].append(index)
        return groups

    def _volume_blocks(self) -> tuple[list[tuple[str, int]], list[Hit]]:
        headings: list[tuple[str, int]] = []
        hits = [Hit("cancel", self.width - 8 - 112, 4, self.width - 8, 32)]
        y = _LIST_TOP
        for title, indexes in self._grouped_volumes():
            headings.append((title, y))
            y += _HEAD_H
            for index in indexes:
                if y > self.height - 16:
                    return headings, hits
                hits.append(Hit(f"vol:{index}", 8, y, self.width - 8, y + _ROW_H - 8))
                y += _ROW_H
            y += 4
        return headings, hits

    def _draw_volumes(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        title = "Backup" if self._usb_mode == "backup" else "Restore"
        draw_text(fb, 12, 8, title, size=18, color=COLOR_FG)
        headings, hits = self._volume_blocks()
        for name, y in headings:
            draw_text(fb, 16, y, name[:26], size=16, color=COLOR_DIM)
        for item in hits:
            if item.id == "cancel":
                _button(fb, item, "Back", held=self._down == "cancel")
                continue
            volume = self._volumes[int(item.id.split(":", 1)[1])]
            _button(fb, item, _partition_label(volume)[:28], held=self._down == item.id)

    def _draw_backups(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        draw_text(fb, 12, 8, "Pick backup", size=18, color=COLOR_FG)
        _button(fb, self._hits()[0], "Back", held=self._down == "cancel")
        for item in self._hits():
            if not item.id.startswith("bak:"):
                continue
            manifest = self._backups[int(item.id.split(":", 1)[1])]
            _button(fb, item, manifest.backup_dir_name[:28], held=self._down == item.id)

    def _draw_warning(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        final = self.phase in ("reset2", "replace")
        title = "Last chance" if final else "Erase?"
        if self.phase == "replace":
            title = "Replace vault?"
        draw_text(fb, 12, 8, title, size=18, color=COLOR_FG)
        _button(fb, self._hits()[0], "Cancel", held=self._down == "cancel")
        body = (
            "All wallets, PINs, and settings are erased from this Pi. "
            "The seed phrase is the only way to recover the coins."
            if self.phase == "reset1"
            else "This cannot be undone. The device returns to first setup."
            if self.phase == "reset2"
            else "All current wallets on this device will be replaced by the backup."
        )
        y = 56
        for line in _wrap(body, 28):
            draw_text(fb, 16, y, line, size=16, color=COLOR_DIM)
            y += 22
        label = "Replace" if self.phase == "replace" else "Erase"
        _button(fb, self._hits()[1], label, held=self._down == "erase", danger=True)

    def _draw_message(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        color = COLOR_DANGER if self._message_error else COLOR_OK
        draw_text(fb, 12, 8, self._message_title[:22], size=18, color=color)
        _button(fb, self._hits()[0], "Back", held=self._down == "cancel")
        y = 64
        for line in _wrap(self._message_body, 28)[:6]:
            draw_text(fb, 16, y, line, size=16, color=COLOR_FG)
            y += 22


def _partition_label(volume: UsbVolume) -> str:
    device = str(getattr(volume, "device", "") or "")
    name = str(getattr(volume, "label", "") or "") or (device.rsplit("/", 1)[-1] if device else "")
    kind = {"vfat": "FAT32", "fat": "FAT32", "fat32": "FAT32", "msdos": "FAT32", "exfat": "exFAT"}.get(
        getattr(volume, "fstype", ""), getattr(volume, "fstype", "")
    )
    parts = [name, str(getattr(volume, "size", "") or "")]
    if kind:
        parts.append(kind)
    text = "  ".join(part for part in parts if part)
    return text or str(getattr(volume, "display_name", "USB"))


def _sleep_label(ms: int) -> str:
    if ms <= 0:
        return "Off"
    return f"{ms // 60_000} min"


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


def _draw_sun(draw, cx: int, cy: int, color: tuple[int, int, int], *, rays: bool) -> None:
    radius = 6 if rays else 7
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=color, width=2)
    if not rays:
        return
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
        draw.line((cx + dx * 10, cy + dy * 10, cx + dx * 14, cy + dy * 14), fill=color, width=2)


def _button(fb: FrameBuffer, item: Hit, label: str, *, held: bool, danger: bool = False) -> None:
    outline = COLOR_DANGER if danger and not held else (COLOR_FG if held else COLOR_ACCENT)
    fb.draw.rounded_rectangle(
        (item.x0, item.y0, item.x1 - 1, item.y1 - 1),
        radius=8,
        fill=COLOR_ACCENT if held else (24, 24, 24),
        outline=outline,
        width=2,
    )
    ink = COLOR_BG if held else (COLOR_DANGER if danger else COLOR_FG)
    draw_text(fb, *item.center(), label, size=16, color=ink, anchor="mm")
