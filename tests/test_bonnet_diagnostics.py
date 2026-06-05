"""Boot splash and diagnostics menu tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from piwallet.bonnet.diagnostics_sw import (
    SoftwareChecksScreen,
    _soften_radio_for_factory,
    collect_software_checks,
)
from piwallet.diag.airgap import CheckResult
from piwallet.bonnet.splash import BootSplashScreen
from piwallet.bonnet.utility import (
    DiagnosticsAction,
    DiagnosticsInfoScreen,
    DiagnosticsMenuScreen,
    build_info_rows,
    run_diagnostics_restart,
)
from piwallet.bonnet.utility_hw_tests import (
    ButtonsTestScreen,
    JoystickTestScreen,
    ScreenTestScreen,
)
from piwallet.core.vault import Vault
from piwallet.firstboot.terms import mark_accepted
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


def _evt(b: Button, k: EventKind = EventKind.PRESS, at_ms: int = 0) -> Event:
    return Event(button=b, kind=k, at_ms=at_ms)


def test_boot_splash_a_continues() -> None:
    s = BootSplashScreen(clock_ms=lambda: 0)
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "continue"


def test_boot_splash_hold_b_enters_diagnostics() -> None:
    clock = {"t": 0}

    def tick() -> int:
        return clock["t"]

    s = BootSplashScreen(clock_ms=tick, diagnostics_hold_ms=5000)
    s.on_event(_evt(Button.B, EventKind.PRESS, at_ms=0))
    clock["t"] = 5000
    s.draw(FrameBuffer())
    assert s.done is True
    assert s.result == "diagnostics"


def test_boot_splash_idle_timeout_continues() -> None:
    clock = {"t": 0}

    def tick() -> int:
        return clock["t"]

    s = BootSplashScreen(clock_ms=tick, idle_timeout_ms=3000)
    clock["t"] = 3000
    s.draw(FrameBuffer())
    assert s.done is True
    assert s.result == "continue"


def test_diagnostics_menu_b_release_returns_back() -> None:
    s = DiagnosticsMenuScreen()
    s.on_event(_evt(Button.B, EventKind.PRESS))
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is False
    s.on_event(_evt(Button.B, EventKind.RELEASE))
    assert s.done is True
    assert s.result == "back"


def test_diagnostics_menu_long_b_does_not_exit() -> None:
    s = DiagnosticsMenuScreen()
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is False


def test_diagnostics_menu_a_confirms_selection() -> None:
    s = DiagnosticsMenuScreen()
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result is DiagnosticsAction.INFO


def test_run_diagnostics_restart_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piwallet.ui.display import HeadlessDisplay
    from piwallet.ui.double_confirm import DoubleConfirmScreen
    from piwallet.ui.input import FakeInputBackend, InputManager

    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(_d, _m, screen, **_):
        if isinstance(screen, DoubleConfirmScreen):
            screen.done = True
            screen.result = False
        return screen.result

    monkeypatch.setattr("piwallet.bonnet.utility.run_screen", fake_run_screen)

    assert run_diagnostics_restart(display, mgr, toast_seconds=0) is False


def test_run_diagnostics_restart_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from piwallet.ui.display import HeadlessDisplay
    from piwallet.ui.double_confirm import DoubleConfirmScreen
    from piwallet.ui.input import FakeInputBackend, InputManager

    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(_d, _m, screen, **_):
        if isinstance(screen, DoubleConfirmScreen):
            screen.done = True
            screen.result = True
        return screen.result

    monkeypatch.setattr("piwallet.bonnet.utility.run_screen", fake_run_screen)
    monkeypatch.setattr("piwallet.bonnet.utility.time.sleep", lambda _: None)

    assert run_diagnostics_restart(display, mgr, toast_seconds=0) is True


def test_diagnostics_info_a_or_b_returns_back() -> None:
    s = DiagnosticsInfoScreen(rows=[("Version", "v0.0.0")])
    s.on_event(_evt(Button.A))
    assert s.done is True
    assert s.result == "back"


def test_build_info_rows(tmp_path: Path) -> None:
    terms = tmp_path / "terms.json"
    mark_accepted(terms, now=lambda: "2026-05-10T00:00:00+00:00")
    vault_path = tmp_path / "vault.bin"
    vault = Vault(vault_path)
    vault.create(pin="123456")

    rows = build_info_rows(vault=vault, terms_path=terms)
    values = dict(rows)
    labels = [k for k, _ in rows]
    assert "Version" in labels
    assert values["Vault"] == "ready"
    assert values["Unlock tries"] == "10"
    assert values["Terms"].startswith("v")
    assert "Network" not in labels


def test_build_info_rows_missing_vault(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "missing.bin")
    rows = build_info_rows(vault=vault)
    values = dict(rows)
    assert values["Vault"] == "missing"
    assert values["Unlock tries"] == "—"


def test_soften_radio_when_rfkill_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fail = CheckResult("wifi", False, "loaded: brcmfmac")
    monkeypatch.setattr(
        "piwallet.bonnet.diagnostics_sw.check_rfkill_all_blocked",
        lambda: CheckResult("rfkill", True, "2 radio(s) blocked"),
    )
    softened = _soften_radio_for_factory(fail)
    assert softened.ok is True
    assert softened.name == "wifi"
    assert "rfkill blocked" in softened.detail


def test_collect_software_checks(tmp_path: Path) -> None:
    checks = collect_software_checks(vault_path=tmp_path / "vault.bin")
    names = {c.name for c in checks}
    assert "gpio" not in names
    assert "modules" not in names
    assert "wifi" in names
    assert "bluetooth" in names
    assert "network" in names
    assert "vault_dir" in names
    assert "serial" in names


def test_joystick_test_tracks_press_and_back() -> None:
    s = JoystickTestScreen()
    s.on_event(_evt(Button.UP))
    assert Button.UP in s._tracker.down
    s.on_event(_evt(Button.B))
    assert s.done is True
    assert s.result == "back"


def test_joystick_test_select_does_not_exit() -> None:
    s = JoystickTestScreen()
    s.on_event(_evt(Button.SELECT))
    assert s.done is False
    assert Button.SELECT in s._tracker.down


def test_buttons_test_tracks_a_b_without_short_b_exiting() -> None:
    s = ButtonsTestScreen()
    s.on_event(_evt(Button.A))
    assert Button.A in s._tracker.down
    assert s.done is False
    s.on_event(_evt(Button.B))
    assert Button.B in s._tracker.down
    assert s.done is False
    s.on_event(_evt(Button.B, EventKind.LONG))
    assert s.done is True
    assert s.result == "back"


def test_screen_test_cycles_patterns() -> None:
    s = ScreenTestScreen()
    s.on_event(_evt(Button.RIGHT))
    assert s.pattern_index == 1
    s.on_event(_evt(Button.LEFT))
    assert s.pattern_index == 0


def test_diagnostics_screens_draw(tmp_path: Path) -> None:
    fb = FrameBuffer()
    BootSplashScreen(clock_ms=lambda: 0).draw(fb)
    DiagnosticsMenuScreen().draw(fb)
    DiagnosticsInfoScreen(rows=[("Version", "v0.0.0")]).draw(fb)
    SoftwareChecksScreen(vault_path=tmp_path / "vault.bin").draw(fb)
    JoystickTestScreen().draw(fb)
    ButtonsTestScreen().draw(fb)
    ScreenTestScreen().draw(fb)
