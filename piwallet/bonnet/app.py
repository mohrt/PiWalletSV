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

3. **Wallet list -> detail.** After unlock, the operator browses the
   list of wallets and drills into one to view receive addresses.
   Long-pressing B at any screen returns up one level; long-press B
   from the wallet list exits the bonnet app cleanly.

This loop is *meant* to be the main process on the Pi. It does not
fork, daemonize, or open any network sockets.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from piwallet.bonnet.unlock import UnlockOutcome, UnlockScreen, VerifyFn
from piwallet.bonnet.wallet_detail import WalletDetailScreen
from piwallet.bonnet.wallet_list import WalletListScreen
from piwallet.core import derivation as deriv
from piwallet.core.vault import (
    Vault,
    VaultError,
    VaultWipedError,
    WalletNotFoundError,
    WrongPinError,
)
from piwallet.firstboot.disclaimer import DisclaimerScreen
from piwallet.firstboot.terms import mark_accepted, requires_acceptance
from piwallet.ui.app import make_input_manager, run_screen
from piwallet.ui.display import (
    COLOR_DANGER,
    COLOR_DIM,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    Display,
    FrameBuffer,
    open_display,
)
from piwallet.ui.input import InputManager, open_input
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
    own_display = display is None
    own_input = input_mgr is None
    if display is None:
        display = open_display("auto")
    if input_mgr is None:
        input_mgr = make_input_manager(open_input("auto"))

    try:
        # ---- 1. Disclaimer --------------------------------------
        if requires_acceptance(terms_path):
            screen = DisclaimerScreen()
            accepted = run_screen(display, input_mgr, screen, target_fps=target_fps)
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
                    "No vault on this device. Use the CLI: "
                    "`piwallet vault init` then `piwallet wallet add`."
                ),
            )
            return 1

        verify = _make_verify_fn(vault)
        unlock = UnlockScreen(
            verify=verify,
            attempts_remaining=vault.attempts_remaining,
        )
        outcome: UnlockOutcome | None = run_screen(
            display, input_mgr, unlock, target_fps=target_fps
        )
        if outcome is None or outcome.kind == "cancelled":
            return 2
        if outcome.kind == "wiped":
            return 3
        assert outcome.kind == "ok" and outcome.pin is not None
        pin = outcome.pin

        # ---- 3. List + detail loop ------------------------------
        while True:
            wallets = vault.list_wallets()
            wlist = WalletListScreen(wallets=wallets)
            chosen = run_screen(display, input_mgr, wlist, target_fps=target_fps)
            if chosen is None:
                # Long-press B exits the loop and the app.
                return 0
            wallet = next((w for w in wallets if w.id == chosen), None)
            if wallet is None:
                continue
            derive = _make_derive_address_fn(vault, wallet.id, pin)
            detail = WalletDetailScreen(wallet=wallet, derive_address=derive)
            outcome2 = run_screen(display, input_mgr, detail, target_fps=target_fps)
            if outcome2 == "exit":
                return 0
            # "back" -> loop iteration restarts at the wallet list.
    finally:
        # The display / input manager were constructed here; tear them
        # down so the caller doesn't have to.
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
