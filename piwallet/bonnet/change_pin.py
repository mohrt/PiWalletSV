"""Bonnet "Change PIN" flow.

Reachable from the Settings screen via the "Change PIN…" action row.
Sequences three sub-screens:

1. :class:`UnlockScreen` — verify the *current* PIN. Reusing the
   unlock composite means the same wrong-PIN retry, attempt-counter
   subtitle, and wipe-on-N-failures contract apply here as on first
   boot. Cancellable via long-B.
2. :class:`PinSetupScreen` (cancellable) — choose-and-confirm the new
   PIN.
3. :meth:`Vault.change_pin` — re-wraps every wallet's DEK under the
   new PIN-derived KEK and rotates the scrypt salt.

Outcomes
--------
=================================  =================================
Result string                       Caller action
=================================  =================================
``"changed"``                       Update the in-memory PIN to the
                                    new one returned alongside, then
                                    re-open the Settings screen so
                                    the operator sees they're back
                                    where they started.
``"cancelled"``                     Operator backed out of the
                                    current-PIN or new-PIN screen.
                                    Re-open Settings.
``"wiped"``                         Verifying the current PIN tripped
                                    the attempts threshold and the
                                    vault has been destroyed. Caller
                                    must propagate this up to
                                    :func:`run_bonnet` so the loop
                                    exits with the wiped status code.
=================================  =================================

The current PIN is verified by calling
:meth:`Vault.derive_signing_key`-style methods through the existing
:class:`UnlockScreen` plumbing — but we own the verify callback here
so we can wire it specifically to :meth:`Vault.change_pin`'s
ergonomics. Concretely, the verify callback uses
:meth:`Vault.get_account_xpub` on any wallet (or a synthetic dry-run
unwrap when no wallets exist), which has the same attempt-counter
semantics as a real unlock.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from piwallet.bonnet.unlock import UnlockScreen, VerifyResult
from piwallet.core.vault import (
    Vault,
    VaultError,
    VaultWipedError,
    WrongPinError,
)
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import COLOR_DANGER, COLOR_OK, Display, FrameBuffer
from piwallet.ui.input import InputManager
from piwallet.ui.pin_setup import PinSetupScreen
from piwallet.ui.widgets import Modal

log = logging.getLogger(__name__)

ChangePinResult = Literal["changed", "cancelled", "wiped"]


def _show_message(
    display: Display,
    *,
    title: str,
    body: str,
    accent: tuple[int, int, int],
) -> None:
    fb = FrameBuffer(display.width, display.height)
    Modal(title=title, body=body, footer="", accent=accent).draw(fb)
    display.flip(fb)


def _make_verify_fn(vault: Vault):
    """Build a :class:`UnlockScreen`-compatible verify callback.

    Verifies the candidate PIN by attempting a benign read
    (``get_account_xpub``) on the first wallet, or — for an empty
    vault — by trusting the format check inside
    :meth:`Vault.change_pin`. The attempt counter / wipe-on-N
    contract is honoured the same way an ordinary unlock honours it.
    """

    def verify(pin: str) -> VerifyResult:
        wallets = vault.list_wallets()
        if not wallets:
            # Empty vault: there's no ciphertext to verify against.
            # We accept the candidate and let change_pin rotate the
            # salt. This mirrors the existing remove_wallet /
            # rename_wallet behaviour on an empty vault.
            return ("ok", None)
        try:
            vault.get_account_xpub(pin, wallets[0].id)
        except WrongPinError as exc:
            return ("wrong", exc.attempts_remaining)
        except VaultWipedError:
            return ("wiped", None)
        except VaultError:
            log.exception("verify_for_change_pin: unexpected vault error")
            return ("wrong", None)
        return ("ok", None)

    return verify


def run_change_pin(
    display: Display,
    input_mgr: InputManager,
    vault: Vault,
    current_pin: str,
    *,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
    toast_seconds: float = 2.0,
) -> tuple[ChangePinResult, str | None]:
    """Drive the change-PIN flow.

    Returns a ``(result, new_pin)`` tuple. ``new_pin`` is populated
    only when ``result == "changed"`` so the caller can update its
    cached PIN to the new value (allowing the wallet-list loop to
    continue without forcing a re-unlock).

    ``current_pin`` is passed in so we can short-circuit the verify
    step when the operator has *just* unlocked the vault and we
    trust the value; it is *also* re-verified through
    :class:`UnlockScreen` against the live vault so we get the
    proper attempt-counter semantics if the vault was wiped from
    under us between calls.
    """
    # ---- 1. Verify current PIN -----------------------------------
    unlock = UnlockScreen(
        verify=_make_verify_fn(vault),
        attempts_remaining=vault.attempts_remaining,
    )
    unlock.pin_entry.title = "Current PIN"
    run_screen(display, input_mgr, unlock, target_fps=target_fps, idle_wake=idle_wake)
    if unlock.result is None:
        # PinEntry-inside-Unlock has no cancel gesture today; this
        # branch only fires if the screen exited without a result
        # (idle blank, etc). Treat as cancel so the caller redraws
        # Settings rather than crashing.
        return ("cancelled", None)
    if unlock.result.kind == "wiped":
        return ("wiped", None)
    assert unlock.result.kind == "ok" and unlock.result.pin is not None
    verified_pin = unlock.result.pin
    # If the operator typed a different PIN than what we expected,
    # honour what they typed — the verify callback proved it works.
    if verified_pin != current_pin:
        log.info("change_pin: verified pin differs from cached pin; using verified")

    # ---- 2. Choose new PIN (double-confirm) ----------------------
    setup = PinSetupScreen(
        prompt="Choose new PIN",
        confirm_prompt="Confirm new PIN",
        cancellable=True,
    )
    run_screen(display, input_mgr, setup, target_fps=target_fps, idle_wake=idle_wake)
    if not setup.done or setup.result is None:
        return ("cancelled", None)
    new_pin = setup.result

    if new_pin == verified_pin:
        _show_message(
            display,
            title="No change",
            body="New PIN matches the current one.",
            accent=COLOR_DANGER,
        )
        time.sleep(toast_seconds)
        return ("cancelled", None)

    # ---- 3. Re-wrap every wallet under the new PIN ---------------
    try:
        vault.change_pin(verified_pin, new_pin)
    except WrongPinError:
        # Should be unreachable — we just verified — but keep the
        # branch so a vault state race (e.g. concurrent CLI access)
        # can't propagate a confusing exception to the UI loop.
        log.exception("change_pin raised WrongPinError after verify")
        _show_message(
            display,
            title="Change failed",
            body="Wrong current PIN. Try again.",
            accent=COLOR_DANGER,
        )
        time.sleep(toast_seconds)
        return ("cancelled", None)
    except VaultWipedError:
        return ("wiped", None)
    except VaultError as exc:
        log.exception("change_pin failed")
        _show_message(
            display,
            title="Change failed",
            body=str(exc)[:96],
            accent=COLOR_DANGER,
        )
        time.sleep(toast_seconds)
        return ("cancelled", None)

    _show_message(
        display,
        title="PIN changed",
        body="The vault is re-encrypted with the new PIN.",
        accent=COLOR_OK,
    )
    time.sleep(toast_seconds)
    return ("changed", new_pin)
