"""Tests for bonnet USB volume picker (wait + select)."""

from __future__ import annotations

from piwallet.backup.usb import UsbVolume
from piwallet.bonnet.usb_backup import UsbConfirmModalScreen, UsbVolumePickerScreen
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


def _evt(b: Button, k: EventKind = EventKind.PRESS) -> Event:
    return Event(button=b, kind=k, at_ms=0)


def _sample_volume() -> UsbVolume:
    return UsbVolume(
        device="/dev/sda1",
        size="8G",
        label="STICK",
        fstype="vfat",
        mountpoint=None,
    )


def test_waits_until_usb_appears_then_lists_it() -> None:
    scans = iter([[], [_sample_volume()]])
    screen = UsbVolumePickerScreen(
        prompt="Backup — pick USB drive",
        list_volumes=lambda: next(scans, [_sample_volume()]),
        scan_interval_s=0,
    )
    fb = FrameBuffer()
    screen.draw(fb)
    assert screen._list is None
    screen.draw(fb)
    assert screen._list is not None


def test_a_rescan_finds_usb_without_waiting_for_interval() -> None:
    scans = iter([[], [_sample_volume()]])
    screen = UsbVolumePickerScreen(
        prompt="Backup — pick USB drive",
        list_volumes=lambda: next(scans, []),
        scan_interval_s=999,
    )
    fb = FrameBuffer()
    screen.draw(fb)  # initial poll — still empty
    screen.on_event(_evt(Button.A))  # manual rescan
    assert screen._list is not None


def test_b_cancels_while_waiting() -> None:
    screen = UsbVolumePickerScreen(
        prompt="Backup — pick USB drive",
        list_volumes=lambda: [],
        scan_interval_s=0,
    )
    screen.on_event(_evt(Button.B))
    assert screen.done is True
    assert screen.result is None


def test_select_volume_after_list_shown() -> None:
    vol = _sample_volume()
    screen = UsbVolumePickerScreen(
        prompt="Backup — pick USB drive",
        list_volumes=lambda: [vol],
        scan_interval_s=0,
    )
    fb = FrameBuffer()
    screen.draw(fb)
    screen.on_event(_evt(Button.A))
    assert screen.done is True
    assert screen.result is vol


def test_import_preview_cancel_does_not_confirm() -> None:
    from piwallet.backup.manifest import BackupManifest, WalletSummary
    from piwallet.bonnet.usb_backup import _ImportPreviewScreen
    from piwallet.ui.app import run_screen
    from piwallet.ui.display import HeadlessDisplay
    from piwallet.ui.input import FakeInputBackend, InputManager

    manifest = BackupManifest(
        bundle_version=1,
        exported_at="2026-01-01T00:00:00Z",
        piwalletsv_version="0.0.0",
        vault_version=2,
        wallet_summary=(WalletSummary(label="daily", fingerprint="abcd1234"),),
        has_settings=False,
        backup_dir_name="20260101-000000Z",
    )
    screen = _ImportPreviewScreen(
        manifest=manifest,
        import_settings=False,
        replace_existing=True,
        current_labels=("old",),
    )
    screen.on_event(_evt(Button.B))
    assert screen.done is True
    assert screen.confirmed is False
    assert screen.result is False
    returned = run_screen(
        HeadlessDisplay(),
        InputManager(FakeInputBackend()),
        screen,
        sleep=False,
        max_iterations=1,
    )
    assert returned is False


def test_confirm_modal_dismisses_on_a_or_b() -> None:
    from piwallet.ui.app import run_screen
    from piwallet.ui.display import HeadlessDisplay
    from piwallet.ui.input import FakeInputBackend, InputManager

    screen = UsbConfirmModalScreen(title="Backup saved", body="done")
    screen.on_event(_evt(Button.A))
    assert screen.done is True
    assert run_screen(
        HeadlessDisplay(),
        InputManager(FakeInputBackend()),
        screen,
        sleep=False,
        max_iterations=1,
    ) is None
    screen = UsbConfirmModalScreen(title="Backup failed", body="oops", accent=(255, 0, 0))
    screen.on_event(_evt(Button.B))
    assert screen.done is True
