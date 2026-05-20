"""Create-wallet flow driver for the bonnet.

Generates a BIP39 phrase via OS RNG, a camera JPEG mix, or many dice readings;
shows it; confirms via shuffled pick lists; asks for a wallet name (or accepts
defaults); encrypts under the PIN.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from piwallet.bonnet.choosers import EntropySourceChooser, WordCountChooser
from piwallet.bonnet.entropy_screens import CameraEntropyScreen, DiceEntropyScreen
from piwallet.bonnet.hd_path_chooser import run_hd_path_chooser
from piwallet.bonnet.network_chooser import run_network_chooser
from piwallet.core import derivation as deriv
from piwallet.core import mnemonic as mnem
from piwallet.core.mnemonic import MnemonicError
from piwallet.core.settings import BonnetSettings
from piwallet.core.vault import Vault, VaultError, WalletRecord
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import Display
from piwallet.ui.input import InputManager
from piwallet.ui.label_entry import WalletLabelEntryScreen
from piwallet.ui.show_phrase import ShowPhraseScreen
from piwallet.ui.word_pick_confirm import MnemonicConfirmPickScreen

log = logging.getLogger(__name__)


@dataclass
class CreateWalletOutcome:
    wallet: WalletRecord | None = None
    cancelled: bool = False
    error: str | None = None


def _next_default_label(vault: Vault) -> str:
    existing = {w.label for w in vault.list_wallets()}
    n = 1
    while f"wallet-{n}" in existing:
        n += 1
    return f"wallet-{n}"


def run_create_wallet(
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
    settings: BonnetSettings | None = None,
) -> CreateWalletOutcome:
    """Walk the operator through wallet creation.

    ``word_count``, ``network``, and ``hd_path`` are optional
    pre-selected choices (caller already prompted for them); if any
    is ``None`` the matching chooser screen runs inline.

    ``network`` selects the wallet's address-encoding network
    (``"main"`` or ``"test"``); the network chooser screen runs
    after the word-count chooser and before the HD path chooser.
    Defaults are mainnet + the BSV BIP44 path
    ``m/44'/236'/0'`` if both choosers accept their preset rows.
    """
    wc = word_count
    if wc is None:
        wcs = WordCountChooser()
        run_screen(display, input_mgr, wcs, target_fps=target_fps, idle_wake=idle_wake)
        wc = wcs.result
        if wc is None:
            return CreateWalletOutcome(cancelled=True)

    if wc not in (12, 24):
        raise ValueError(f"word_count must be 12 or 24 (or None); got {wc}")

    chosen_network: deriv.Network | None = network
    if chosen_network is None:
        chosen_network = run_network_chooser(
            display,
            input_mgr,
            target_fps=target_fps,
            idle_wake=idle_wake,
        )
        if chosen_network is None:
            return CreateWalletOutcome(cancelled=True)

    chosen_path = hd_path
    if chosen_path is None:
        chosen_path = run_hd_path_chooser(
            display,
            input_mgr,
            target_fps=target_fps,
            idle_wake=idle_wake,
        )
        if chosen_path is None:
            return CreateWalletOutcome(cancelled=True)

    ents = EntropySourceChooser()
    run_screen(display, input_mgr, ents, target_fps=target_fps, idle_wake=idle_wake)
    src = ents.result
    if src is None:
        return CreateWalletOutcome(cancelled=True)

    try:
        if src == "csr":
            phrase = mnem.generate(wc)
        elif src == "camera":
            af = settings is None or settings.camera_type in ("imx708", "auto")
            caps = CameraEntropyScreen(autofocus_continuous=af)
            run_screen(display, input_mgr, caps, target_fps=target_fps, idle_wake=idle_wake)
            if caps.result is None:
                return CreateWalletOutcome(cancelled=True)
            phrase = mnem.mnemonic_from_camera_jpeg(bytes(caps.result), wc)
        elif src == "dice":
            dex = DiceEntropyScreen(word_count=wc)
            run_screen(display, input_mgr, dex, target_fps=target_fps, idle_wake=idle_wake)
            if dex.result is None:
                return CreateWalletOutcome(cancelled=True)
            phrase = mnem.mnemonic_from_dice_rolls(dex.result, wc)
        else:
            return CreateWalletOutcome(error=f"unknown entropy source {src!r}")

        words_list = phrase.split()

        show = ShowPhraseScreen(words=words_list, per_page=4)
        confirmed = run_screen(display, input_mgr, show, target_fps=target_fps, idle_wake=idle_wake)
        if confirmed is not True:
            return CreateWalletOutcome(cancelled=True)

        picker = MnemonicConfirmPickScreen(list(words_list))
        run_screen(display, input_mgr, picker, target_fps=target_fps, idle_wake=idle_wake)
        if picker.result is None:
            return CreateWalletOutcome(cancelled=True)

        suggested = _next_default_label(vault)
        name_scr = WalletLabelEntryScreen(suggested_default=suggested)
        run_screen(display, input_mgr, name_scr, target_fps=target_fps, idle_wake=idle_wake)
        if name_scr.result is None:
            label = _next_default_label(vault)
        else:
            label = name_scr.result.strip() or _next_default_label(vault)

        coin_type, account_index = chosen_path
        rec = vault.add_wallet(
            pin,
            picker.result,
            label,
            coin_type=coin_type,
            account_index=account_index,
            network=chosen_network,
        )
        return CreateWalletOutcome(wallet=rec)
    except MnemonicError as exc:
        return CreateWalletOutcome(error=str(exc))
    except VaultError as exc:
        log.exception("vault.add_wallet failed during create flow")
        return CreateWalletOutcome(error=f"vault error: {exc}")
