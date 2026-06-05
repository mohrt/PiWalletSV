"""Return PiWallet to out-of-box software state.

Erases the encrypted vault (secure overwrite), global bonnet settings,
and disclaimer acceptance so the next boot walks through first-setup
again. Intended for handing the device to a new operator.
"""

from __future__ import annotations

from pathlib import Path

from piwallet.core.paths import (
    default_settings_path,
    default_terms_path,
    default_vault_path,
)
from piwallet.core.vault import Vault


def _unlink_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def factory_reset(
    *,
    vault_path: Path | None = None,
    settings_path: Path | None = None,
    terms_path: Path | None = None,
) -> None:
    """Wipe vault, settings, and terms state at the given paths.

    Missing files are ignored. The vault file is overwritten with random
    bytes before unlink (same contract as :meth:`Vault.wipe`).
    """
    vault_path = vault_path or default_vault_path()
    settings_path = settings_path or default_settings_path()
    terms_path = terms_path or default_terms_path()

    vault = Vault(vault_path)
    if vault.exists:
        vault.wipe()

    _unlink_if_exists(settings_path)
    _unlink_if_exists(terms_path)


__all__ = ["factory_reset"]
