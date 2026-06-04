"""Bonnet USB backup / restore flows."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from piwallet.backup.constants import STICK_ROOT_DIRNAME
from piwallet.backup.bundle import (
    BackupBundleError,
    export_backup,
    import_backup,
    list_backup_summaries,
    stick_backups_root,
)
from piwallet.backup.manifest import BackupManifest
from piwallet.backup.usb import (
    DEFAULT_USB_MOUNT_POINT,
    UsbVolume,
    ensure_mounted,
    list_usb_volumes,
    unmount,
)
from piwallet.backup.usb_mount_socket import UsbMountError
from piwallet.core.paths import default_settings_path, default_vault_path
from piwallet.core.vault import Vault, VaultError
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_FG,
    COLOR_OK,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    Display,
    FrameBuffer,
)
from piwallet.ui.double_confirm import DoubleConfirmScreen
from piwallet.ui.input import Button, Event, EventKind, InputManager
from piwallet.ui.pin_entry import PinEntryScreen
from piwallet.ui.widgets import ListItem, ListView, Modal, draw_text

log = logging.getLogger(__name__)

UsbFlowResult = Literal["ok", "cancelled", "failed"]
UsbMenuChoice = Literal["backup", "restore"]

ListUsbVolumesFn = Callable[[], list[UsbVolume]]
_DEFAULT_USB_SCAN_INTERVAL_S = 1.0


@dataclass
class UsbVolumePickerScreen:
    """Wait for a removable USB stick, then let the operator pick one."""

    prompt: str
    list_volumes: ListUsbVolumesFn = field(default=list_usb_volumes)
    scan_interval_s: float = _DEFAULT_USB_SCAN_INTERVAL_S
    done: bool = False
    result: UsbVolume | None = None
    _list: ListView | None = field(init=False, default=None)
    _last_scan_mono: float = field(init=False, default=-1e9)

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if event.button == Button.B and event.kind in (
            EventKind.PRESS,
            EventKind.LONG,
        ):
            self.done = True
            return
        if self._list is None:
            if event.button in (Button.A, Button.SELECT) and event.kind == EventKind.PRESS:
                self._scan(force=True)
            return
        self._list.on_event(event)
        if self._list.confirmed is not None:
            self.done = True
            self.result = self._list.confirmed  # type: ignore[assignment]

    def draw(self, fb: FrameBuffer) -> None:
        if self._list is None:
            self._scan(force=False)
            self._draw_waiting(fb)
            return
        self._list.draw(fb)

    def _scan(self, *, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self._last_scan_mono < self.scan_interval_s:
            return
        self._last_scan_mono = now
        volumes = self.list_volumes()
        if volumes:
            self._show_volume_list(volumes)

    def _show_volume_list(self, volumes: list[UsbVolume]) -> None:
        items = [
            ListItem(label=vol.display_name, value=vol)
            for vol in volumes
        ]
        self._list = ListView(
            items=items,
            title=self.prompt,
            footer="A: select   B: back",
        )

    def _draw_waiting(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        title_h = 28
        fb.draw.rectangle((0, 0, DISPLAY_WIDTH, title_h), fill=(20, 20, 32))
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            title_h // 2,
            self.prompt,
            size=13,
            color=COLOR_ACCENT,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            72,
            "No USB drive",
            size=14,
            color=COLOR_DANGER,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            98,
            "Insert a FAT32/exFAT stick",
            size=11,
            color=COLOR_FG,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            116,
            "in the data USB port.",
            size=11,
            color=COLOR_FG,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            148,
            "Waiting for device…",
            size=11,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 24,
            "A: rescan",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 10,
            "B: back",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )


@dataclass
class UsbConfirmModalScreen:
    """Result / error modal that stays until the operator presses A or B."""

    title: str
    body: str
    accent: tuple[int, int, int] = COLOR_OK
    done: bool = False
    result: None = None

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if event.button in (Button.A, Button.B, Button.SELECT) and event.kind in (
            EventKind.PRESS,
            EventKind.LONG,
        ):
            self.done = True

    def draw(self, fb: FrameBuffer) -> None:
        Modal(
            title=self.title,
            body=self.body,
            footer="A / B: OK",
            accent=self.accent,
        ).draw(fb)


def _release_usb(unmount_after: Path | None) -> None:
    """Best-effort unmount; never raise (cancel paths must not crash the bonnet)."""
    if unmount_after is None:
        return
    try:
        unmount(unmount_after)
    except Exception:
        log.exception("usb unmount failed for %s", unmount_after)


def release_usb_session() -> None:
    """Unmount the canonical USB stick path when leaving the USB backup menu."""
    _release_usb(DEFAULT_USB_MOUNT_POINT)


def _show_modal(
    display: Display,
    input_mgr: InputManager,
    *,
    title: str,
    body: str,
    accent: tuple[int, int, int] = COLOR_OK,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
) -> None:
    screen = UsbConfirmModalScreen(title=title, body=body, accent=accent)
    run_screen(
        display,
        input_mgr,
        screen,
        target_fps=target_fps,
        idle_wake=idle_wake,
    )


def _pick_usb_volume(
    display: Display,
    input_mgr: InputManager,
    *,
    target_fps: int,
    idle_wake: IdleWakeTracker | None,
    prompt: str,
    list_volumes: ListUsbVolumesFn = list_usb_volumes,
) -> UsbVolume | None:
    picker = UsbVolumePickerScreen(prompt=prompt, list_volumes=list_volumes)
    run_screen(display, input_mgr, picker, target_fps=target_fps, idle_wake=idle_wake)
    return picker.result


def run_usb_backup_menu(
    display: Display,
    input_mgr: InputManager,
    *,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
) -> UsbMenuChoice | None:
    """Submenu: backup to stick or restore from stick."""

    @dataclass
    class _Menu:
        done: bool = False
        result: UsbMenuChoice | None = None
        _list: ListView = field(init=False)

        def __post_init__(self) -> None:
            self._list = ListView(
                items=[
                    ListItem(label="Backup to USB", value="backup"),
                    ListItem(label="Restore from USB", value="restore"),
                ],
                title="USB backup",
                footer="A: select   B: back",
            )

        def on_event(self, event: Event) -> None:
            if self.done:
                return
            if event.button == Button.B and event.kind in (
                EventKind.PRESS,
                EventKind.LONG,
            ):
                self.done = True
                return
            self._list.on_event(event)
            if self._list.confirmed is not None:
                self.done = True
                self.result = self._list.confirmed  # type: ignore[assignment]

        def draw(self, fb: FrameBuffer) -> None:
            self._list.draw(fb)

    menu = _Menu()
    run_screen(display, input_mgr, menu, target_fps=target_fps, idle_wake=idle_wake)
    return menu.result


def _resolve_stick_root(volume: UsbVolume) -> tuple[Path | None, Path | None, str | None]:
    """Return (stick_root, mount_point_to_unmount, error_message)."""
    mount_point = DEFAULT_USB_MOUNT_POINT
    if volume.mountpoint == str(mount_point):
        return mount_point, None, None
    try:
        root = ensure_mounted(volume, mount_point)
        return root, mount_point, None
    except UsbMountError as exc:
        log.warning("mount failed for %s: %s", volume.device, exc)
        return None, None, str(exc)
    except Exception:
        log.exception("mount failed for %s", volume.device)
        return None, None, "Could not mount USB."


def _prompt_pin(
    display: Display,
    input_mgr: InputManager,
    *,
    prompt: str,
    target_fps: int,
    idle_wake: IdleWakeTracker | None,
) -> str | None:
    screen = PinEntryScreen(title=prompt, subtitle="Re-enter vault PIN")
    run_screen(display, input_mgr, screen, target_fps=target_fps, idle_wake=idle_wake)
    return screen.result


def run_usb_backup(
    display: Display,
    input_mgr: InputManager,
    *,
    vault_path: Path | None = None,
    settings_path: Path | None = None,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
) -> UsbFlowResult:
    unmount_after: Path | None = None
    flow: UsbFlowResult = "failed"

    try:
        volume = _pick_usb_volume(
            display,
            input_mgr,
            target_fps=target_fps,
            idle_wake=idle_wake,
            prompt="Backup — pick USB drive",
        )
        if volume is None:
            flow = "cancelled"
            return flow

        stick_root, unmount_after, mount_error = _resolve_stick_root(volume)
        if stick_root is None:
            _show_modal(
                display,
                input_mgr,
                title="Mount failed",
                body=(mount_error or "Could not mount USB.")[:80],
                accent=COLOR_DANGER,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
            return flow

        pin = _prompt_pin(
            display,
            input_mgr,
            prompt="Confirm PIN",
            target_fps=target_fps,
            idle_wake=idle_wake,
        )
        if pin is None:
            flow = "cancelled"
            return flow

        try:
            result = export_backup(
                stick_root,
                vault_path=vault_path or default_vault_path(),
                settings_path=settings_path or default_settings_path(),
                include_settings=True,
            )
        except BackupBundleError as exc:
            log.exception("export failed")
            _show_modal(
                display,
                input_mgr,
                title="Backup failed",
                body=str(exc)[:80],
                accent=COLOR_DANGER,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
            return flow
        except OSError as exc:
            log.exception("export failed")
            _show_modal(
                display,
                input_mgr,
                title="Backup failed",
                body=str(exc)[:80] or "Could not write to USB.",
                accent=COLOR_DANGER,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
            return flow

        rel = result.backup_dir.relative_to(stick_root)
        _show_modal(
            display,
            input_mgr,
            title="Backup saved",
            body=f"{rel}\nDisclaimer shown again after firmware upgrade.",
            target_fps=target_fps,
            idle_wake=idle_wake,
        )
        flow = "ok"
        return flow
    except Exception:
        log.exception("usb backup flow failed")
        return flow
    finally:
        if flow == "ok":
            _release_usb(unmount_after)


@dataclass
class _ImportPreviewScreen:
    manifest: BackupManifest
    import_settings: bool
    replace_existing: bool
    current_labels: tuple[str, ...]
    done: bool = False
    confirmed: bool = False
    result: bool | None = None

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if event.button == Button.B and event.kind in (
            EventKind.PRESS,
            EventKind.LONG,
        ):
            self.done = True
            self.result = False
            return
        if event.button in (Button.A, Button.SELECT) and event.kind == EventKind.PRESS:
            self.done = True
            self.confirmed = True
            self.result = True
            return
        if event.button == Button.RIGHT and event.kind == EventKind.PRESS:
            if self.manifest.has_settings:
                self.import_settings = not self.import_settings

    def draw(self, fb: FrameBuffer) -> None:
        fb.clear(COLOR_BG)
        title = "Replace wallets" if self.replace_existing else "Restore wallets"
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            16,
            title,
            size=14,
            color=COLOR_DANGER if self.replace_existing else COLOR_ACCENT,
            anchor="mm",
        )
        y = 36
        draw_text(fb, 8, y, "From backup:", size=11, color=COLOR_DIM, anchor="lm")
        y += 16
        for w in self.manifest.wallet_summary:
            draw_text(
                fb,
                12,
                y,
                f"{w.label}  {w.fingerprint}",
                size=11,
                color=COLOR_FG,
                anchor="lm",
            )
            y += 14
        if self.replace_existing and self.current_labels:
            y += 6
            draw_text(fb, 8, y, "Will erase:", size=11, color=COLOR_DANGER, anchor="lm")
            y += 16
            for label in self.current_labels:
                draw_text(fb, 12, y, label, size=11, color=COLOR_DANGER, anchor="lm")
                y += 14
        settings_line = (
            "Settings: import (RIGHT toggles)"
            if self.manifest.has_settings
            else "Settings: not in backup"
        )
        if self.manifest.has_settings:
            state = "yes" if self.import_settings else "no"
            settings_line = f"Import settings: {state} (RIGHT toggles)"
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 36,
            settings_line,
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 14,
            "A: continue   B: cancel",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )


def run_usb_restore(
    display: Display,
    input_mgr: InputManager,
    *,
    vault_path: Path | None = None,
    settings_path: Path | None = None,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
) -> UsbFlowResult:
    vault_path = vault_path or default_vault_path()
    settings_path = settings_path or default_settings_path()
    unmount_after: Path | None = None
    flow: UsbFlowResult = "failed"

    try:
        volume = _pick_usb_volume(
            display,
            input_mgr,
            target_fps=target_fps,
            idle_wake=idle_wake,
            prompt="Restore — pick USB drive",
        )
        if volume is None:
            flow = "cancelled"
            return flow

        stick_root, unmount_after, mount_error = _resolve_stick_root(volume)
        if stick_root is None:
            _show_modal(
                display,
                input_mgr,
                title="Mount failed",
                body=(mount_error or "Could not mount USB.")[:80],
                accent=COLOR_DANGER,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
            return flow

        backups = list_backup_summaries(stick_root)
        if not backups:
            _show_modal(
                display,
                input_mgr,
                title="No backups",
                body=f"Nothing under {STICK_ROOT_DIRNAME}/backups/",
                accent=COLOR_DANGER,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
            return flow

        @dataclass
        class _BackupPicker:
            done: bool = False
            result: BackupManifest | None = None
            _list: ListView = field(init=False)

            def __post_init__(self) -> None:
                items = []
                for manifest in backups:
                    wallets = ", ".join(w.label for w in manifest.wallet_summary) or "empty"
                    items.append(
                        ListItem(
                            label=f"{manifest.backup_dir_name}  {wallets}",
                            value=manifest,
                        )
                    )
                self._list = ListView(
                    items=items,
                    title="Pick backup",
                    footer="A: select   B: back",
                )

            def on_event(self, event: Event) -> None:
                if self.done:
                    return
                if event.button == Button.B and event.kind in (
                    EventKind.PRESS,
                    EventKind.LONG,
                ):
                    self.done = True
                    return
                self._list.on_event(event)
                if self._list.confirmed is not None:
                    self.done = True
                    self.result = self._list.confirmed  # type: ignore[assignment]

            def draw(self, fb: FrameBuffer) -> None:
                self._list.draw(fb)

        picker = _BackupPicker()
        run_screen(display, input_mgr, picker, target_fps=target_fps, idle_wake=idle_wake)
        manifest = picker.result
        if manifest is None:
            flow = "cancelled"
            return flow

        backup_dir = stick_backups_root(stick_root) / manifest.backup_dir_name
        try:
            vault = Vault(vault_path)
            replace_existing = vault.is_initialized and bool(vault.list_wallets())
            current_labels = (
                tuple(w.label for w in vault.list_wallets()) if replace_existing else ()
            )
        except VaultError as exc:
            log.exception("vault metadata read failed during restore preview")
            _show_modal(
                display,
                input_mgr,
                title="Restore failed",
                body=str(exc)[:80],
                accent=COLOR_DANGER,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
            return flow

        preview = _ImportPreviewScreen(
            manifest=manifest,
            import_settings=manifest.has_settings,
            replace_existing=replace_existing,
            current_labels=current_labels,
        )
        run_screen(display, input_mgr, preview, target_fps=target_fps, idle_wake=idle_wake)
        if not preview.confirmed:
            flow = "cancelled"
            return flow

        if replace_existing:
            confirm = DoubleConfirmScreen(
                title="Replace vault?",
                first_prompt="All current wallets on this device will be erased.",
                second_prompt="Hold A again to replace with the USB backup.",
                second_step_warning=True,
                second_title="Last chance",
            )
            run_screen(display, input_mgr, confirm, target_fps=target_fps, idle_wake=idle_wake)
            if confirm.result is not True:
                flow = "cancelled"
                return flow

        pin = _prompt_pin(
            display,
            input_mgr,
            prompt="Backup PIN",
            target_fps=target_fps,
            idle_wake=idle_wake,
        )
        if pin is None:
            flow = "cancelled"
            return flow

        try:
            import_backup(
                backup_dir,
                vault_path=vault_path,
                settings_path=settings_path,
                import_settings=preview.import_settings,
                pin=pin,
            )
        except BackupBundleError as exc:
            log.exception("import failed")
            _show_modal(
                display,
                input_mgr,
                title="Restore failed",
                body=str(exc)[:80],
                accent=COLOR_DANGER,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
            return flow
        except OSError as exc:
            log.exception("import failed")
            _show_modal(
                display,
                input_mgr,
                title="Restore failed",
                body=str(exc)[:80] or "Could not read from USB.",
                accent=COLOR_DANGER,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
            return flow

        _show_modal(
            display,
            input_mgr,
            title="Restored",
            body="Wallets imported. Unlock with backup PIN.",
            target_fps=target_fps,
            idle_wake=idle_wake,
        )
        flow = "ok"
        return flow
    except Exception:
        log.exception("usb restore flow failed")
        return flow
    finally:
        # Unmount only after a successful import. Mid-flow cancel keeps
        # the stick mounted so retry does not hit umount/remount issues.
        if flow == "ok":
            _release_usb(unmount_after)

