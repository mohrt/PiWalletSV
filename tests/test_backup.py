"""Tests for USB/directory vault backup export and import."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import cbor2
import pytest

from piwallet.backup.bundle import (
    BackupBundleError,
    export_backup,
    import_backup,
    import_state_backup,
    list_backup_summaries,
)
from piwallet.backup.manifest import (
    BACKUP_BUNDLE_VERSION,
    BackupManifestError,
    load_manifest,
)
from piwallet.backup.vault_peek import peek_vault_file
from piwallet.core.settings import BonnetSettings, load_settings, save_settings
from piwallet.core.state import WalletStateStore
from piwallet.core.vault import Vault

CANONICAL_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
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
    assert result.manifest.has_state
    assert (result.backup_dir / "vault.bin").is_file()
    assert (result.backup_dir / "state.bin").is_file()
    assert (result.backup_dir / "settings.json").is_file()
    assert (result.backup_dir / "manifest.json").is_file()
    assert not (result.backup_dir / "terms.json").exists()

    dest_vault = tmp_path / "restored.bin"
    dest_settings = tmp_path / "restored-settings.json"
    dest_state = tmp_path / "restored-state.bin"
    import_backup(
        result.backup_dir,
        vault_path=dest_vault,
        settings_path=dest_settings,
        state_path=dest_state,
        import_settings=True,
        pin=GOOD_PIN,
    )
    restored = Vault(dest_vault)
    wallets = restored.list_wallets()
    assert len(wallets) == 1
    assert wallets[0].label == "daily"
    assert stat.S_IMODE(dest_vault.stat().st_mode) == 0o600
    assert stat.S_IMODE(dest_state.stat().st_mode) == 0o600
    assert stat.S_IMODE(dest_settings.stat().st_mode) == 0o644


def test_v2_backup_checksums_reject_state_corruption_before_restore(
    tmp_path: Path, vault_with_wallet: Path
) -> None:
    stick = tmp_path / "usb"
    stick.mkdir()
    result = export_backup(stick, vault_path=vault_with_wallet, include_settings=False)
    assert set(result.manifest.checksums) == {"vault.bin", "state.bin"}

    state_copy = result.backup_dir / "state.bin"
    state_copy.write_bytes(state_copy.read_bytes() + b"corrupt")
    destination = tmp_path / "destination.bin"
    destination.write_bytes(b"unchanged")
    with pytest.raises(BackupBundleError, match=r"checksum mismatch for state\.bin"):
        import_backup(result.backup_dir, vault_path=destination, pin=GOOD_PIN)
    assert destination.read_bytes() == b"unchanged"


def test_state_only_restore_after_mnemonic_recovery(tmp_path: Path) -> None:
    original_dir = tmp_path / "original"
    original_dir.mkdir()
    original = Vault(original_dir / "vault.bin")
    original.create(GOOD_PIN)
    wallet = original.add_wallet(GOOD_PIN, CANONICAL_MNEMONIC, "original")
    state_key = original.derive_state_key(GOOD_PIN, wallet.id)
    store = WalletStateStore(original.state_path)
    state = store.load(wallet, state_key)
    state.next_receive_index = 17
    store.save(wallet, state_key, state)

    stick = tmp_path / "usb"
    stick.mkdir()
    exported = export_backup(stick, vault_path=original.path, include_settings=False)

    recovered_dir = tmp_path / "recovered"
    recovered_dir.mkdir()
    recovered = Vault(recovered_dir / "vault.bin")
    recovered.create("654321")
    recovered_wallet = recovered.add_wallet("654321", CANONICAL_MNEMONIC, "recovered")
    import_state_backup(exported.backup_dir, state_path=recovered.state_path)
    recovered_key = recovered.derive_state_key("654321", recovered_wallet.id)
    recovered_state = WalletStateStore(recovered.state_path).load(recovered_wallet, recovered_key)
    assert recovered_state.next_receive_index == 17


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


def test_v2_manifest_rejects_undeclared_checksum_entry(
    tmp_path: Path, vault_with_wallet: Path
) -> None:
    stick = tmp_path / "usb"
    stick.mkdir()
    result = export_backup(stick, vault_path=vault_with_wallet, include_settings=False)
    manifest_path = result.backup_dir / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["checksums"]["../outside"] = "00" * 32
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(BackupManifestError, match="exactly match"):
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
