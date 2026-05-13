"""Companion pairing PW1 lines and offer screen."""

from __future__ import annotations

from pathlib import Path

import pytest

from piwallet.bonnet.companion_pairing import OfferCompanionPairingScreen, pairing_pw1_lines
from piwallet.core import envelope as env
from piwallet.core import mnemonic as mnem
from piwallet.core.vault import Vault, WalletRecord
from piwallet.qr.multipart import join_multipart_lines
from piwallet.ui.display import FrameBuffer
from piwallet.ui.input import Button, Event, EventKind


@pytest.fixture()
def vault_pin_wallet(tmp_path: Path) -> tuple[Vault, str, WalletRecord]:
    path = tmp_path / "v.bin"
    v = Vault(path)
    v.create(pin="123456")
    rec = v.add_wallet("123456", mnem.generate(12), label="paired-test")
    return v, "123456", rec


def test_pairing_pw1_lines_join_decode_roundtrip(vault_pin_wallet: tuple) -> None:
    vault, pin, rec = vault_pin_wallet
    lines = pairing_pw1_lines(vault, pin, rec)
    assert len(lines) >= 1
    blob = join_multipart_lines(lines)
    got = env.decode(blob)
    assert isinstance(got, env.XpubExport)
    assert got.path == rec.derivation_path
    assert got.fingerprint == rec.fingerprint
    assert got.label == (rec.label or "wallet")
    xpub_expected = vault.get_account_xpub(pin, rec.id)
    assert got.xpub == xpub_expected


def test_offer_companion_pairing_screen_confirms_true() -> None:
    s = OfferCompanionPairingScreen("my wallet")
    fb = FrameBuffer()
    s.draw(fb)
    s.on_event(Event(button=Button.A, kind=EventKind.PRESS, at_ms=0))
    assert s.done and s.result is True


def test_offer_companion_pairing_long_b_skips() -> None:
    s = OfferCompanionPairingScreen("x")
    s.on_event(Event(button=Button.B, kind=EventKind.LONG, at_ms=0))
    assert s.done and s.result is False
