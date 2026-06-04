"""Top-level bonnet boot loop.

This is the entry point the systemd unit / SD-card image runs on
startup. It performs, in order:

1. **Disclaimer.** If the operator hasn't accepted the current
   disclaimer version, walk them through the three-page
   :class:`piwallet.firstboot.DisclaimerScreen`. Persist acceptance
   on success; exit on cancel.

2. **Vault setup or unlock.** If no vault exists on disk, run
   :func:`piwallet.bonnet.vault_setup.run_vault_setup` to walk the
   operator through picking a PIN twice and create the empty vault
   on the spot — first-boot devices never see the legacy "use the
   CLI" dead-end. If a vault already exists, present the
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

import fcntl
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Single-instance display lock
# ---------------------------------------------------------------------------

_DISPLAY_LOCK_PATH = "/tmp/piwallet-display.lock"
_display_lock_fd: int = -1  # kept open for the lifetime of the process


def _acquire_display_lock() -> bool:
    """Acquire an exclusive process lock on the bonnet display.

    Uses ``flock(LOCK_EX | LOCK_NB)`` so the lock is automatically released
    by the OS when this process exits (even on crash / SIGKILL).  Returns
    ``True`` if the lock was acquired, ``False`` if another process holds it.
    """
    global _display_lock_fd
    fd = -1
    try:
        fd = os.open(_DISPLAY_LOCK_PATH, os.O_CREAT | os.O_WRONLY, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        _display_lock_fd = fd
        return True
    except OSError:
        if fd >= 0:
            os.close(fd)
        return False

from piwallet.bonnet.airgap_screen import AirgapScreen
from piwallet.bonnet.usb_backup import (
    release_usb_session,
    run_usb_backup,
    run_usb_backup_menu,
    run_usb_restore,
)
from piwallet.bonnet.change_pin import run_change_pin
from piwallet.bonnet.companion_pairing import (
    OfferCompanionPairingScreen,
    pairing_pw1_lines,
)
from piwallet.bonnet.create_wallet import CreateWalletOutcome, run_create_wallet
from piwallet.bonnet.restore_wallet import RestoreWalletOutcome, run_restore_wallet
from piwallet.bonnet.unlock import UnlockOutcome, UnlockScreen, VerifyFn
from piwallet.bonnet.vault_setup import run_vault_setup
from piwallet.bonnet.wallet_list import WalletListAction, WalletListScreen
from piwallet.bonnet.wallet_manage import run_wallet_manage
from piwallet.core import derivation as deriv
from piwallet.core.settings import (
    BonnetSettings,
    load_settings,
    save_settings,
)
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
from piwallet.ui.input import Button, Event, EventKind, InputManager, open_input
from piwallet.ui.pairing_multipart_qr_screen import PairingMultipartQrScreen
from piwallet.ui.settings_screen import SettingsScreen
from piwallet.ui.widgets import ListItem, ListView, Modal, draw_text

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
    """Build a ``(change, index) -> address`` closure for a wallet.

    Reads the wallet's stored network (``"main"`` / ``"test"``) so
    rendered addresses are valid for the network the operator
    configured at create-time.
    """
    xpub_str = vault.get_account_xpub(pin, wallet_id)
    xpub = deriv.parse_xpub(xpub_str)
    rec = next(
        (w for w in vault.list_wallets() if w.id == wallet_id),
        None,
    )
    network: deriv.Network = rec.network if rec is not None else deriv.NETWORK_MAIN

    def derive(change: int, index: int) -> str:
        return deriv.derive_address(xpub, change, index, network=network)
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


def _run_settings_loop(
    display: Display,
    input_mgr: InputManager,
    settings: BonnetSettings,
    *,
    vault: Vault,
    pin: str,
    settings_path: Path | None,
    target_fps: int,
    idle_wake: IdleWakeTracker,
) -> tuple[BonnetSettings, str, bool, str]:
    """Open the Settings screen and dispatch on its result.

    Returns ``(settings, status, exit_requested, pin)`` where:

    * ``settings`` is the (possibly edited) settings record. Value-row
      drafts are persisted to disk on save; on cancel the disk file
      is left untouched and the live brightness preview is reverted.
    * ``status`` is one of:

        - ``"saved"``     value-row edits were saved.
        - ``"back"``      operator cancelled.
        - ``"exit"``      operator long-pressed B (caller must quit).
        - ``"changed_pin"`` PIN was rotated; ``pin`` reflects the new
          value and the caller must reuse it for subsequent
          vault-gated operations.
        - ``"wiped"``     vault was wiped while verifying the current
          PIN; caller must propagate as exit code 3.
        - ``"restored_usb"`` vault replaced from USB; caller must
          re-unlock with the backup PIN.
    * ``exit_requested`` is the legacy long-B flag, retained for
      callers that still treat it specially.
    * ``pin`` is the active PIN to use after this call returns.

    Live brightness preview is wired to ``display.set_brightness`` so
    the panel reflects the in-progress draft.
    """
    while True:
        screen = SettingsScreen(
            settings=settings,
            apply_brightness=display.set_brightness,
        )
        run_screen(
            display,
            input_mgr,
            screen,
            target_fps=target_fps,
            idle_wake=idle_wake,
        )
        if screen.result == "saved":
            save_settings(screen.settings, settings_path)
            display.set_brightness(screen.settings.brightness)
            return screen.settings, "saved", False, pin
        if screen.result == "exit":
            return settings, "exit", True, pin
        if screen.result == "change_pin":
            # The screen saved any value-row drafts on its own (A on an
            # action row commits the draft so a half-adjusted brightness
            # slider isn't lost while the sub-flow runs). Persist now,
            # then drive the change-PIN sub-flow.
            save_settings(screen.settings, settings_path)
            display.set_brightness(screen.settings.brightness)
            result, new_pin = run_change_pin(
                display,
                input_mgr,
                vault,
                pin,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
            if result == "wiped":
                return screen.settings, "wiped", False, pin
            if result == "changed" and new_pin is not None:
                return screen.settings, "changed_pin", False, new_pin
            # "cancelled" - keep the saved settings, original PIN.
            return screen.settings, "saved", False, pin
        if screen.result == "airgap":
            # Same value-row-draft-saving pattern as change_pin: persist
            # any in-flight tweaks before opening the airgap diag, so an
            # operator who fiddled with brightness and then tapped the
            # airgap row doesn't lose their slider change. The airgap
            # screen itself is read-only — it can return only "back" or
            # "exit".
            save_settings(screen.settings, settings_path)
            display.set_brightness(screen.settings.brightness)
            airgap = AirgapScreen()
            run_screen(
                display,
                input_mgr,
                airgap,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
            if airgap.result == "exit":
                return screen.settings, "exit", True, pin
            return screen.settings, "saved", False, pin
        if screen.result == "usb_backup":
            save_settings(screen.settings, settings_path)
            display.set_brightness(screen.settings.brightness)
            settings = screen.settings
            while True:
                choice = run_usb_backup_menu(
                    display,
                    input_mgr,
                    target_fps=target_fps,
                    idle_wake=idle_wake,
                )
                if choice is None:
                    release_usb_session()
                    break
                if choice == "backup":
                    run_usb_backup(
                        display,
                        input_mgr,
                        vault_path=vault.path,
                        settings_path=settings_path,
                        target_fps=target_fps,
                        idle_wake=idle_wake,
                    )
                elif choice == "restore":
                    flow = run_usb_restore(
                        display,
                        input_mgr,
                        vault_path=vault.path,
                        settings_path=settings_path,
                        target_fps=target_fps,
                        idle_wake=idle_wake,
                    )
                    if flow == "ok":
                        return screen.settings, "restored_usb", False, pin
            continue
        # "back": SettingsScreen has already reverted the live preview.
        return settings, "back", False, pin


def run_bonnet(
    vault_path: Path,
    *,
    display: Display | None = None,
    input_mgr: InputManager | None = None,
    terms_path: Path | None = None,
    settings_path: Path | None = None,
    target_fps: int = 30,
) -> int:
    """Run the bonnet boot loop.

    Returns a Unix-style exit code. Useful exits:

    * 0   -- normal exit (operator long-pressed B from wallet list).
    * 1   -- in-bonnet vault setup itself failed (rare: an on-disk
             race between ``vault.exists`` at boot and the
             ``vault.create`` call inside the setup flow). The
             operator is shown a "Vault setup failed" modal and
             pointed at the CLI.
    * 2   -- the disclaimer was cancelled.
    * 3   -- the vault wiped itself during unlock or during a PIN
             change attempt.

    ``settings_path`` overrides the location of the persistent global
    settings JSON file (default: ``~/.piwallet/settings.json``).
    Settings are loaded on entry and persisted only when the operator
    saves changes from the Settings screen.
    """
    from piwallet.core.paths import migrate_legacy_dev_dir
    from piwallet.runtime_logging import prepare_runtime_for_bonnet

    prepare_runtime_for_bonnet()

    if not _acquire_display_lock():
        log.error(
            "Another piwallet bonnet process is already running "
            "(lock held at %s). Stop it before starting a new instance.",
            _DISPLAY_LOCK_PATH,
        )
        return 4

    # One-shot migration for developer Pis that still have the legacy
    # `~/.piwallet-dev/` directory from before the rename. No-op on a
    # freshly-flashed image (canonical dir is created later by the
    # vault-setup flow) and no-op once it's run. Logged either way so
    # journald captures the fact for the operator.
    migrate_legacy_dev_dir()

    import signal

    own_display = display is None
    own_input = input_mgr is None
    if display is None:
        display = open_display("auto")
    if input_mgr is None:
        input_mgr = make_input_manager(open_input("auto"))

    # Release GPIO/SPI cleanly on Ctrl-C so the display resets properly
    # on the next run. Without this the RST pin stays claimed and the
    # ST7789 never gets a hardware reset, leaving the screen blank.
    def _shutdown(sig: int, frame: object) -> None:
        if own_display:
            display.set_backlight(False)
            display.close()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Apply persisted brightness up front so the disclaimer / unlock
    # screens already reflect the operator's preference. The sleep
    # timer is threaded into IdleWakeTracker so the disclaimer flow
    # already honours the operator's setting (5 min default; 0 = off).
    settings = load_settings(settings_path)
    display.set_brightness(settings.brightness)

    idle_wake = IdleWakeTracker(input_mgr, timeout_ms=settings.sleep_timeout_ms)

    try:
        # ---- 0. Splash ------------------------------------------
        # Draw the logo once, sleep, then move on. Running the full
        # animation loop (60 SPI transfers at 24 MHz) leaves the ST7789
        # in a corrupted state that makes all subsequent frames appear
        # black, so we use a single flip + sleep instead.
        from piwallet.bonnet.splash import show_splash_once

        show_splash_once(display)

        # ---- 1. Disclaimer --------------------------------------
        if requires_acceptance(terms_path):
            screen = DisclaimerScreen()
            accepted = run_screen(
                display, input_mgr, screen, target_fps=target_fps, idle_wake=idle_wake
            )
            if accepted is not True:
                return 2
            mark_accepted(terms_path)

        # ---- 2. Vault setup (first boot) or Unlock --------------
        vault = Vault(vault_path)
        if not vault.exists or not vault.is_initialized:
            @dataclass
            class _FirstBootChooser:
                done: bool = False
                result: str | None = None
                _list: ListView = field(init=False)

                def __post_init__(self) -> None:
                    self._list = ListView(
                        items=[
                            ListItem(label="New vault (set PIN)", value="new"),
                            ListItem(label="Restore from USB", value="usb"),
                        ],
                        title="First setup",
                    )

                def on_event(self, event: Event) -> None:
                    if self.done:
                        return
                    if event.button == Button.B and event.kind in (
                        EventKind.PRESS,
                        EventKind.LONG,
                    ):
                        self.done = True
                        return
                    self._list.on_event(event)
                    if self._list.confirmed is not None:
                        self.done = True
                        self.result = str(self._list.confirmed)

                def draw(self, fb: FrameBuffer) -> None:
                    self._list.draw(fb)

            chooser = _FirstBootChooser()
            run_screen(
                display,
                input_mgr,
                chooser,
                target_fps=target_fps,
                idle_wake=idle_wake,
            )
            if chooser.result == "usb":
                flow = run_usb_restore(
                    display,
                    input_mgr,
                    vault_path=vault_path,
                    settings_path=settings_path,
                    target_fps=target_fps,
                    idle_wake=idle_wake,
                )
                vault = Vault(vault_path)
                if flow == "ok" and vault.is_initialized:
                    verify = _make_verify_fn(vault)
                    unlock = UnlockScreen(
                        verify=verify,
                        attempts_remaining=vault.attempts_remaining,
                    )
                    outcome: UnlockOutcome | None = run_screen(
                        display,
                        input_mgr,
                        unlock,
                        target_fps=target_fps,
                        idle_wake=idle_wake,
                    )
                    if outcome is None:
                        return 2
                    if outcome.kind == "wiped":
                        return 3
                    assert outcome.kind == "ok" and outcome.pin is not None
                    pin = outcome.pin
                elif flow == "cancelled":
                    chooser = _FirstBootChooser()
                    run_screen(
                        display,
                        input_mgr,
                        chooser,
                        target_fps=target_fps,
                        idle_wake=idle_wake,
                    )
                    if chooser.result != "new":
                        return 2
                    setup_result = run_vault_setup(
                        display,
                        input_mgr,
                        vault_path,
                        target_fps=target_fps,
                        idle_wake=idle_wake,
                    )
                    if setup_result is None:
                        _show_message(
                            display,
                            title="No vault",
                            body=(
                                "Vault setup failed. Try `piwallet vault init` "
                                "from the CLI."
                            ),
                        )
                        return 1
                    vault, pin = setup_result
                elif flow != "ok":
                    return 2
                else:
                    setup_result = run_vault_setup(
                        display,
                        input_mgr,
                        vault_path,
                        target_fps=target_fps,
                        idle_wake=idle_wake,
                    )
                    if setup_result is None:
                        _show_message(
                            display,
                            title="No vault",
                            body=(
                                "Vault setup failed. Try `piwallet vault init` "
                                "from the CLI."
                            ),
                        )
                        return 1
                    vault, pin = setup_result
            elif chooser.result == "new":
                setup_result = run_vault_setup(
                    display,
                    input_mgr,
                    vault_path,
                    target_fps=target_fps,
                    idle_wake=idle_wake,
                )
                if setup_result is None:
                    _show_message(
                        display,
                        title="No vault",
                        body=(
                            "Vault setup failed. Try `piwallet vault init` "
                            "from the CLI."
                        ),
                    )
                    return 1
                vault, pin = setup_result
            else:
                return 2
        else:
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
                # WalletListScreen never sets ``result=None`` in normal
                # operation (there is no "quit the app" gesture from the
                # top level — operators just power off). Treat it as a
                # defensive no-op and re-show the list.
                continue
            if chosen is WalletListAction.NEW:
                outcome3 = run_create_wallet(
                    display,
                    input_mgr,
                    vault,
                    pin,
                    target_fps=target_fps,
                    idle_wake=idle_wake,
                    settings=settings,
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
            if chosen is WalletListAction.SETTINGS:
                settings, status, exit_requested, pin = _run_settings_loop(
                    display,
                    input_mgr,
                    settings,
                    vault=vault,
                    pin=pin,
                    settings_path=settings_path,
                    target_fps=target_fps,
                    idle_wake=idle_wake,
                )
                # Apply the (possibly edited) sleep timeout immediately
                # so the next idle window honours the operator's choice
                # without needing a bonnet restart.
                idle_wake.timeout_ms = settings.sleep_timeout_ms
                if status == "wiped":
                    return 3
                if status == "restored_usb":
                    vault = Vault(vault_path)
                    verify = _make_verify_fn(vault)
                    unlock = UnlockScreen(
                        verify=verify,
                        attempts_remaining=vault.attempts_remaining,
                    )
                    outcome = run_screen(
                        display,
                        input_mgr,
                        unlock,
                        target_fps=target_fps,
                        idle_wake=idle_wake,
                    )
                    if outcome is None:
                        return 2
                    if outcome.kind == "wiped":
                        return 3
                    assert outcome.kind == "ok" and outcome.pin is not None
                    pin = outcome.pin
                    settings = load_settings(settings_path)
                    display.set_brightness(settings.brightness)
                    idle_wake.timeout_ms = settings.sleep_timeout_ms
                if exit_requested:
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
                    settings=settings,
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
