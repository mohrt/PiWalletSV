"""Bonnet flow for securing companion-delivered wallet transactions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from piwallet.bonnet.qr_settings import qr_brightness_screen_kwargs
from piwallet.bonnet.sign_scan import (
    ScanProposalScreen,
    _make_default_worker,
    _preflight_camera_imports,
    _show_modal,
)
from piwallet.core import envelope as env
from piwallet.core.settings import BonnetSettings
from piwallet.core.state import WalletStateError, WalletStateStore
from piwallet.core.vault import Vault, VaultError, VaultWipedError, WalletRecord
from piwallet.qr.multipart import split_envelope_to_lines
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import COLOR_DANGER, Display
from piwallet.ui.input import InputManager
from piwallet.ui.pairing_multipart_qr_screen import PairingMultipartQrScreen

log = logging.getLogger(__name__)


def run_state_sync_flow(
    display: Display,
    input_mgr: InputManager,
    vault: Vault,
    pin: str,
    wallet: WalletRecord,
    *,
    target_fps: int = 30,
    toast_seconds: float = 2.0,
    idle_wake: IdleWakeTracker | None = None,
    start_worker=None,
    settings: BonnetSettings | None = None,
    settings_path: Path | None = None,
    on_settings_changed: Callable[[BonnetSettings], None] | None = None,
) -> str:
    """Scan a state-sync package, verify it offline, and return a receipt."""
    if start_worker is None:
        cam_err = _preflight_camera_imports()
        if cam_err is not None:
            _show_modal(
                display,
                title="Camera unavailable",
                body=cam_err,
                accent=COLOR_DANGER,
                hold_seconds=toast_seconds,
            )
            return "stay"
        start_worker = _make_default_worker()

    scan = ScanProposalScreen(title="Secure payments", start_worker=start_worker)
    run_screen(display, input_mgr, scan, target_fps=target_fps, idle_wake=idle_wake)
    if not isinstance(scan.result, (bytes, bytearray)):
        return "stay"
    try:
        decoded = env.decode(bytes(scan.result))
        if not isinstance(decoded, env.StateSync):
            raise WalletStateError(f"got {type(decoded).__name__}, expected state sync")
        if decoded.wallet_fp != wallet.fingerprint:
            raise WalletStateError("state sync is for a different wallet")
        xpub = vault.get_account_xpub(pin, wallet.id)
        state_key = vault.derive_state_key(pin, wallet.id)
        _, receipt = WalletStateStore(vault.state_path).apply_sync(wallet, state_key, decoded, xpub)
    except (env.EnvelopeError, WalletStateError, VaultError, VaultWipedError) as exc:
        log.exception("state sync failed")
        _show_modal(
            display,
            title="Sync failed",
            body=str(exc)[:96],
            accent=COLOR_DANGER,
            hold_seconds=toast_seconds,
        )
        return "stay"

    blob = env.encode(receipt)
    lines = split_envelope_to_lines(blob, max_encoded_chunk_chars=100)
    qr = PairingMultipartQrScreen(
        lines,
        title="State secured",
        **qr_brightness_screen_kwargs(
            settings,
            settings_path=settings_path,
            on_settings_changed=on_settings_changed,
        ),
    )
    run_screen(display, input_mgr, qr, target_fps=target_fps, idle_wake=idle_wake)
    return "stay"


__all__ = ["run_state_sync_flow"]
