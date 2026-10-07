"""Boot logo and the touch diagnostics menu."""

from __future__ import annotations

import pytest

from piwallet.core.vault import Vault
from piwallet.diag.airgap import CheckResult
from piwallet.touch.factory_menu import DiagnosticsFlow, run_touch_diagnostics, touch_software_checks
from piwallet.touch.input import ScriptedTouch, Tap
from piwallet.touch.splash import run_touch_splash
from piwallet.ui.display import HeadlessDisplay


def _clock(values: list[float]):
    pending = list(values)

    def clock() -> float:
        return pending.pop(0)

    return clock


def test_splash_continues_after_a_couple_of_seconds() -> None:
    display = HeadlessDisplay(width=320, height=480)
    outcome = run_touch_splash(
        display,
        ScriptedTouch([]),
        idle_s=2.0,
        clock=_clock([0.0, 0.0, 2.0]),
        sleep=False,
    )
    assert outcome == "continue"


def test_splash_hold_opens_diagnostics() -> None:
    display = HeadlessDisplay(width=320, height=480)
    outcome = run_touch_splash(
        display,
        ScriptedTouch([Tap(10, 10, True)]),
        hold_s=5.0,
        idle_s=2.0,
        clock=_clock([0.0, 0.0, 5.0]),
        sleep=False,
    )
    assert outcome == "diagnostics"


def test_splash_release_before_five_seconds_continues() -> None:
    display = HeadlessDisplay(width=320, height=480)
    outcome = run_touch_splash(
        display,
        ScriptedTouch([Tap(10, 10, True), Tap(10, 10, False)]),
        hold_s=5.0,
        idle_s=2.0,
        clock=_clock([0.0, 0.2, 0.4, 2.0]),
        sleep=False,
    )
    assert outcome == "continue"


def test_checks_list_each_radio_once(monkeypatch, tmp_path) -> None:
    fake = [
        CheckResult("spi_device", None, ""),
        CheckResult("backlight_gpio", None, ""),
        CheckResult("camera", True, ""),
        CheckResult("vault_dir", True, ""),
        CheckResult("serial", True, ""),
        CheckResult("wifi", False, "loaded"),
        CheckResult("bluetooth", False, "loaded"),
        CheckResult("network", False, "wlan0"),
        CheckResult("rfkill", False, "unblocked"),
        CheckResult("services", False, "active"),
        CheckResult("boot_config", False, "missing"),
        CheckResult("blacklist", False, "missing"),
    ]
    monkeypatch.setattr("piwallet.touch.factory_menu.collect_software_checks", lambda vault_path: fake)
    monkeypatch.setattr(
        "piwallet.touch.factory_menu.checks_for_bonnet_display",
        lambda: (
            CheckResult("wifi", False, "loaded"),
            CheckResult("bluetooth", False, "loaded"),
            CheckResult("network", False, "wlan0"),
        ),
    )
    assert [check.display_name for check in touch_software_checks(tmp_path / "vault.bin")] == [
        "camera",
        "vault dir",
        "serial",
        "Wi-Fi",
        "Bluetooth",
        "Network",
    ]


def test_camera_test_uses_the_panel_rotation(tmp_path, monkeypatch) -> None:
    seen: dict = {}

    def _start(state, **kwargs) -> None:
        seen.update(kwargs)

    monkeypatch.setattr("piwallet.touch.factory_menu.start_camera_preview_worker", _start)
    vault = Vault(tmp_path / "vault.bin")
    flow = DiagnosticsFlow(320, 480, vault, terms_path=tmp_path / "terms.json", camera_rotation=180)
    flow._open("camera")
    assert seen["rotation_degrees"] == 180


def test_diagnostics_menu_has_no_back_button(tmp_path) -> None:
    vault = Vault(tmp_path / "vault.bin")
    flow = DiagnosticsFlow(320, 480, vault, terms_path=tmp_path / "terms.json")
    assert [item.id for item in flow._hits()] == ["info", "checks", "camera", "screen", "restart"]
    flow._open("info")
    assert any(item.id == "cancel" for item in flow._hits())


def test_diagnostics_restart_confirms_once(tmp_path) -> None:
    vault = Vault(tmp_path / "vault.bin")
    flow = DiagnosticsFlow(320, 480, vault, terms_path=tmp_path / "terms.json")

    def choose(action: str) -> None:
        hit = next(item for item in flow._hits() if item.id == action)
        flow.on_tap(Tap(*hit.center(), True))
        flow.on_tap(Tap(*hit.center(), False))

    choose("restart")
    assert flow.phase == "restart"
    assert flow.done is False
    choose("go")
    assert flow.result == "restart"


def test_shell_restart_asks_the_cli_to_relaunch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("piwallet.touch.splash.run_touch_splash", lambda *args, **kwargs: "diagnostics")
    monkeypatch.setattr(
        "piwallet.touch.factory_menu.run_touch_diagnostics",
        lambda *args, **kwargs: "restart",
    )
    from piwallet.touch.shell import TouchRestart, run_touch_shell

    with pytest.raises(TouchRestart):
        run_touch_shell(
            HeadlessDisplay(width=320, height=480),
            ScriptedTouch([]),
            vault=Vault(tmp_path / "vault.bin"),
            settings_path=tmp_path / "settings.json",
            splash=True,
            sleep=False,
        )


def test_relaunch_replaces_this_process(monkeypatch) -> None:
    seen: dict = {}

    def _exec(path: str, argv: list[str]) -> None:
        seen["path"] = path
        seen["argv"] = list(argv)
        raise SystemExit(0)

    monkeypatch.setattr("piwallet.touch.shell.os.execvp", _exec)
    monkeypatch.setattr(
        "piwallet.touch.shell.sys.argv",
        [".venv/bin/piwallet", "touch", "--device", "pi3-ws35f"],
    )
    from piwallet.touch.shell import relaunch_process

    with pytest.raises(SystemExit):
        relaunch_process()
    assert seen["path"] == ".venv/bin/piwallet"
    assert seen["argv"] == [".venv/bin/piwallet", "touch", "--device", "pi3-ws35f"]


def _disclaimer_hit(action: str):
    from piwallet.touch.disclaimer import TouchDisclaimer

    flow = TouchDisclaimer(320, 480)
    return next(item for item in flow.hits() if item.id == action)


def test_disclaimer_accepts_when_held() -> None:
    from piwallet.touch.disclaimer import run_touch_disclaimer

    accepted = run_touch_disclaimer(
        HeadlessDisplay(width=320, height=480),
        ScriptedTouch([Tap(*_disclaimer_hit("accept").center(), True)]),
        clock=_clock([0.0, 0.8]),
        sleep=False,
    )
    assert accepted is True


def test_shell_records_disclaimer_acceptance(tmp_path, monkeypatch) -> None:
    from piwallet.firstboot.terms import requires_acceptance
    from piwallet.touch.shell import run_touch_shell

    monkeypatch.setattr("piwallet.touch.disclaimer.run_touch_disclaimer", lambda *args, **kwargs: True)
    terms = tmp_path / "terms.json"
    run_touch_shell(
        HeadlessDisplay(width=320, height=480),
        ScriptedTouch([]),
        vault=Vault(tmp_path / "vault.bin"),
        settings_path=tmp_path / "settings.json",
        terms_path=terms,
        splash=False,
        disclaimer=True,
        sleep=False,
        max_iterations=1,
    )
    assert not requires_acceptance(terms)
