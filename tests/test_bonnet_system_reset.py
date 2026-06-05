"""System reset flow from Settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from piwallet.bonnet import system_reset as sr
from piwallet.core.settings import BonnetSettings, save_settings
from piwallet.core.vault import Vault
from piwallet.firstboot.terms import mark_accepted, requires_acceptance
from piwallet.ui.display import HeadlessDisplay
from piwallet.ui.double_confirm import DoubleConfirmScreen
from piwallet.ui.input import FakeInputBackend, InputManager


@pytest.fixture
def device_state(tmp_path: Path) -> tuple[Path, Path, Path, Vault, str]:
    vault_path = tmp_path / "vault.bin"
    settings_path = tmp_path / "settings.json"
    terms_path = tmp_path / "terms.json"
    vault = Vault(vault_path)
    vault.create(pin="123456")
    save_settings(BonnetSettings(), settings_path)
    mark_accepted(terms_path)
    return vault_path, settings_path, terms_path, vault, "123456"


def test_run_system_reset_cancelled_at_confirm(
    monkeypatch: pytest.MonkeyPatch,
    device_state: tuple[Path, Path, Path, Vault, str],
) -> None:
    vault_path, settings_path, terms_path, vault, _pin = device_state
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(_d, _m, screen, **_):
        if isinstance(screen, DoubleConfirmScreen):
            screen.done = True
            screen.result = False
        return screen.result

    monkeypatch.setattr(sr, "run_screen", fake_run_screen)

    assert sr.run_system_reset(
        display,
        mgr,
        vault,
        vault_path=vault_path,
        settings_path=settings_path,
        terms_path=terms_path,
        toast_seconds=0,
    ) == "cancelled"
    assert vault_path.exists()


def test_run_system_reset_completed_wipes_state(
    monkeypatch: pytest.MonkeyPatch,
    device_state: tuple[Path, Path, Path, Vault, str],
) -> None:
    vault_path, settings_path, terms_path, vault, pin = device_state
    display = HeadlessDisplay()
    mgr = InputManager(FakeInputBackend())

    def fake_run_screen(_d, _m, screen, **_):
        if isinstance(screen, DoubleConfirmScreen):
            screen.done = True
            screen.result = True
            return True
        from piwallet.bonnet.unlock import UnlockOutcome

        screen.done = True
        screen.result = UnlockOutcome(kind="ok", pin=pin)
        return screen.result

    monkeypatch.setattr(sr, "run_screen", fake_run_screen)
    monkeypatch.setattr(sr.time, "sleep", lambda _: None)

    assert sr.run_system_reset(
        display,
        mgr,
        vault,
        vault_path=vault_path,
        settings_path=settings_path,
        terms_path=terms_path,
        toast_seconds=0,
    ) == "completed"
    assert not vault_path.exists()
    assert not settings_path.exists()
    assert not terms_path.exists()
    assert requires_acceptance(terms_path) is True
