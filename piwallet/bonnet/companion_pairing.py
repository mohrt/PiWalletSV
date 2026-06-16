"""Companion watch-only pairing: xpub_export envelope as PW1 multipart QRs."""

from __future__ import annotations

from dataclasses import dataclass, field

from piwallet.core import envelope as env
from piwallet.core.vault import Vault, WalletRecord
from piwallet.qr.multipart import split_envelope_to_lines
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind
from piwallet.ui.widgets import ListItem, ListView


def pairing_pw1_lines(
    vault: Vault,
    pin: str,
    wallet: WalletRecord,
    *,
    chunk_chars: int = 100,
) -> list[str]:
    """Return PW1 multipart lines for the gzip+CBOR ``xpub_export`` envelope.

    The wallet's network is stamped into the envelope so the companion
    can route the paired wallet to the correct base58check prefix and
    WhatsOnChain endpoint.

    ``chunk_chars`` targets 100 so each frame stays within QR version 7
    (45×45 modules) when rendered with error="L".  At the ~196 px QR
    target (see :class:`PairingMultipartQrScreen`) that gives 4 px per
    module — comfortably above phone-scanner minimums through TFT glow.
    The progression that led here:

    * 720 chars → version 25, ~1.5 px/module, phones could not lock.
    * 240 chars → version 8, ~3 px/module, marginal.
    * 120 chars + error M → version 10, 3 px/module (57+4=61 bordered,
      floor(200/61)=3), still marginal for signed-tx scanning.
    * **100 chars + error L** (current): version 7, 4 px/module
      (45+4=49 bordered, floor(200/49)=4) — reliably scannable.
    """
    xpub_str = vault.get_account_xpub(pin, wallet.id)
    payload = env.XpubExport(
        xpub=xpub_str,
        path=wallet.derivation_path,
        label=wallet.label or "wallet",
        fingerprint=wallet.fingerprint,
        network=wallet.network,
    )
    blob = env.encode(payload)
    return split_envelope_to_lines(blob, max_encoded_chunk_chars=chunk_chars)


@dataclass
class OfferCompanionPairingScreen:
    """Prompt after wallet save: show pairing QR now or skip."""

    wallet_label_stub: str
    done: bool = False
    result: bool | None = None
    _list: ListView = field(init=False)

    def __post_init__(self) -> None:
        stub = self.wallet_label_stub.strip()[:16]
        suffix = "" if len(self.wallet_label_stub.strip()) <= 16 else "…"
        title = f'Pair "{stub}{suffix}"?'
        self._list = ListView(
            title=title,
            items=[
                ListItem(label="Show companion QR", value=True),
                ListItem(label="Skip (do later)", value=False),
            ],
        )

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        # Either short tap or long hold of B treats the prompt as a
        # decline (= "Not now"), matching the rest of the app where
        # B is always "back".
        if event.button == Button.B and event.kind in (EventKind.PRESS, EventKind.LONG):
            self.done = True
            self.result = False
            return
        self._list.on_event(event)
        picked = self._list.confirmed
        if isinstance(picked, bool):
            self.done = True
            self.result = picked

    def draw(self, fb: FrameBuffer) -> None:
        self._list.draw(fb)
