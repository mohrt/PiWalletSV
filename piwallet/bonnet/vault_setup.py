"""First-boot vault initialisation flow.

Replaces the legacy "vault missing — run ``piwallet vault init`` from
the CLI" dead-end with an in-bonnet "choose a PIN" flow. After the
operator confirms a PIN twice via :class:`PinSetupScreen`, this module
calls :meth:`Vault.create` and returns the live ``(vault, pin)`` pair
to the caller so it can drop straight into the wallet-list loop
without re-prompting.

Cancel semantics
----------------
The flow is **non-cancellable** by design. The disclaimer step has
already been accepted by the time this runs (see
:mod:`piwallet.bonnet.app`); there's nowhere meaningful to "go back"
to without dropping the operator into a freshly-rebooted bonnet that
would just present the same setup screen again. If a real bail-out
becomes necessary later (e.g. an "Erase device" gesture), it should
be added as an explicit menu rather than overloading the long-B
gesture inside PIN entry.

Failure modes
-------------
:meth:`Vault.create` validates the PIN format independently — but the
:class:`PinSetupScreen` only emits a 6-digit ASCII PIN, so the only
realistic failure is a stale ``vault.bin`` appearing on disk between
the existence-check at boot and the create call here. In that case
we surface a red modal and return ``None``; the caller should treat
this as a fatal boot error so the operator can investigate.
"""

from __future__ import annotations

import time
from pathlib import Path

from piwallet.core.vault import Vault, VaultError
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import COLOR_DANGER, COLOR_OK, Display, FrameBuffer
from piwallet.ui.input import InputManager
from piwallet.ui.pin_setup import PinSetupScreen
from piwallet.ui.widgets import Modal


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


def run_vault_setup(
    display: Display,
    input_mgr: InputManager,
    vault_path: Path,
    *,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
    welcome_hold_seconds: float = 2.0,
    saved_hold_seconds: float = 1.5,
) -> tuple[Vault, str] | None:
    """Run the first-boot vault initialisation flow.

    Returns ``(vault, pin)`` after the vault has been created and
    persisted, or ``None`` if vault creation itself failed (a rare
    on-disk race). The caller should treat ``None`` as a fatal boot
    error and surface it to the operator.

    Side effects
    ------------
    * Creates ``vault_path`` on disk if PIN setup succeeds.
    * Renders three transient modals: a welcome banner, a "Saved"
      success banner, and (on failure) a red error modal.
    """
    _show_message(
        display,
        title="Welcome",
        body=(
            "Set a 6-digit PIN to encrypt the vault."
        ),
        accent=COLOR_OK,
    )
    time.sleep(welcome_hold_seconds)

    setup = PinSetupScreen(
        prompt="Choose vault PIN",
        confirm_prompt="Confirm vault PIN",
        cancellable=False,
    )
    run_screen(display, input_mgr, setup, target_fps=target_fps, idle_wake=idle_wake)
    pin = setup.result
    # PinSetupScreen with cancellable=False only completes via
    # matching double-confirm, but the outer run_screen could in
    # principle end via an idle-blank cycle that returns no result.
    # We retry until a PIN is captured rather than crash.
    while not setup.done or pin is None:
        setup = PinSetupScreen(
            prompt="Choose vault PIN",
            confirm_prompt="Confirm vault PIN",
            cancellable=False,
        )
        run_screen(
            display, input_mgr, setup, target_fps=target_fps, idle_wake=idle_wake
        )
        pin = setup.result

    vault = Vault(vault_path)
    try:
        vault.create(pin=pin)
    except VaultError as exc:
        _show_message(
            display,
            title="Setup failed",
            body=str(exc)[:96],
            accent=COLOR_DANGER,
        )
        time.sleep(welcome_hold_seconds)
        return None

    _show_message(
        display,
        title="Vault ready",
        body="PIN saved. Add a wallet from the next screen.",
        accent=COLOR_OK,
    )
    time.sleep(saved_hold_seconds)
    return vault, pin
