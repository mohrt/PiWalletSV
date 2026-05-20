"""Vault integrity diagnostic.

Checks that the on-disk vault file is:

1. **Present** — the path exists.
2. **Parseable** — the CBOR top-level is a well-formed map.
3. **Supported version** — ``vaultVersion`` is in
   :data:`~piwallet.core.vault.SUPPORTED_VAULT_VERSIONS`.
4. **Wallet count sane** — the ``wallets`` array is present and its
   length matches what :meth:`~piwallet.core.vault.Vault.list_wallets`
   returns (cross-checks the high-level accessor against raw CBOR).

These checks are **PIN-free**: they operate only on the encrypted-but-
parseable outer envelope (labels, fingerprints, derivation paths,
creation timestamps) and never attempt to decrypt key material.  The
goal is to detect on-disk corruption or format drift *before* the
operator is prompted for their PIN.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CheckOk = Literal[True, False, None]


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single diagnostic sub-check."""

    name: str
    ok: CheckOk
    detail: str


def check_vault(vault_path: Path | None = None) -> list[CheckResult]:
    """Run all vault integrity checks against ``vault_path``.

    If ``vault_path`` is ``None`` the default location
    (``~/.piwallet/vault.bin``) is used.
    """
    from piwallet.core.paths import default_vault_path
    from piwallet.core.vault import (
        SUPPORTED_VAULT_VERSIONS,
        Vault,
        VaultError,
    )

    path = vault_path or default_vault_path()
    results: list[CheckResult] = []

    # ---- 1. File present ------------------------------------------------
    if not path.exists():
        results.append(
            CheckResult(
                name="vault_present",
                ok=False,
                detail=f"no vault file at {path}",
            )
        )
        return results
    results.append(
        CheckResult(name="vault_present", ok=True, detail=str(path))
    )

    # ---- 2. CBOR parseable + version ------------------------------------
    try:
        import cbor2
        raw = path.read_bytes()
        data = cbor2.loads(raw)
    except Exception as exc:
        results.append(
            CheckResult(
                name="vault_parseable",
                ok=False,
                detail=f"CBOR decode error: {exc}",
            )
        )
        return results

    if not isinstance(data, dict):
        results.append(
            CheckResult(
                name="vault_parseable",
                ok=False,
                detail="top-level value is not a map",
            )
        )
        return results
    results.append(CheckResult(name="vault_parseable", ok=True, detail="CBOR map OK"))

    version = data.get("vaultVersion")
    if version not in SUPPORTED_VAULT_VERSIONS:
        results.append(
            CheckResult(
                name="vault_version",
                ok=False,
                detail=(
                    f"unsupported vaultVersion={version!r}; "
                    f"supported: {sorted(SUPPORTED_VAULT_VERSIONS)}"
                ),
            )
        )
        return results
    results.append(
        CheckResult(name="vault_version", ok=True, detail=f"vaultVersion={version}")
    )

    # ---- 3. Wallet count cross-check ------------------------------------
    raw_count = len(data.get("wallets", []))
    try:
        vault = Vault(path)
        api_count = len(vault.list_wallets())
    except VaultError as exc:
        results.append(
            CheckResult(
                name="vault_wallet_count",
                ok=False,
                detail=f"Vault.list_wallets() raised: {exc}",
            )
        )
        return results

    if raw_count != api_count:
        results.append(
            CheckResult(
                name="vault_wallet_count",
                ok=False,
                detail=(
                    f"CBOR wallets array has {raw_count} entries "
                    f"but list_wallets() returned {api_count}"
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                name="vault_wallet_count",
                ok=True,
                detail=f"{api_count} wallet(s) consistent",
            )
        )

    return results


def run_all(vault_path: Path | None = None) -> list[CheckResult]:
    """Run all vault checks and return results in a stable order."""
    return check_vault(vault_path)
