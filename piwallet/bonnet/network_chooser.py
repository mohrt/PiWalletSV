"""Network chooser screen for the wallet-create flow.

Runs *before* the HD path chooser so the operator picks the
target network — BSV mainnet (the safe default) or BSV testnet
(TBSV, free coins, no real value) — at the moment they create a
wallet. The choice is stored on the wallet record and threaded
through every subsequent address-rendering / WoC / sign path.

Returns:

- ``"main"``  — operator confirmed the mainnet preset.
- ``"test"``  — operator confirmed the testnet option.
- ``None``    — operator pressed B (back) or held B (exit) to
  cancel and abort the create flow.

The screen uses the same :class:`ListView` widget the HD path and
entropy-source choosers use, so the UX stays consistent. A short
help blurb at the bottom reminds the operator that testnet wallets
hold no real BSV.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from piwallet.core.derivation import Network
from piwallet.ui.app import IdleWakeTracker, run_screen
from piwallet.ui.display import (
    COLOR_DIM,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    Display,
    FrameBuffer,
)
from piwallet.ui.input import Button, Event, EventKind, InputManager
from piwallet.ui.widgets import ListItem, ListView, draw_text


@dataclass
class NetworkChooserScreen:
    """Pick BSV mainnet vs testnet for a new wallet.

    Output is exposed via :attr:`result`:

    - ``"main"`` / ``"test"``: operator picked + confirmed.
    - ``None``: operator backed out (``B`` press or long-press) —
      caller treats this as a cancellation of the whole create flow.

    A long-press of ``B`` requests app exit; this is signalled to
    the caller via :attr:`exit_requested` so the create-wallet
    driver can propagate it back to the bonnet boot loop.
    """

    title: str = "Network"
    done: bool = False
    result: Network | None = None
    exit_requested: bool = False
    _list: ListView = field(init=False)

    def __post_init__(self) -> None:
        self._list = ListView(
            title=self.title,
            items=[
                ListItem(
                    label="Mainnet (real BSV)",
                    value="main",
                ),
                ListItem(
                    label="Testnet (TBSV)",
                    value="test",
                ),
            ],
        )

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if event.button == Button.B:
            if event.kind == EventKind.LONG:
                self.done = True
                self.exit_requested = True
                self.result = None
                return
            if event.kind == EventKind.PRESS:
                self.done = True
                self.result = None
                return
        self._list.on_event(event)
        chosen = self._list.confirmed
        if chosen in ("main", "test"):
            self.done = True
            self.result = chosen  # type: ignore[assignment]

    def draw(self, fb: FrameBuffer) -> None:
        self._list.draw(fb)
        # Footer hint: emphasise that testnet has no real value so
        # operators don't accidentally confuse the two for receive
        # addresses they'll be sharing.
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 22,
            "A confirm   B back",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )
        draw_text(
            fb,
            DISPLAY_WIDTH // 2,
            DISPLAY_HEIGHT - 10,
            "Testnet has no real value",
            size=10,
            color=COLOR_DIM,
            anchor="mm",
        )


def run_network_chooser(
    display: Display,
    input_mgr: InputManager,
    *,
    target_fps: int = 30,
    idle_wake: IdleWakeTracker | None = None,
    run_screen_fn: Callable[..., Any] = run_screen,
) -> Network | None:
    """Drive :class:`NetworkChooserScreen` until the operator picks or backs out.

    Returns the chosen :data:`piwallet.core.derivation.Network` or
    ``None`` if the operator backed out (B press) or requested app
    exit (B long-press). The caller distinguishes these two cases
    via :attr:`NetworkChooserScreen.exit_requested` if needed; for
    the wallet-create flow both outcomes mean "abort".

    ``run_screen_fn`` exists for tests to bypass the real frame loop;
    production callers leave it at the default. Mirrors the same
    injection knob :func:`piwallet.bonnet.hd_path_chooser.run_hd_path_chooser`
    exposes.
    """
    screen = NetworkChooserScreen()
    run_screen_fn(
        display,
        input_mgr,
        screen,
        target_fps=target_fps,
        idle_wake=idle_wake,
    )
    return screen.result
