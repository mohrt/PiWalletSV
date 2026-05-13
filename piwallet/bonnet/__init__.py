"""Bonnet application flows.

This package stitches the bonnet UI primitives (``piwallet.ui``) and
the first-boot disclaimer (``piwallet.firstboot``) together with the
encrypted vault into the screens a user sees once the device is
powered on:

* :class:`UnlockScreen`        - PIN entry against the vault.
* :class:`WalletListScreen`    - menu of unlocked wallets.
* :class:`WalletDetailScreen`  - receive address + QR for one wallet.
* :func:`run_bonnet`           - the top-level loop that runs them all.

The CLI entry point is ``piwallet bonnet`` in :mod:`piwallet.cli`.
"""

from piwallet.bonnet.unlock import UnlockOutcome, UnlockScreen
from piwallet.bonnet.wallet_detail import WalletDetailScreen
from piwallet.bonnet.wallet_list import WalletListAction, WalletListScreen

__all__ = [
    "UnlockOutcome",
    "UnlockScreen",
    "WalletDetailScreen",
    "WalletListAction",
    "WalletListScreen",
]
