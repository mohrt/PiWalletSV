"""Restore-wallet flow driver for the bonnet.

Asks the operator whether the phrase is 12 or 24 words, then mirrors
the create-wallet flow for network, HD path, and label selection before
collecting the mnemonic words via
:class:`piwallet.ui.word_entry.MnemonicEntryScreen`.

Screen order
------------
1. Word count chooser (12 / 24)
2. Network chooser (mainnet / testnet)
3. HD path chooser (BSV default or advanced)
4. Mnemonic word entry (+ checksum review)
5. Label entry (operator may skip to accept the generated default)

Security note
-------------
The phrase is held inside :class:`piwallet.ui.word_entry.MnemonicEntryScreen`
for the duration of entry. After ``vault.add_wallet()`` is called the
screen is discarded and only the encrypted xprv survives. Python strings
can't be reliably zeroed; the vault layer zeroes the derived seed itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from piwallet.bonnet.choosers import WordCountChooser
from piwallet.bonnet.hd_path_chooser import run_hd_path_chooser
from piwallet.bonnet.network_chooser import run_network_chooser
from piwallet.core import derivation as deriv
from piwallet.core.vault import Vault, VaultError, WalletRecord
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import Display
from piwallet.ui.input import InputManager
from piwallet.ui.label_entry import WalletLabelEntryScreen
from piwallet.ui.word_entry import MnemonicEntryScreen

log = logging.getLogger(__name__)


@dataclass
class RestoreWalletOutcome:
    """Result of a single restore-wallet attempt."""

    wallet: WalletRecord | None = None
    cancelled: bool = False
    error: str | None = None


def _next_default_label(vault: Vault) -> str:
    existing = {w.label for w in vault.list_wallets()}
    n = 1
    while f"restored-{n}" in existing:
        n += 1
    return f"restored-{n}"


def run_restore_wallet(
    display: Display,
    input_mgr: InputManager,
    vault: Vault,
    pin: str,
    *,
    target_fps: int = 30,
    word_count: int | None = None,
    hd_path: tuple[int, int] | None = None,
    network: deriv.Network | None = None,
    idle_wake: IdleWakeTracker | None = None,
) -> RestoreWalletOutcome:
    """Drive the restore-wallet flow.

    ``word_count``, ``network``, and ``hd_path`` are optional
    pre-selected choices (caller already prompted for them); if any is
    ``None`` the matching chooser screen runs inline.

    Returns a :class:`RestoreWalletOutcome`.
    """
    wc = word_count
    if wc is None:
        chooser = WordCountChooser()
        run_screen(display, input_mgr, chooser, target_fps=target_fps, idle_wake=idle_wake)
        wc = chooser.result
        if wc is None:
            return RestoreWalletOutcome(cancelled=True)

    chosen_network: deriv.Network | None = network
    if chosen_network is None:
        chosen_network = run_network_chooser(
            display,
            input_mgr,
            target_fps=target_fps,
            idle_wake=idle_wake,
        )
        if chosen_network is None:
            return RestoreWalletOutcome(cancelled=True)

    chosen_path = hd_path
    if chosen_path is None:
        chosen_path = run_hd_path_chooser(
            display,
            input_mgr,
            target_fps=target_fps,
            idle_wake=idle_wake,
        )
        if chosen_path is None:
            return RestoreWalletOutcome(cancelled=True)

    entry = MnemonicEntryScreen(word_count=wc, mode="restore")
    run_screen(display, input_mgr, entry, target_fps=target_fps, idle_wake=idle_wake)
    if entry.result is None:
        if entry.error is None:
            return RestoreWalletOutcome(cancelled=True)
        return RestoreWalletOutcome(error=entry.error)

    suggested = _next_default_label(vault)
    name_scr = WalletLabelEntryScreen(
        suggested_default=suggested,
        ignore_hold_b_long=True,
    )
    run_screen(display, input_mgr, name_scr, target_fps=target_fps, idle_wake=idle_wake)
    if name_scr.result is None:
        label = suggested
    else:
        label = name_scr.result.strip() or suggested

    coin_type, account_index = chosen_path
    try:
        rec = vault.add_wallet(
            pin,
            entry.result,
            label,
            coin_type=coin_type,
            account_index=account_index,
            network=chosen_network,
        )
    except VaultError as exc:
        log.exception("vault.add_wallet failed during restore flow")
        return RestoreWalletOutcome(error=f"vault error: {exc}")
    # Drop the entry screen (which holds the phrase) before returning so
    # its references are reclaimed by GC at the call site as soon as possible.
    return RestoreWalletOutcome(wallet=rec)
