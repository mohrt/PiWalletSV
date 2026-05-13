"""Restore-wallet flow driver for the bonnet.

Asks the operator whether the phrase is 12 or 24 words, collects words
via :class:`piwallet.ui.word_entry.MnemonicEntryScreen` (including the
checksum review step), and on success encrypts the resulting xprv into
vault under the unlocked PIN.

Security note
-------------
The phrase is held in a local variable inside
:class:`piwallet.ui.word_entry.MnemonicEntryScreen` for the duration
of entry. After ``vault.add_wallet()`` is invoked the screen is
discarded and only the encrypted xprv survives. Python strings can't
be reliably zeroed; the vault layer zeroes the derived seed itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from piwallet.bonnet.choosers import WordCountChooser
from piwallet.core.vault import Vault, VaultError, WalletRecord
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import Display
from piwallet.ui.input import InputManager
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


def _ask_word_count(
    display: Display,
    input_mgr: InputManager,
    target_fps: int,
    *,
    idle_wake: IdleWakeTracker | None = None,
) -> int | None:
    """Drive the word-count chooser; return 12, 24, or None on cancel."""
    chooser = WordCountChooser()
    run_screen(display, input_mgr, chooser, target_fps=target_fps, idle_wake=idle_wake)
    return chooser.result


def run_restore_wallet(
    display: Display,
    input_mgr: InputManager,
    vault: Vault,
    pin: str,
    *,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
) -> RestoreWalletOutcome:
    """Drive the restore-wallet flow.

    Returns a :class:`RestoreWalletOutcome`.
    """
    word_count = _ask_word_count(
        display, input_mgr, target_fps, idle_wake=idle_wake
    )
    if word_count is None:
        return RestoreWalletOutcome(cancelled=True)

    entry = MnemonicEntryScreen(word_count=word_count, mode="restore")
    run_screen(display, input_mgr, entry, target_fps=target_fps, idle_wake=idle_wake)
    if entry.result is None:
        if entry.error is None:
            return RestoreWalletOutcome(cancelled=True)
        return RestoreWalletOutcome(error=entry.error)

    label = _next_default_label(vault)
    try:
        rec = vault.add_wallet(pin, entry.result, label)
    except VaultError as exc:
        log.exception("vault.add_wallet failed during restore flow")
        return RestoreWalletOutcome(error=f"vault error: {exc}")
    # Drop the screen (which holds the phrase) before returning so its
    # references are reclaimed by GC at the call site as soon as
    # possible.
    return RestoreWalletOutcome(wallet=rec)
