"""Export/import backup directories on a USB stick (or test fixture path)."""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from piwallet.backup.constants import (
    BACKUPS_SUBDIR,
    MANIFEST_FILENAME,
    SETTINGS_FILENAME,
    STATE_FILENAME,
    STICK_ROOT_DIRNAME,
    VAULT_FILENAME,
)
from piwallet.backup.manifest import (
    BackupManifest,
    BackupManifestError,
    build_manifest,
    load_manifest,
    utc_export_dirname,
)
from piwallet.backup.vault_peek import peek_vault_file
from piwallet.core.paths import default_settings_path, default_state_path, default_vault_path
from piwallet.core.state import STATE_FILE_VERSION
from piwallet.core.vault import Vault, VaultError


class BackupBundleError(Exception):
    """Export/import failure."""


def _chmod_if_supported(path: Path, mode: int) -> None:
    """Set mode bits when the backing filesystem supports them (not vfat/exfat)."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _copy_file(src: Path, dest: Path) -> None:
    """Copy file contents; skip mode/utime on filesystems that reject them."""
    try:
        shutil.copy2(src, dest)
    except OSError:
        shutil.copyfile(src, dest)
    _chmod_if_supported(dest, 0o600 if dest.name in {VAULT_FILENAME, STATE_FILENAME} else 0o644)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ExportResult:
    backup_dir: Path
    manifest: BackupManifest


@dataclass(frozen=True)
class ImportResult:
    manifest: BackupManifest
    vault_path: Path
    settings_imported: bool
    state_imported: bool = False


def stick_backups_root(stick_root: Path) -> Path:
    """``PiWalletSV/backups`` on the mounted stick volume."""
    return stick_root / STICK_ROOT_DIRNAME / BACKUPS_SUBDIR


def export_backup(
    stick_root: Path,
    *,
    vault_path: Path | None = None,
    settings_path: Path | None = None,
    state_path: Path | None = None,
    include_settings: bool = True,
) -> ExportResult:
    """Write a timestamped backup under ``stick_root/PiWalletSV/backups/``."""
    vault_path = vault_path or default_vault_path()
    settings_path = settings_path or default_settings_path()
    state_path = state_path or vault_path.with_name(STATE_FILENAME)
    if not vault_path.is_file():
        raise BackupBundleError(f"no vault at {vault_path}")

    peek = peek_vault_file(vault_path)
    summaries = peek.wallet_summary
    has_settings = include_settings and settings_path.is_file()
    has_state = state_path.is_file()

    backup_dir = stick_backups_root(stick_root) / utc_export_dirname()
    backup_dir.mkdir(parents=True, exist_ok=False)

    dest_vault = backup_dir / VAULT_FILENAME
    _copy_file(vault_path, dest_vault)

    if has_state:
        _copy_file(state_path, backup_dir / STATE_FILENAME)

    if has_settings:
        _copy_file(settings_path, backup_dir / SETTINGS_FILENAME)

    checksums = {VAULT_FILENAME: _sha256_file(dest_vault)}
    if has_state:
        checksums[STATE_FILENAME] = _sha256_file(backup_dir / STATE_FILENAME)
    if has_settings:
        checksums[SETTINGS_FILENAME] = _sha256_file(backup_dir / SETTINGS_FILENAME)
    manifest = build_manifest(
        vault_version=peek.vault_version,
        wallet_summary=summaries,
        include_settings=has_settings,
        include_state=has_state,
        state_version=STATE_FILE_VERSION if has_state else None,
        checksums=checksums,
    )
    # Write the manifest last so a power loss cannot leave a partial directory
    # that the restore picker considers complete.
    manifest.write(backup_dir)

    return ExportResult(backup_dir=backup_dir, manifest=manifest)


def find_backups_on_stick(stick_root: Path) -> list[Path]:
    """Return backup directories newest-first (valid manifest only)."""
    root = stick_backups_root(stick_root)
    if not root.is_dir():
        return []
    candidates = sorted(
        (p for p in root.iterdir() if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    valid: list[Path] = []
    for directory in candidates:
        if (directory / MANIFEST_FILENAME).is_file():
            valid.append(directory)
    return valid


def list_backup_summaries(stick_root: Path) -> list[BackupManifest]:
    out: list[BackupManifest] = []
    for directory in find_backups_on_stick(stick_root):
        try:
            manifest = load_manifest(directory)
        except BackupManifestError:
            continue
        out.append(
            BackupManifest(
                bundle_version=manifest.bundle_version,
                exported_at=manifest.exported_at,
                piwalletsv_version=manifest.piwalletsv_version,
                vault_version=manifest.vault_version,
                wallet_summary=manifest.wallet_summary,
                has_settings=manifest.has_settings,
                has_state=manifest.has_state,
                state_version=manifest.state_version,
                checksums=manifest.checksums,
                backup_dir_name=directory.name,
            )
        )
    return out


def _atomic_copy(src: Path, dest: Path, *, mode: int = 0o600) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    _copy_file(src, tmp)
    _chmod_if_supported(tmp, mode)
    with tmp.open("rb") as f:
        os.fsync(f.fileno())
    os.replace(tmp, dest)


def import_backup(
    backup_dir: Path,
    *,
    vault_path: Path | None = None,
    settings_path: Path | None = None,
    state_path: Path | None = None,
    import_settings: bool = False,
    pin: str | None = None,
) -> ImportResult:
    """Replace on-device vault (and optionally settings) from a backup directory."""
    vault_path = vault_path or default_vault_path()
    settings_path = settings_path or default_settings_path()
    state_path = state_path or vault_path.with_name(STATE_FILENAME)

    manifest = load_manifest(backup_dir)
    src_vault = backup_dir / VAULT_FILENAME
    if not src_vault.is_file():
        raise BackupBundleError(f"missing {VAULT_FILENAME} in backup")

    peek_vault_file(src_vault)
    _verify_manifest_checksums(backup_dir, manifest)

    staging = vault_path.with_suffix(vault_path.suffix + ".import-staging")
    try:
        _atomic_copy(src_vault, staging)
        if pin is not None:
            vault = Vault(staging)
            wallets = vault.list_wallets()
            if not wallets:
                raise BackupBundleError("backup vault contains no wallets")
            try:
                vault.derive_signing_key(pin, wallets[0].id, 0, 0)
            except VaultError as exc:
                raise BackupBundleError(f"backup PIN check failed: {exc}") from exc
        _atomic_copy(staging, vault_path)
    finally:
        if staging.exists():
            staging.unlink()

    settings_imported = False
    src_settings = backup_dir / SETTINGS_FILENAME
    if import_settings and manifest.has_settings and src_settings.is_file():
        _atomic_copy(src_settings, settings_path, mode=0o644)
        settings_imported = True

    state_imported = False
    src_state = backup_dir / STATE_FILENAME
    if manifest.has_state:
        if not src_state.is_file():
            raise BackupBundleError(f"missing {STATE_FILENAME} in backup")
        _atomic_copy(src_state, state_path)
        state_imported = True

    return ImportResult(
        manifest=manifest,
        vault_path=vault_path,
        settings_imported=settings_imported,
        state_imported=state_imported,
    )


def _verify_manifest_checksums(backup_dir: Path, manifest: BackupManifest) -> None:
    """Verify bundle integrity and completeness before replacing device files."""
    if not manifest.checksums:
        # v1 compatibility: those bundles predate checksums and state.bin.
        return
    for name, expected in manifest.checksums.items():
        path = backup_dir / name
        if not path.is_file():
            raise BackupBundleError(f"missing checksummed file {name}")
        actual = _sha256_file(path)
        if actual != expected:
            raise BackupBundleError(f"checksum mismatch for {name}")


def import_state_backup(
    backup_dir: Path,
    *,
    state_path: Path | None = None,
) -> Path:
    """Restore only encrypted state.bin after mnemonic-based key recovery."""
    state_path = state_path or default_state_path()
    manifest = load_manifest(backup_dir)
    _verify_manifest_checksums(backup_dir, manifest)
    if not manifest.has_state:
        raise BackupBundleError("backup predates wallet-state snapshots")
    src_state = backup_dir / STATE_FILENAME
    if not src_state.is_file():
        raise BackupBundleError(f"missing {STATE_FILENAME} in backup")
    _atomic_copy(src_state, state_path)
    return state_path
