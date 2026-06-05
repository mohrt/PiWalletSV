"""Factory reset wipes vault, settings, and terms state."""

from __future__ import annotations

from pathlib import Path

from piwallet.core.factory_reset import factory_reset
from piwallet.core.settings import BonnetSettings, save_settings
from piwallet.core.vault import Vault
from piwallet.firstboot.terms import mark_accepted, requires_acceptance


def test_factory_reset_removes_vault_settings_and_terms(tmp_path: Path) -> None:
    vault_path = tmp_path / "vault.bin"
    settings_path = tmp_path / "settings.json"
    terms_path = tmp_path / "terms.json"

    vault = Vault(vault_path)
    vault.create(pin="123456")
    save_settings(BonnetSettings(brightness=0.4), settings_path)
    mark_accepted(terms_path)

    factory_reset(
        vault_path=vault_path,
        settings_path=settings_path,
        terms_path=terms_path,
    )

    assert not vault_path.exists()
    assert not settings_path.exists()
    assert not terms_path.exists()
    assert requires_acceptance(terms_path) is True

    reloaded = Vault(vault_path)
    assert reloaded.exists is False
    assert reloaded.is_initialized is False
