"""Tests for USB/directory vault backup export and import."""

from __future__ import annotations

from pathlib import Path

import cbor2
import pytest

from piwallet.backup.bundle import (
    BackupBundleError,
    export_backup,
    import_backup,
    list_backup_summaries,
)
from piwallet.backup.manifest import (
    BACKUP_BUNDLE_VERSION,
    BackupManifestError,
    load_manifest,
)
from piwallet.backup.vault_peek import peek_vault_file
from piwallet.core.settings import BonnetSettings, load_settings, save_settings
from piwallet.core.vault import Vault

CANONICAL_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)
GOOD_PIN = "123456"


@pytest.fixture
def vault_with_wallet(tmp_path: Path) -> Path:
    path = tmp_path / "vault.bin"
    vault = Vault(path)
    vault.create(pin=GOOD_PIN)
    vault.add_wallet(
        pin=GOOD_PIN,
        mnemonic_phrase=CANONICAL_MNEMONIC,
        label="daily",
    )
    return path


def test_export_import_round_trip(tmp_path: Path, vault_with_wallet: Path) -> None:
    stick = tmp_path / "usb"
    stick.mkdir()
    settings_path = tmp_path / "settings.json"
    save_settings(BonnetSettings(brightness=0.42), settings_path)

    result = export_backup(
        stick,
        vault_path=vault_with_wallet,
        settings_path=settings_path,
        include_settings=True,
    )
    assert result.manifest.has_settings
    assert (result.backup_dir / "vault.bin").is_file()
    assert (result.backup_dir / "settings.json").is_file()
    assert (result.backup_dir / "manifest.json").is_file()
    assert not (result.backup_dir / "terms.json").exists()

    dest_vault = tmp_path / "restored.bin"
    import_backup(
        result.backup_dir,
        vault_path=dest_vault,
        settings_path=tmp_path / "restored-settings.json",
        import_settings=True,
        pin=GOOD_PIN,
    )
    restored = Vault(dest_vault)
    wallets = restored.list_wallets()
    assert len(wallets) == 1
    assert wallets[0].label == "daily"


def test_import_wrong_pin_fails(tmp_path: Path, vault_with_wallet: Path) -> None:
    stick = tmp_path / "usb"
    stick.mkdir()
    result = export_backup(stick, vault_path=vault_with_wallet, include_settings=False)
    dest = tmp_path / "dest.bin"
    with pytest.raises(BackupBundleError, match="PIN"):
        import_backup(result.backup_dir, vault_path=dest, pin="999999")


def test_list_backups_newest_first(tmp_path: Path, vault_with_wallet: Path) -> None:
    stick = tmp_path / "usb"
    stick.mkdir()
    export_backup(stick, vault_path=vault_with_wallet, include_settings=False)
    summaries = list_backup_summaries(stick)
    assert len(summaries) == 1
    assert summaries[0].wallet_summary[0].label == "daily"


def test_reject_newer_bundle_version(tmp_path: Path, vault_with_wallet: Path) -> None:
    stick = tmp_path / "usb"
    stick.mkdir()
    result = export_backup(stick, vault_path=vault_with_wallet, include_settings=False)
    manifest_path = result.backup_dir / "manifest.json"
    text = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        text.replace(
            f'"bundleVersion": {BACKUP_BUNDLE_VERSION}',
            '"bundleVersion": 99',
        ),
        encoding="utf-8",
    )
    with pytest.raises(BackupManifestError, match="newer"):
        load_manifest(result.backup_dir)


def test_v1_vault_in_backup_imports(tmp_path: Path, vault_with_wallet: Path) -> None:
    raw = cbor2.loads(vault_with_wallet.read_bytes())
    raw["vaultVersion"] = 1
    for w in raw.get("wallets", []):
        w.pop("network", None)
    vault_with_wallet.write_bytes(cbor2.dumps(raw))

    stick = tmp_path / "usb"
    stick.mkdir()
    result = export_backup(stick, vault_path=vault_with_wallet, include_settings=False)
    peek = peek_vault_file(result.backup_dir / "vault.bin")
    assert peek.vault_version == 1

    dest = tmp_path / "dest.bin"
    import_backup(result.backup_dir, vault_path=dest, pin=GOOD_PIN)
    assert Vault(dest).list_wallets()[0].network == "main"


def test_export_ignores_chmod_on_fat_filesystem(
    tmp_path: Path, vault_with_wallet: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stick = tmp_path / "usb"
    stick.mkdir()

    def _deny_chmod(path, mode, *, follow_symlinks=True) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr("piwallet.backup.bundle.os.chmod", _deny_chmod)
    result = export_backup(
        stick,
        vault_path=vault_with_wallet,
        include_settings=False,
    )
    assert (result.backup_dir / "vault.bin").is_file()


def test_import_without_settings_leaves_settings_path(
    tmp_path: Path, vault_with_wallet: Path
) -> None:
    stick = tmp_path / "usb"
    stick.mkdir()
    settings_path = tmp_path / "settings.json"
    save_settings(BonnetSettings(brightness=0.11), settings_path)
    result = export_backup(
        stick,
        vault_path=vault_with_wallet,
        settings_path=settings_path,
        include_settings=True,
    )
    out_settings = tmp_path / "out-settings.json"
    save_settings(BonnetSettings(brightness=0.99), out_settings)
    import_backup(
        result.backup_dir,
        vault_path=tmp_path / "v.bin",
        settings_path=out_settings,
        import_settings=False,
        pin=GOOD_PIN,
    )
    assert load_settings(out_settings).brightness == 0.99
