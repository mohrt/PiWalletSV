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


def test_pairing_pw1_lines_default_chunk_keeps_qr_low_density(
    vault_pin_wallet: tuple,
) -> None:
    """Default chunk size produces multiple low-density frames.

    Regression history:

    * 720 chars/frame produced a single ~v25 QR at ~1.5 px/module —
      phones could not autofocus through the TFT glow.
    * 240 chars/frame produced 2 frames at v8 / 3 px/module — still
      sat at the edge of arm's-length scanning during the
      hardware checkpoint #3 round-trip on 2026-05-13.
    * **120 chars/frame** (current) produces 2-4 frames at v6 /
      ~4 px/module on the new ~196 px QR area, comfortably above
      phone-scanner minimums.

    Keep each frame under ~140 chars (120 fragment + ~10-char PW1
    header) so the default doesn't silently drift back into the
    too-dense regime.
    """
    vault, pin, rec = vault_pin_wallet
    lines = pairing_pw1_lines(vault, pin, rec)
    assert all(len(line) <= 140 for line in lines), (
        f"PW1 frame exceeded 140-char ceiling: {[len(line) for line in lines]}"
    )
    blob = join_multipart_lines(lines)
    assert isinstance(env.decode(blob), env.XpubExport)


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


def test_offer_companion_pairing_short_b_press_also_skips() -> None:
    """Short tap of B is treated as decline so B is universally 'back'."""
    s = OfferCompanionPairingScreen("x")
    s.on_event(Event(button=Button.B, kind=EventKind.PRESS, at_ms=0))
    assert s.done and s.result is False
