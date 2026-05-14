"""Tests for piwallet.core.atomic_beef (BRC-95 Atomic BEEF codec)."""

from __future__ import annotations

import pytest

from piwallet.core import atomic_beef as ab
from tests.fixtures.generate_fixtures import build_proposal_01

from bsv import Transaction


def _signed_tx_from_fixture() -> Transaction:
    """Build a real signed-ish transaction from the canonical fixture.

    Re-uses the verify/sign machinery so the test exercises the same
    ``Transaction`` shape (with ``source_transaction`` references and
    attached merkle paths on ancestors) the production sign path
    produces. Avoids the brittleness of a hand-rolled BEEF blob.
    """
    from functools import partial

    from piwallet.core import derivation as deriv
    from piwallet.core import envelope as env
    from piwallet.core import mnemonic as mnem
    from piwallet.core import sign as sgn

    blob, _meta = build_proposal_01()
    proposal = env.decode(blob)
    assert isinstance(proposal, env.UnsignedProposal)

    seed = mnem.seed_from_mnemonic(
        "abandon abandon abandon abandon abandon abandon abandon abandon "
        "abandon abandon abandon about"
    )
    master = deriv.master_xprv_from_seed(seed)
    account = deriv.derive_account(master)
    derive_key = partial(deriv.derive_signing_key, account.xprv)
    result = sgn.verify_then_sign(proposal, str(account.xpub), derive_key)
    # `result.atomic_beef` was already produced by the signer; we
    # re-derive a `Transaction` here so split/encode round-trip can be
    # validated independently from `SignedResult.atomic_beef`.
    return ab.to_transaction(result.atomic_beef)


def test_encode_prefixes_magic_and_subject_txid() -> None:
    tx = _signed_tx_from_fixture()
    blob = ab.encode(tx)
    assert blob[:4] == ab.ATOMIC_BEEF_MAGIC
    # Subject TXID is on the wire in raw byte order — the displayed
    # hex form is the byte-reverse, matching how block hashes are
    # printed everywhere else in BSV tooling.
    assert blob[4:36] == bytes.fromhex(tx.txid())[::-1]


def test_split_returns_displayed_txid_hex() -> None:
    tx = _signed_tx_from_fixture()
    blob = ab.encode(tx)
    txid_hex, body = ab.split(blob)
    assert txid_hex == tx.txid()
    assert len(body) == len(blob) - ab.ATOMIC_BEEF_HEADER_LEN
    assert body == blob[ab.ATOMIC_BEEF_HEADER_LEN :]


def test_to_transaction_roundtrips_via_inner_beef() -> None:
    tx = _signed_tx_from_fixture()
    blob = ab.encode(tx)
    recovered = ab.to_transaction(blob)
    assert recovered.txid() == tx.txid()
    assert recovered.hex() == tx.hex()


def test_split_rejects_non_bytes_input() -> None:
    with pytest.raises(ab.AtomicBeefError, match="bytes"):
        ab.split("not bytes")  # type: ignore[arg-type]


def test_split_rejects_short_blob() -> None:
    with pytest.raises(ab.AtomicBeefError, match="at least"):
        ab.split(b"\x01\x01\x01\x01" + b"\x00" * 10)


def test_split_rejects_wrong_magic() -> None:
    with pytest.raises(ab.AtomicBeefError, match="magic mismatch"):
        ab.split(b"\xde\xad\xbe\xef" + b"\x00" * 32 + b"body")


def test_to_transaction_rejects_subject_txid_mismatch() -> None:
    """If the BRC-95 header declares a TXID different from the inner
    BEEF's top-level tx, ``to_transaction`` must refuse rather than
    silently returning the inner tx — the protocol contract is that
    the header pins the subject of the atomic envelope."""
    tx = _signed_tx_from_fixture()
    blob = ab.encode(tx)
    # Flip a single byte inside the subject TXID portion of the header.
    forged = bytearray(blob)
    forged[4] ^= 0xFF
    with pytest.raises(ab.AtomicBeefError, match="subject txid"):
        ab.to_transaction(bytes(forged))
