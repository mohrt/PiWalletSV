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
    chunk_chars: int = 240,
) -> list[str]:
    """Return PW1 multipart lines for the gzip+CBOR ``xpub_export`` envelope.

    The wallet's network is stamped into the envelope so the companion
    can route the paired wallet to the correct base58check prefix and
    WhatsOnChain endpoint.

    ``chunk_chars`` is deliberately small (240) so each rendered QR
    stays at a low module count even on the bonnet's 240x240 panel:
    at 720 chars the encoded payload pushed the QR to version ~25
    with each module ~1.5 px wide, which sat right at the edge of
    what a phone camera can autofocus and decode at arm's length.
    240 chars puts each frame around version 10 (~57 modules square,
    ~3 px per module at the 176 px QR target) and the multipart
    animation cycles through 2-4 frames so the scanner has multiple
    decode attempts per envelope.
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
                ListItem(label="Not now", value=False),
            ],
        )

    def on_event(self, event: Event) -> None:
        if self.done:
            return
        if event.button == Button.B and event.kind == EventKind.LONG:
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
