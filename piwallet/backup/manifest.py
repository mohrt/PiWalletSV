"""Backup manifest schema and version policy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from piwallet import __version__
from piwallet.backup.constants import (
    MANIFEST_FILENAME,
    MANIFEST_FORMAT,
    SETTINGS_FILENAME,
    VAULT_FILENAME,
)

#: Bump when export JSON shape changes in a non-additive way.
BACKUP_BUNDLE_VERSION: int = 1


class BackupManifestError(ValueError):
    """Invalid or unsupported backup manifest."""


@dataclass(frozen=True)
class WalletSummary:
    label: str
    fingerprint: str  # 8 hex chars for display
    network: str = "main"


@dataclass(frozen=True)
class BackupManifest:
    bundle_version: int
    exported_at: str
    piwalletsv_version: str
    vault_version: int
    wallet_summary: tuple[WalletSummary, ...]
    has_settings: bool
    backup_dir_name: str = ""

    @property
    def format(self) -> str:
        return MANIFEST_FORMAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "bundleVersion": self.bundle_version,
            "exportedAt": self.exported_at,
            "exporter": {
                "piwalletsvVersion": self.piwalletsv_version,
            },
            "vaultVersion": self.vault_version,
            "walletSummary": [
                {
                    "label": w.label,
                    "fingerprint": w.fingerprint,
                    "network": w.network,
                }
                for w in self.wallet_summary
            ],
            "files": {
                "vault": VAULT_FILENAME,
                **({"settings": SETTINGS_FILENAME} if self.has_settings else {}),
            },
        }

    def write(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / MANIFEST_FILENAME
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _parse_wallet_summary(raw: Any) -> WalletSummary:
    if not isinstance(raw, dict):
        raise BackupManifestError("walletSummary entry must be an object")
    label = str(raw.get("label", ""))
    fp = str(raw.get("fingerprint", ""))
    network = str(raw.get("network", "main"))
    if not label:
        raise BackupManifestError("walletSummary entry missing label")
    return WalletSummary(label=label, fingerprint=fp, network=network)


def load_manifest(directory: Path) -> BackupManifest:
    """Read and validate ``manifest.json`` in ``directory``."""
    path = directory / MANIFEST_FILENAME
    if not path.is_file():
        raise BackupManifestError(f"missing {MANIFEST_FILENAME} in {directory}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupManifestError(f"unreadable manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise BackupManifestError("manifest must be a JSON object")
    if data.get("format") != MANIFEST_FORMAT:
        raise BackupManifestError(
            f"unsupported format: {data.get('format')!r}; expected {MANIFEST_FORMAT!r}"
        )
    bundle_version = int(data["bundleVersion"])
    validate_bundle_version(bundle_version)
    vault_version = int(data.get("vaultVersion", 0))
    exporter = data.get("exporter") or {}
    piwalletsv_version = str(exporter.get("piwalletsvVersion", "?"))
    exported_at = str(data.get("exportedAt", ""))
    summaries = tuple(
        _parse_wallet_summary(w) for w in (data.get("walletSummary") or [])
    )
    files = data.get("files") or {}
    if files.get("vault") != VAULT_FILENAME:
        raise BackupManifestError("manifest files.vault must name vault.bin")
    has_settings = files.get("settings") == SETTINGS_FILENAME
    return BackupManifest(
        bundle_version=bundle_version,
        exported_at=exported_at,
        piwalletsv_version=piwalletsv_version,
        vault_version=vault_version,
        wallet_summary=summaries,
        has_settings=has_settings,
        backup_dir_name=directory.name,
    )


def validate_bundle_version(version: int) -> None:
    if version < 1:
        raise BackupManifestError(f"invalid bundleVersion: {version}")
    if version > BACKUP_BUNDLE_VERSION:
        raise BackupManifestError(
            f"backup bundle version {version} is newer than this firmware "
            f"(supports up to {BACKUP_BUNDLE_VERSION}) — update the Pi image first"
        )


def utc_export_dirname() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%SZ")


def build_manifest(
    *,
    vault_version: int,
    wallet_summary: tuple[WalletSummary, ...],
    include_settings: bool,
) -> BackupManifest:
    return BackupManifest(
        bundle_version=BACKUP_BUNDLE_VERSION,
        exported_at=datetime.now(UTC).isoformat(timespec="seconds"),
        piwalletsv_version=__version__,
        vault_version=vault_version,
        wallet_summary=wallet_summary,
        has_settings=include_settings,
    )
