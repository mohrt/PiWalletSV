"""Touch settings covers the Zero Preferences and Maintenance items."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from piwallet.core.settings import BonnetSettings, load_settings
from piwallet.core.vault import Vault
from piwallet.diag.airgap import CheckResult
from piwallet.touch.input import Tap
from piwallet.touch.settings import SettingsFlow
from piwallet.ui.display import COLOR_ACCENT, COLOR_DANGER, FrameBuffer, HeadlessDisplay


@pytest.fixture(autouse=True)
def _fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    import piwallet.core.vault as vlt

    monkeypatch.setattr(vlt, "SCRYPT_N", 2**12)


def _flow(tmp_path, vault: Vault | None = None, **kwargs) -> SettingsFlow:
    if vault is None:
        vault = Vault(tmp_path / "vault.bin")
        vault.create("123456")
    return SettingsFlow(
        320,
        480,
        vault,
        "123456",
        settings_path=tmp_path / "settings.json",
        terms_path=tmp_path / "terms.json",
        settings=BonnetSettings(),
        **kwargs,
    )


def _choose(flow: SettingsFlow, action: str) -> None:
    hit = next(item for item in flow._hits() if item.id == action)
    flow.on_tap(Tap(*hit.center(), True))
    flow.on_tap(Tap(*hit.center(), False))


def _type_pin(flow: SettingsFlow, pin: str) -> None:
    assert flow._pad is not None
    for digit in pin:
        hit = flow._pad.grid.hit(digit)
        flow.on_tap(Tap(*hit.center(), True))
        flow.on_tap(Tap(*hit.center(), False))
    ok = flow._pad.grid.hit("ok")
    flow.on_tap(Tap(*ok.center(), True))
    flow.on_tap(Tap(*ok.center(), False))


def test_settings_hub_lists_preferences_and_maintenance(tmp_path) -> None:
    flow = _flow(tmp_path)
    _choose(flow, "preferences")
    assert [item.id for item in flow._hits() if item.id != "cancel"] == ["brightness", "sleep"]
    _choose(flow, "cancel")
    _choose(flow, "maintenance")
    assert [item.id for item in flow._hits() if item.id != "cancel"] == [
        "change_pin",
        "airgap",
        "usb",
        "about",
        "reset",
    ]


def test_brightness_screen_previews_then_saves_or_cancels(tmp_path) -> None:
    flow = _flow(tmp_path)
    display = HeadlessDisplay(width=320, height=480)
    flow.display = display
    _choose(flow, "preferences")
    _choose(flow, "brightness")
    assert [item.id for item in flow._hits()] == ["dim", "bright", "cancel", "save"]
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    bright = next(item for item in flow._hits() if item.id == "bright")
    dim = next(item for item in flow._hits() if item.id == "dim")
    bx, by = bright.center()
    dx, dy = dim.center()
    assert fb.image.getpixel((bx + 12, by)) == (240, 240, 240)
    assert fb.image.getpixel((bx + 20, by)) == (24, 24, 24)
    assert fb.image.getpixel((dx + 18, dy)) == (24, 24, 24)
    for expected in (0.8, 0.6, 0.4, 0.2):
        _choose(flow, "dim")
        assert flow._brightness_draft == expected
    assert display.brightness == 0.2
    assert flow.settings.brightness == 1.0
    _choose(flow, "cancel")
    assert display.brightness == 1.0
    assert flow.phase == "preferences"
    assert not (tmp_path / "settings.json").exists()
    _choose(flow, "brightness")
    _choose(flow, "dim")
    _choose(flow, "save")
    assert flow.settings.brightness == 0.8
    assert flow.phase == "preferences"
    assert load_settings(tmp_path / "settings.json").brightness == 0.8


def test_startup_keeps_a_saved_dim_brightness(tmp_path) -> None:
    from piwallet.core.settings import save_settings
    from piwallet.touch.input import ScriptedTouch
    from piwallet.touch.shell import run_touch_shell

    path = tmp_path / "settings.json"
    save_settings(BonnetSettings(brightness=0.2), path)
    display = HeadlessDisplay(width=320, height=480)
    run_touch_shell(
        display,
        ScriptedTouch([]),
        max_iterations=1,
        sleep=False,
        settings_path=path,
    )
    assert display.brightness == 0.2
    assert load_settings(path).brightness == 0.2


def test_sleep_timer_screen_saves_or_cancels(tmp_path) -> None:
    flow = _flow(tmp_path)
    _choose(flow, "preferences")
    _choose(flow, "sleep")
    assert [item.id for item in flow._hits()] == ["off", "min1", "min5", "cancel", "save"]
    assert flow._sleep_draft == 300_000
    _choose(flow, "off")
    assert flow.settings.sleep_timeout_ms == 300_000
    _choose(flow, "cancel")
    assert flow.phase == "preferences"
    assert not (tmp_path / "settings.json").exists()
    _choose(flow, "sleep")
    _choose(flow, "min1")
    _choose(flow, "save")
    assert flow.settings.sleep_timeout_ms == 60_000
    assert flow.phase == "preferences"
    assert load_settings(tmp_path / "settings.json").sleep_timeout_ms == 60_000


def test_change_pin_rewraps_the_vault(tmp_path) -> None:
    flow = _flow(tmp_path)
    _choose(flow, "maintenance")
    _choose(flow, "change_pin")
    _type_pin(flow, "123456")
    _type_pin(flow, "654321")
    _type_pin(flow, "654321")
    assert flow.new_pin == "654321"
    assert flow.phase == "message"
    flow.vault.check_pin("654321")


@pytest.mark.parametrize("typed", [(), ("123456",), ("123456", "654321")])
def test_cancel_abandons_the_whole_pin_change(tmp_path, typed) -> None:
    flow = _flow(tmp_path)
    _choose(flow, "maintenance")
    _choose(flow, "change_pin")
    for pin in typed:
        _type_pin(flow, pin)
    assert flow.phase in ("pin_current", "pin_new", "pin_confirm")
    cancel = (flow.width - 8 - 56, 18)
    flow.on_tap(Tap(*cancel, True))
    flow.on_tap(Tap(*cancel, False))
    assert flow.phase == "maintenance"
    assert flow._pad is None
    assert flow.new_pin is None
    flow.vault.check_pin("123456")


def test_about_shows_the_logo(tmp_path) -> None:
    flow = _flow(tmp_path)
    flow.phase = "about"
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    assert any(
        fb.image.getpixel((x, y)) != (0, 0, 0)
        for y in range(50, 180)
        for x in range(100, 220)
    )


def test_about_lists_pro_version_and_hardware(tmp_path) -> None:
    from piwallet import __version__
    from piwallet.device import get_device, hardware_rows

    hardware = hardware_rows(get_device("pi3-ws35f"), "Pi 3 Model B Rev 1.2")
    flow = _flow(tmp_path, hardware=hardware)
    rows = dict(flow._about_rows())
    assert rows["Version"] == f"v{__version__} Pro"
    assert rows["Pi"] == "Pi 3 Model B Rev 1.2"
    assert rows["HAT"] == "Waveshare 3.5in LCD (F)"
    assert rows["Camera"] == "ArduCam OV5647 5MP"


def test_read_pi_model_drops_the_raspberry_prefix(tmp_path) -> None:
    from piwallet.platform.pi_serial import read_pi_model

    model = tmp_path / "model"
    model.write_bytes(b"Raspberry Pi 3 Model B Rev 1.2\0")
    assert read_pi_model(model) == "Pi 3 Model B Rev 1.2"
    assert read_pi_model(tmp_path / "missing") is None


def test_airgap_shows_a_breach_when_a_radio_is_active(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "piwallet.touch.settings.check_airgap",
        lambda: SimpleNamespace(ok=False),
    )
    monkeypatch.setattr(
        "piwallet.touch.settings.checks_for_bonnet_display",
        lambda: (CheckResult(name="wifi", ok=False, detail="up"),),
    )
    flow = _flow(tmp_path)
    _choose(flow, "maintenance")
    _choose(flow, "airgap")
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    assert any(fb.image.getpixel((x, 16)) == COLOR_DANGER for x in range(20, 160))
    _choose(flow, "refresh")
    assert flow._airgap_ok is False


def test_about_lists_version_and_wallet_count(tmp_path) -> None:
    flow = _flow(tmp_path)
    _choose(flow, "maintenance")
    _choose(flow, "about")
    fb = FrameBuffer(width=320, height=480)
    flow.draw(fb)
    assert any(fb.image.getpixel((x, 16)) == (240, 240, 240) for x in range(12, 80))


def test_partition_button_shows_that_partitions_filesystem() -> None:
    from piwallet.backup.usb import UsbVolume
    from piwallet.touch.settings import _partition_label

    small = UsbVolume("/dev/sdb1", "200M", "", "vfat", None, model="Reader")
    large = UsbVolume("/dev/sdb2", "14.3G", "", "exfat", None, model="Reader")
    assert _partition_label(small) == "sdb1  200M  FAT32"
    assert _partition_label(large) == "sdb2  14.3G  exFAT"


def test_usb_screen_shows_the_device_name_then_its_partitions(tmp_path) -> None:
    from piwallet.backup.usb import UsbVolume

    volumes = [
        UsbVolume("/dev/sda1", "29.1G", "", "vfat", None, model="Card Reader"),
        UsbVolume("/dev/sdb1", "200M", "", "vfat", None, model="SanDisk Ultra"),
        UsbVolume("/dev/sdb2", "14.3G", "", "exfat", None, model="SanDisk Ultra"),
    ]
    flow = _flow(tmp_path, list_volumes=lambda: volumes)
    _choose(flow, "maintenance")
    _choose(flow, "usb")
    _choose(flow, "backup")
    headings, hits = flow._volume_blocks()
    assert [name for name, _y in headings] == ["Card Reader", "SanDisk Ultra"]
    buttons = [item for item in hits if item.id.startswith("vol:")]
    assert [item.id for item in buttons] == ["vol:0", "vol:1", "vol:2"]
    assert buttons[1].y0 - buttons[0].y0 > 48
    assert buttons[2].y0 - buttons[1].y0 == 48


def test_usb_screen_follows_plug_and_unplug(tmp_path) -> None:
    from piwallet.backup.usb import UsbVolume

    stick = UsbVolume(device="/dev/sda1", size="29.1G", label="", fstype="vfat", mountpoint=None)
    scans = [[], [stick], []]

    def _list():
        return scans.pop(0) if scans else []

    flow = _flow(tmp_path, list_volumes=_list)
    _choose(flow, "maintenance")
    _choose(flow, "usb")
    _choose(flow, "backup")
    assert flow.phase == "usb_wait"
    flow._usb_scan_at = 0
    assert flow.tick() is True
    assert flow.phase == "volumes"
    assert [item.device for item in flow._volumes] == ["/dev/sda1"]
    flow._usb_scan_at = 0
    assert flow.tick() is True
    assert flow.phase == "usb_wait"
    assert flow._volumes == []


def test_usb_backup_writes_the_vault(tmp_path, monkeypatch) -> None:
    stick = tmp_path / "stick"
    stick.mkdir()
    monkeypatch.setattr("piwallet.touch.settings.ensure_mounted", lambda volume, mount: stick)
    released = {"n": 0}
    monkeypatch.setattr(
        "piwallet.touch.settings.release_usb_session",
        lambda: released.__setitem__("n", released["n"] + 1),
    )
    saved: dict = {}

    def _export(root, **kwargs):
        saved["root"] = root
        saved.update(kwargs)
        return SimpleNamespace(backup_dir=stick / "2026")

    monkeypatch.setattr("piwallet.touch.settings.export_backup", _export)
    volume = SimpleNamespace(display_name="STICK  1G")
    flow = _flow(tmp_path, list_volumes=lambda: [volume])
    _choose(flow, "maintenance")
    _choose(flow, "usb")
    _choose(flow, "backup")
    _choose(flow, "vol:0")
    _type_pin(flow, "123456")
    assert flow._message_title == "Backup saved"
    assert saved["root"] == stick
    assert saved["vault_path"] == flow.vault.path
    assert released["n"] == 1


def test_usb_restore_replaces_the_vault_and_asks_to_unlock(tmp_path, monkeypatch) -> None:
    stick = tmp_path / "stick"
    stick.mkdir()
    monkeypatch.setattr("piwallet.touch.settings.ensure_mounted", lambda volume, mount: stick)
    monkeypatch.setattr("piwallet.touch.settings.release_usb_session", lambda: None)
    monkeypatch.setattr(
        "piwallet.touch.settings.list_backup_summaries",
        lambda root: [SimpleNamespace(backup_dir_name="2026", has_settings=True)],
    )
    imported: dict = {}

    def _import(backup_dir, **kwargs):
        imported["dir"] = backup_dir
        imported.update(kwargs)

    monkeypatch.setattr("piwallet.touch.settings.import_backup", _import)
    flow = _flow(tmp_path, list_volumes=lambda: [SimpleNamespace(display_name="STICK")])
    _choose(flow, "maintenance")
    _choose(flow, "usb")
    _choose(flow, "restore")
    _choose(flow, "vol:0")
    _choose(flow, "bak:0")
    assert flow._pad is not None
    assert flow._pad.grid.title == "Current PIN"
    _type_pin(flow, "000000")
    assert flow.restored is False
    assert "pin" not in imported
    _type_pin(flow, "123456")
    assert flow._pad is not None
    assert flow._pad.grid.title == "Backup PIN"
    _type_pin(flow, "654321")
    assert flow.restored is True
    assert flow.done is True
    assert flow.new_pin == "654321"
    assert imported["pin"] == "654321"
    assert imported["import_settings"] is True


def test_factory_reset_erases_the_vault_after_two_confirms(tmp_path) -> None:
    flow = _flow(tmp_path)
    _choose(flow, "maintenance")
    _choose(flow, "reset")
    _choose(flow, "erase")
    assert flow.phase == "reset2"
    _choose(flow, "erase")
    assert flow._pad is not None
    assert flow._pad.grid.title == "Verify PIN"
    _type_pin(flow, "123456")
    assert flow.factory_reset is True
    assert flow.vault.path.exists() is False
    assert (tmp_path / "settings.json").exists() is False


def test_wake_from_sleep_asks_for_the_pin_again(tmp_path, monkeypatch) -> None:
    from piwallet.core.settings import save_settings
    from piwallet.touch.create import PinPad
    from piwallet.touch.shell import run_touch_shell
    from piwallet.touch.ui import WalletHome

    vault = Vault(tmp_path / "vault.bin")
    vault.create("123456")
    save_settings(BonnetSettings(sleep_timeout_ms=60_000), tmp_path / "settings.json")
    pad = PinPad(320, 480, title="Enter PIN", masked=True)
    pin_taps: list[Tap] = []
    for digit in "123456":
        pin_taps.append(Tap(*pad.grid.hit(digit).center(), True))
        pin_taps.append(Tap(*pad.grid.hit(digit).center(), False))
    pin_taps.append(Tap(*pad.grid.hit("ok").center(), True))
    pin_taps.append(Tap(*pad.grid.hit("ok").center(), False))
    opened: list[str] = []
    original = PinPad.__init__

    def _spy(self, width: int, height: int, *, title: str, masked: bool = False) -> None:
        original(self, width, height, title=title, masked=masked)
        opened.append(title)

    monkeypatch.setattr(PinPad, "__init__", _spy)
    clock = {"now": 0.0}

    class _Touch:
        def __init__(self) -> None:
            self._taps = list(pin_taps)
            self._phase = "unlock"

        def poll(self) -> Tap | None:
            if self._phase == "unlock":
                if self._taps:
                    return self._taps.pop(0)
                self._phase = "asleep"
                clock["now"] = 120.0
                return None
            if self._phase == "asleep":
                self._phase = "relock"
                self._taps = list(pin_taps)
                return Tap(12, 12, True)
            if self._taps:
                return self._taps.pop(0)
            return None

    monkeypatch.setattr("piwallet.touch.shell.time.monotonic", lambda: clock["now"])
    display = HeadlessDisplay(width=320, height=480)
    run_touch_shell(
        display,
        _Touch(),  # type: ignore[arg-type]
        vault=vault,
        max_iterations=len(pin_taps) + 2 + len(pin_taps),
        sleep=False,
        settings_path=tmp_path / "settings.json",
    )
    home = WalletHome(320, 480)
    expected = FrameBuffer(width=320, height=480)
    home.draw(expected)
    assert opened == ["Enter PIN", "Enter PIN"]
    assert display.image.tobytes() == expected.image.tobytes()


def test_shell_opens_settings_and_blanks_after_the_sleep_timer(tmp_path, monkeypatch) -> None:
    from piwallet.touch.create import PinPad
    from piwallet.touch.input import ScriptedTouch
    from piwallet.touch.shell import run_touch_shell
    from piwallet.touch.ui import WalletHome

    vault = Vault(tmp_path / "vault.bin")
    vault.create("123456")
    opened: list[SettingsFlow] = []
    original = SettingsFlow.__init__

    def _spy(self, *args, **kwargs):
        original(self, *args, **kwargs)
        opened.append(self)

    monkeypatch.setattr(SettingsFlow, "__init__", _spy)
    pad = PinPad(320, 480, title="Enter PIN", masked=True)
    taps: list[Tap] = []
    for digit in "123456":
        taps.append(Tap(*pad.grid.hit(digit).center(), True))
        taps.append(Tap(*pad.grid.hit(digit).center(), False))
    taps.append(Tap(*pad.grid.hit("ok").center(), True))
    taps.append(Tap(*pad.grid.hit("ok").center(), False))
    home = WalletHome(320, 480)
    taps.append(Tap(*home.hit("settings").center(), True))
    taps.append(Tap(*home.hit("settings").center(), False))
    display = HeadlessDisplay(width=320, height=480)
    run_touch_shell(
        display,
        ScriptedTouch(taps),
        vault=vault,
        max_iterations=len(taps),
        sleep=False,
        settings_path=tmp_path / "settings.json",
    )
    assert opened and opened[0].phase == "hub"

    monkeypatch.setattr(
        "piwallet.touch.shell.load_settings",
        lambda path=None: BonnetSettings(sleep_timeout_ms=1),
    )
    blank = HeadlessDisplay(width=320, height=480)
    run_touch_shell(
        blank,
        ScriptedTouch([]),
        vault=vault,
        max_iterations=2,
        sleep=False,
        settings_path=tmp_path / "settings.json",
    )
    assert not any(
        blank.image.getpixel((x, y)) == COLOR_ACCENT
        for y in range(0, blank.height, 4)
        for x in range(0, blank.width, 4)
    )
