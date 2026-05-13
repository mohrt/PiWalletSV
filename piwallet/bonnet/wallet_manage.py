"""Bonnet wallet manage menu and per-action runner.

The menu is the per-wallet hub the operator lands on after selecting a
wallet from the wallet list. From here they can:

* show the deposit address (delegates to :class:`WalletDetailScreen`),
* show the xpub as an animated multipart QR (the "Companion QR" used
  to pair with the PWA companion),
* rename the wallet (double-confirm),
* erase the wallet from the Pi (double-confirm),
* go back to the wallet list.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from piwallet.bonnet.companion_pairing import pairing_pw1_lines
from piwallet.bonnet.wallet_detail import WalletDetailScreen
from piwallet.core import derivation as deriv
from piwallet.core.vault import Vault, VaultError, VaultWipedError, WalletRecord
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import COLOR_DANGER, COLOR_OK, Display, FrameBuffer
from piwallet.ui.double_confirm import DoubleConfirmScreen
from piwallet.ui.input import Button, Event, EventKind, InputManager
from piwallet.ui.label_entry import WalletLabelEntryScreen
from piwallet.ui.pairing_multipart_qr_screen import PairingMultipartQrScreen
from piwallet.ui.widgets import ListItem, ListView, Modal

log = logging.getLogger(__name__)


class WalletManageAction(Enum):
    """Row selection on :class:`WalletManageMenuScreen`."""

    RECEIVE = "receive"
    COMPANION_QR = "companion_qr"
    RENAME = "rename"
    DELETE = "delete"
    BACK = "back"


#: Outcomes from :func:`run_wallet_manage`:
#:
#: * ``"stay"``     - non-destructive action finished; redraw the menu.
#: * ``"renamed"``  - rename succeeded; caller should refresh ``WalletRecord``.
#: * ``"deleted"``  - wallet erased; caller should drop back to the wallet list.
#: * ``"back"``     - operator chose Back / long-pressed B from the menu;
#:                    caller should drop back to the wallet list.
#: * ``"exit"``     - operator long-pressed B inside a sub-screen to quit
#:                    the bonnet app entirely.
WalletManageResult = Literal["stay", "renamed", "deleted", "back", "exit"]


@dataclass
class WalletManageMenuScreen:
    """Per-wallet hub: receive address, xpub QR, rename, erase, back."""

    wallet: WalletRecord
    done: bool = False
    result: WalletManageAction | None = None
    _list: ListView = field(init=False)

    def __post_init__(self) -> None:
        label = self.wallet.label.strip() or "wallet"
        stub = label[:14] + ("..." if len(label) > 14 else "")
        self._list = ListView(
            title=f'"{stub}"',
            items=[
                ListItem(label="Show deposit address", value=WalletManageAction.RECEIVE),
                ListItem(label="Show xpub (QR)", value=WalletManageAction.COMPANION_QR),
                ListItem(label="Rename", value=WalletManageAction.RENAME),
                ListItem(label="Erase from Pi", value=WalletManageAction.DELETE),
                ListItem(label="< Back", value=WalletManageAction.BACK),
            ],
        )

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if event.button == Button.B and event.kind == EventKind.LONG:
            self.done = True
            self.result = WalletManageAction.BACK
            return
        self._list.on_event(event)
        raw = self._list.confirmed
        if isinstance(raw, WalletManageAction):
            self.done = True
            self.result = raw

    def draw(self, fb: FrameBuffer) -> None:
        self._list.draw(fb)


def _brief_modal(display: Display, *, title: str, body: str, accent: tuple[int, int, int]) -> None:
    fb = FrameBuffer(display.width, display.height)
    Modal(title=title, body=body, footer="", accent=accent).draw(fb)
    display.flip(fb)


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


def run_wallet_manage(
    display: Display,
    input_mgr: InputManager,
    vault: Vault,
    pin: str,
    wallet: WalletRecord,
    *,
    target_fps: int = 30,
    toast_seconds: float = 2.0,
    idle_wake: IdleWakeTracker | None = None,
) -> WalletManageResult:
    """Show manage menu and run the chosen sub-flow.

    Receive: shows :class:`WalletDetailScreen` for the current wallet.
    Companion QR: animates the xpub_export envelope as PW1 multipart frames.
    Rename: label editor → two-step confirmation → ``vault.rename_wallet``.
    Erase: two-step confirmation → ``vault.remove_wallet``.

    Returns one of :data:`WalletManageResult`. The caller is expected to
    loop, calling this function until the wallet is deleted, the user
    backs out to the wallet list, or the user long-presses B inside a
    sub-screen to exit the bonnet app.
    """
    menu = WalletManageMenuScreen(wallet=wallet)
    run_screen(display, input_mgr, menu, target_fps=target_fps, idle_wake=idle_wake)
    choice = menu.result

    if choice in (None, WalletManageAction.BACK):
        return "back"

    if choice == WalletManageAction.RECEIVE:
        try:
            derive = _make_derive_address_fn(vault, wallet.id, pin)
        except (VaultError, VaultWipedError) as exc:
            log.exception("derive xpub failed from manage")
            _brief_modal(
                display, title="Derive failed", body=str(exc)[:96], accent=COLOR_DANGER
            )
            time.sleep(toast_seconds)
            return "stay"
        detail = WalletDetailScreen(wallet=wallet, derive_address=derive)
        run_screen(
            display, input_mgr, detail, target_fps=target_fps, idle_wake=idle_wake
        )
        if detail.result == "exit":
            return "exit"
        # "back" or "manage" both drop back to the manage menu.
        return "stay"

    if choice == WalletManageAction.COMPANION_QR:
        try:
            lines = pairing_pw1_lines(vault, pin, wallet)
        except (VaultError, VaultWipedError) as exc:
            log.exception("pairing_pw1_lines failed from manage")
            _brief_modal(display, title="QR failed", body=str(exc)[:96], accent=COLOR_DANGER)
            time.sleep(toast_seconds)
            return "stay"
        qr = PairingMultipartQrScreen(lines)
        run_screen(display, input_mgr, qr, target_fps=target_fps, idle_wake=idle_wake)
        if qr.result == "exit":
            return "exit"
        return "stay"

    if choice == WalletManageAction.RENAME:
        # The label editor's own confirm step (Save / Edit again / Cancel)
        # is the single confirmation we need; no second double-confirm.
        editor = WalletLabelEntryScreen(
            title="Rename wallet",
            suggested_default=wallet.label,
        )
        run_screen(display, input_mgr, editor, target_fps=target_fps, idle_wake=idle_wake)
        if editor.result is None:
            return "stay"
        new_label = editor.result.strip()
        if new_label == (wallet.label or "").strip():
            return "stay"
        try:
            vault.rename_wallet(pin, wallet.id, new_label)
        except VaultError as exc:
            log.exception("rename_wallet failed from bonnet")
            _brief_modal(display, title="Rename failed", body=str(exc)[:96], accent=COLOR_DANGER)
            time.sleep(toast_seconds)
            return "stay"
        _brief_modal(
            display,
            title="Renamed",
            body=new_label[:96],
            accent=COLOR_OK,
        )
        time.sleep(toast_seconds)
        return "renamed"

    # DELETE
    assert choice == WalletManageAction.DELETE
    wl = wallet.label.strip() or "wallet"
    stub = wl[:14] + ("..." if len(wl) > 14 else "")
    dc_del = DoubleConfirmScreen(
        title="Erase wallet?",
        first_prompt=(
            f'Wallet "{stub}" is removed from this device only. '
            "Your on-chain balance is not deleted. "
            "You still need your seed phrase to spend those funds later. "
            "Press A for the final warning."
        ),
        second_prompt=(
            "This is the last step. The wallet will be deleted from the "
            "vault on this Pi with no undo. Your backup is the phrase only. "
            "Press A to erase permanently or B to stop."
        ),
        second_step_warning=True,
        second_title="Last chance to stop",
    )
    run_screen(display, input_mgr, dc_del, target_fps=target_fps, idle_wake=idle_wake)
    if dc_del.result is not True:
        return "stay"
    try:
        vault.remove_wallet(pin, wallet.id)
    except VaultError as exc:
        log.exception("remove_wallet failed from bonnet")
        _brief_modal(display, title="Erase failed", body=str(exc)[:96], accent=COLOR_DANGER)
        time.sleep(toast_seconds)
        return "stay"
    _brief_modal(
        display,
        title="Erased",
        body="Wallet dropped from vault.\nFunds stay on-chain.",
        accent=COLOR_OK,
    )
    time.sleep(toast_seconds)
    return "deleted"
