"""Top-level bonnet boot loop.

This is the entry point the systemd unit / SD-card image runs on
startup. It performs, in order:

1. **Disclaimer.** If the operator hasn't accepted the current
   disclaimer version, walk them through the three-page
   :class:`piwallet.firstboot.DisclaimerScreen`. Persist acceptance
   on success; exit on cancel.

2. **Unlock.** If a vault exists, present the
   :class:`piwallet.bonnet.UnlockScreen` and let the user type their
   PIN. The screen verifies against ``Vault.derive_signing_key``
   via a dummy derivation (or, if there are no wallets yet, a
   constant-time "is this PIN well-formed?" check until at least one
   wallet is added). Wrong PINs surface the attempts-remaining
   counter; the 10th wrong PIN wipes the vault.

3. **Wallet list -> manage menu.** After unlock, the operator browses
   the list of wallets and drills into one. Selecting a wallet opens
   its **manage menu** (show deposit address, show xpub QR, rename,
   erase). Long **B** backs out of the bonnet loop from the wallet
   list only.

This loop is *meant* to be the main process on the Pi. It does not
fork, daemonize, or open any network sockets.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from piwallet.bonnet.companion_pairing import (
    OfferCompanionPairingScreen,
    pairing_pw1_lines,
)
from piwallet.bonnet.create_wallet import CreateWalletOutcome, run_create_wallet
from piwallet.bonnet.restore_wallet import RestoreWalletOutcome, run_restore_wallet
from piwallet.bonnet.unlock import UnlockOutcome, UnlockScreen, VerifyFn
from piwallet.bonnet.wallet_list import WalletListAction, WalletListScreen
from piwallet.bonnet.wallet_manage import run_wallet_manage
from piwallet.core import derivation as deriv
from piwallet.core.vault import (
    Vault,
    VaultError,
    VaultWipedError,
    WalletNotFoundError,
    WalletRecord,
    WrongPinError,
)
from piwallet.firstboot.disclaimer import DisclaimerScreen
from piwallet.firstboot.terms import mark_accepted, requires_acceptance
from piwallet.ui.app import IdleWakeTracker, make_input_manager, run_screen
from piwallet.ui.display import (
    COLOR_DANGER,
    COLOR_DIM,
    COLOR_OK,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    Display,
    FrameBuffer,
    open_display,
)
from piwallet.ui.input import InputManager, open_input
from piwallet.ui.pairing_multipart_qr_screen import PairingMultipartQrScreen
from piwallet.ui.widgets import Modal, draw_text

log = logging.getLogger(__name__)


def _make_verify_fn(vault: Vault) -> VerifyFn:
    """Build a PIN-verify callback closed over ``vault``.

    The strategy is to attempt the cheapest PIN-gated operation we
    have, which is wallet xpub recovery. For an *empty* vault we can't
    actually verify the PIN (nothing is encrypted under it yet); in
    that case any well-formed PIN is accepted - this matches the CLI's
    behaviour and is safe because an empty vault has nothing to lose.
    """
    def verify(pin: str) -> tuple[str, int | None]:
        wallets = vault.list_wallets()
        if not wallets:
            # Empty vault: accept any well-formed PIN.
            return ("ok", None)
        first_id = wallets[0].id
        try:
            vault.get_account_xpub(pin, first_id)
        except VaultWipedError:
            return ("wiped", None)
        except WrongPinError as exc:
            return ("wrong", exc.attempts_remaining)
        except (VaultError, WalletNotFoundError) as exc:
            # Surfacing as wrong-pin keeps the UX consistent; the vault
            # state machine has already accounted for the failure.
            log.warning("verify_fn unexpected vault error: %s", exc)
            return ("wrong", vault.attempts_remaining)
        return ("ok", None)
    return verify


def _make_derive_address_fn(
    vault: Vault,
    wallet_id: str,
    pin: str,
) -> Callable[[int, int], str]:
    """Build a ``(change, index) -> address`` closure for a wallet."""
    xpub_str = vault.get_account_xpub(pin, wallet_id)
    xpub = deriv.parse_xpub(xpub_str)

    def derive(change: int, index: int) -> str:
        return deriv.derive_address(xpub, change, index)
    return derive


def _show_message(
    display: Display,
    title: str,
    body: str,
    *,
    accent: tuple[int, int, int] = COLOR_DANGER,
) -> None:
    """Briefly render a static modal on the screen."""
    fb = FrameBuffer(display.width, display.height)
    Modal(title=title, body=body, footer="", accent=accent).draw(fb)
    display.flip(fb)


def _surface_wallet_outcome(
    display: Display,
    outcome: CreateWalletOutcome | RestoreWalletOutcome,
    *,
    hold_seconds: float = 2.0,
) -> None:
    """Briefly show the result of a create / restore attempt.

    Success: green "Saved <label>" banner. Error: red modal with the
    truncated error. Cancel: nothing — the operator already knows.
    """
    if outcome.wallet is not None:
        _show_message(
            display,
            title="Wallet saved",
            body=f"{outcome.wallet.label}\n{outcome.wallet.fingerprint.hex()[:8]}",
            accent=COLOR_OK,
        )
        time.sleep(hold_seconds)
        return
    if outcome.error is not None:
        _show_message(
            display,
            title="Failed",
            body=outcome.error[:96],
            accent=COLOR_DANGER,
        )
        time.sleep(hold_seconds)
        return


def _offer_companion_pairing_after_wallet_save(
    display: Display,
    input_mgr: InputManager,
    vault: Vault,
    pin: str,
    wallet: WalletRecord,
    *,
    idle_wake: IdleWakeTracker,
    target_fps: int,
) -> bool:
    """Optional xpub_export multipart QR for the PiWalletSV companion.

    Returns ``True`` when the user long-pressed B inside the QR screen
    and wants to exit the bonnet app; ``False`` otherwise.
    """
    prompt = OfferCompanionPairingScreen(wallet.label or wallet.id)
    run_screen(
        display,
        input_mgr,
        prompt,
        target_fps=target_fps,
        idle_wake=idle_wake,
    )
    if prompt.result is not True:
        return False
    try:
        lines = pairing_pw1_lines(vault, pin, wallet)
    except (VaultError, VaultWipedError) as exc:
        _show_message(
            display,
            title="Pairing failed",
            body=str(exc)[:96],
            accent=COLOR_DANGER,
        )
        time.sleep(2.0)
        return False
    qr_screen = PairingMultipartQrScreen(lines)
    run_screen(
        display,
        input_mgr,
        qr_screen,
        target_fps=target_fps,
        idle_wake=idle_wake,
    )
    return qr_screen.result == "exit"


def _show_status(display: Display, lines: list[str]) -> None:
    """Render a multi-line status screen used for transient banners."""
    fb = FrameBuffer(display.width, display.height)
    fb.clear()
    y = 60
    for line in lines:
        draw_text(fb, DISPLAY_WIDTH // 2, y, line, size=12, color=COLOR_DIM, anchor="mm")
        y += 18
    fb.draw.rectangle(
        (12, DISPLAY_HEIGHT - 20, DISPLAY_WIDTH - 12, DISPLAY_HEIGHT - 16),
        fill=COLOR_DIM,
    )
    display.flip(fb)


def run_bonnet(
    vault_path: Path,
    *,
    display: Display | None = None,
    input_mgr: InputManager | None = None,
    terms_path: Path | None = None,
    target_fps: int = 30,
) -> int:
    """Run the bonnet boot loop.

    Returns a Unix-style exit code. Useful exits:

    * 0   -- normal exit (operator long-pressed B from wallet list).
    * 1   -- vault is missing or empty *and* the operator hasn't created
             one via the CLI yet.
    * 2   -- the disclaimer was cancelled.
    * 3   -- the vault wiped itself during unlock.
    """
    from piwallet.runtime_logging import prepare_runtime_for_bonnet

    prepare_runtime_for_bonnet()

    own_display = display is None
    own_input = input_mgr is None
    if display is None:
        display = open_display("auto")
    if input_mgr is None:
        input_mgr = make_input_manager(open_input("auto"))

    idle_wake = IdleWakeTracker(input_mgr)

    try:
        # ---- 1. Disclaimer --------------------------------------
        if requires_acceptance(terms_path):
            screen = DisclaimerScreen()
            accepted = run_screen(
                display, input_mgr, screen, target_fps=target_fps, idle_wake=idle_wake
            )
            if accepted is not True:
                return 2
            mark_accepted(terms_path)

        # ---- 2. Unlock ------------------------------------------
        vault = Vault(vault_path)
        if not vault.exists or not vault.is_initialized:
            _show_message(
                display,
                title="No vault",
                body=(
                    "No vault on this device. Initialize with: "
                    "`piwallet vault init` from the CLI."
                ),
            )
            return 1

        verify = _make_verify_fn(vault)
        unlock = UnlockScreen(
            verify=verify,
            attempts_remaining=vault.attempts_remaining,
        )
        outcome: UnlockOutcome | None = run_screen(
            display, input_mgr, unlock, target_fps=target_fps, idle_wake=idle_wake
        )
        if outcome is None:
            return 2
        if outcome.kind == "wiped":
            return 3
        assert outcome.kind == "ok" and outcome.pin is not None
        pin = outcome.pin

        # ---- 3. List + detail loop ------------------------------
        while True:
            wallets = vault.list_wallets()
            wlist = WalletListScreen(wallets=wallets)
            chosen = run_screen(
                display, input_mgr, wlist, target_fps=target_fps, idle_wake=idle_wake
            )
            if chosen is None:
                # Long-press B exits the loop and the app.
                return 0
            if chosen is WalletListAction.NEW:
                outcome3 = run_create_wallet(
                    display,
                    input_mgr,
                    vault,
                    pin,
                    target_fps=target_fps,
                    idle_wake=idle_wake,
                )
                _surface_wallet_outcome(display, outcome3)
                if outcome3.wallet is not None:
                    quit_requested = _offer_companion_pairing_after_wallet_save(
                        display,
                        input_mgr,
                        vault,
                        pin,
                        outcome3.wallet,
                        idle_wake=idle_wake,
                        target_fps=target_fps,
                    )
                    if quit_requested:
                        return 0
                continue
            if chosen is WalletListAction.RESTORE:
                outcome4 = run_restore_wallet(
                    display,
                    input_mgr,
                    vault,
                    pin,
                    target_fps=target_fps,
                    idle_wake=idle_wake,
                )
                _surface_wallet_outcome(display, outcome4)
                if outcome4.wallet is not None:
                    quit_requested = _offer_companion_pairing_after_wallet_save(
                        display,
                        input_mgr,
                        vault,
                        pin,
                        outcome4.wallet,
                        idle_wake=idle_wake,
                        target_fps=target_fps,
                    )
                    if quit_requested:
                        return 0
                continue
            wallet = next((w for w in wallets if w.id == chosen), None)
            if wallet is None:
                continue
            active = wallet
            while True:
                mg = run_wallet_manage(
                    display,
                    input_mgr,
                    vault,
                    pin,
                    active,
                    target_fps=target_fps,
                    idle_wake=idle_wake,
                )
                if mg == "exit":
                    return 0
                if mg in ("deleted", "back"):
                    break
                if mg == "renamed":
                    refreshed = vault.list_wallets()
                    nw = next((w for w in refreshed if w.id == active.id), None)
                    if nw is None:
                        break
                    active = nw
                # "stay" or "renamed" → loop back to redraw the manage menu.
    finally:
        # Blank the panel whenever the bonnet loop ends (CLI passes display in,
        # so own_display is false — we still must turn the backlight off).
        if display is not None:
            try:
                display.set_backlight(False)
            except Exception as exc:  # pragma: no cover
                log.warning("display.set_backlight(False) on exit failed: %s", exc)
        if own_display and display is not None:
            try:
                display.close()
            except Exception as exc:  # pragma: no cover (best-effort cleanup)
                log.warning("display.close() failed: %s", exc)
        if own_input and input_mgr is not None and hasattr(input_mgr, "_backend"):
            try:
                input_mgr._backend.close()
            except Exception as exc:  # pragma: no cover
                log.warning("input backend close() failed: %s", exc)


def _attrs_for_testing() -> dict[str, Any]:  # pragma: no cover - test hook
    """Expose internals for tests without making them a public API."""
    return {
        "_make_verify_fn": _make_verify_fn,
        "_make_derive_address_fn": _make_derive_address_fn,
    }
