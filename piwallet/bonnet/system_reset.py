"""Bonnet "System reset" flow — factory wipe from Settings."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Literal

from piwallet.bonnet.unlock import UnlockScreen, VerifyResult
from piwallet.core.factory_reset import factory_reset
from piwallet.core.vault import (
    Vault,
    VaultError,
    VaultWipedError,
    WrongPinError,
)
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import COLOR_OK, Display, FrameBuffer
from piwallet.ui.double_confirm import DoubleConfirmScreen
from piwallet.ui.input import InputManager
from piwallet.ui.widgets import Modal

log = logging.getLogger(__name__)

SystemResetResult = Literal["completed", "cancelled", "wiped"]


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
    """Verify the operator's PIN before erasing device state."""

    def verify(pin: str) -> VerifyResult:
        wallets = vault.list_wallets()
        if not wallets:
            return ("ok", None)
        try:
            vault.get_account_xpub(pin, wallets[0].id)
        except WrongPinError as exc:
            return ("wrong", exc.attempts_remaining)
        except VaultWipedError:
            return ("wiped", None)
        except VaultError:
            log.exception("system_reset verify: unexpected vault error")
            return ("wrong", None)
        return ("ok", None)

    return verify


def run_system_reset(
    display: Display,
    input_mgr: InputManager,
    vault: Vault,
    *,
    vault_path: Path,
    settings_path: Path | None,
    terms_path: Path | None,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
    toast_seconds: float = 2.0,
) -> SystemResetResult:
    """Double-confirm, verify PIN, then wipe vault + settings + terms."""
    confirm = DoubleConfirmScreen(
        title="Reset device?",
        first_prompt=(
            "All wallets, PINs, and settings are erased from this Pi. "
            "Funds stay on the blockchain — only your seed phrase can "
            "recover them. Press A for the final warning."
        ),
        second_prompt=(
            "This cannot be undone. The device returns to first-setup, "
            "as if new. Press A to erase everything or B to stop."
        ),
        second_step_warning=True,
        second_title="Erase all device data",
    )
    run_screen(
        display,
        input_mgr,
        confirm,
        target_fps=target_fps,
        idle_wake=idle_wake,
    )
    if confirm.result is not True:
        return "cancelled"

    unlock = UnlockScreen(
        verify=_make_verify_fn(vault),
        attempts_remaining=vault.attempts_remaining,
    )
    unlock.pin_entry.title = "PIN to confirm reset"
    run_screen(
        display,
        input_mgr,
        unlock,
        target_fps=target_fps,
        idle_wake=idle_wake,
    )
    if unlock.result is None:
        return "cancelled"
    if unlock.result.kind == "wiped":
        return "wiped"
    assert unlock.result.kind == "ok"

    try:
        factory_reset(
            vault_path=vault_path,
            settings_path=settings_path,
            terms_path=terms_path,
        )
    except OSError as exc:
        log.exception("factory_reset failed")
        _show_message(
            display,
            title="Reset failed",
            body=str(exc)[:96],
            accent=(224, 80, 80),
        )
        time.sleep(toast_seconds)
        return "cancelled"

    _show_message(
        display,
        title="Device reset",
        body="All data erased. Set up this Pi as a new device.",
        accent=COLOR_OK,
    )
    time.sleep(toast_seconds)
    return "completed"
