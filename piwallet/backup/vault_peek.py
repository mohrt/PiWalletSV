"""PIN-less read of public vault metadata from ``vault.bin``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cbor2

from piwallet.backup.manifest import WalletSummary
from piwallet.core import derivation as deriv
from piwallet.core.vault import SUPPORTED_VAULT_VERSIONS, VaultError


@dataclass(frozen=True)
class VaultPeek:
    vault_version: int
    wallet_summary: tuple[WalletSummary, ...]


def peek_vault_file(path: Path) -> VaultPeek:
    """Return public metadata without decrypting wallet payloads."""
    try:
        data = cbor2.loads(path.read_bytes())
    except (OSError, cbor2.CBORDecodeError, EOFError) as exc:
        raise VaultError(f"cannot read vault: {exc}") from exc
    if not isinstance(data, dict):
        raise VaultError("corrupted vault: top-level not a map")
    on_disk_version = data.get("vaultVersion")
    if on_disk_version not in SUPPORTED_VAULT_VERSIONS:
        raise VaultError(
            f"unsupported vault version: {on_disk_version!r}; "
            f"this build supports {sorted(SUPPORTED_VAULT_VERSIONS)!r}"
        )
    wallets = list(data.get("wallets", []))
    summaries: list[WalletSummary] = []
    for w in wallets:
        if not isinstance(w, dict):
            continue
        fp = w.get("fingerprint")
        if isinstance(fp, (bytes, bytearray)):
            fp_hex = bytes(fp).hex()[:8]
        else:
            fp_hex = "????????"
        network = str(w.get("network", deriv.NETWORK_MAIN))
        summaries.append(
            WalletSummary(
                label=str(w.get("label", "?")),
                fingerprint=fp_hex,
                network=network,
            )
        )
    return VaultPeek(
        vault_version=int(on_disk_version),
        wallet_summary=tuple(summaries),
    )
