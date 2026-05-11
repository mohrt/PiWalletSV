"""End-to-end signing tests.

Uses the canonical fixture proposal: builds it, verifies it, signs it, and
runs sanity checks on the resulting transaction.
"""

from __future__ import annotations

from functools import partial

import pytest
from bsv import Transaction

from piwallet.core import derivation as deriv
from piwallet.core import envelope as env
from piwallet.core import mnemonic as mnem
from piwallet.core import sign as s
from piwallet.core import verify as v
from tests.fixtures.generate_fixtures import (
    CANONICAL_MNEMONIC,
    build_proposal_01,
)


@pytest.fixture
def fixture():
    """Returns (proposal, account_xprv, account_xpub_str)."""
    seed = mnem.seed_from_mnemonic(CANONICAL_MNEMONIC)
    master = deriv.master_xprv_from_seed(seed)
    account = deriv.derive_account(master)
    blob, _meta = build_proposal_01()
    proposal = env.decode(blob)
    assert isinstance(proposal, env.UnsignedProposal)
    return proposal, account.xprv, str(account.xpub)


def make_deriver(xprv):
    return partial(deriv.derive_signing_key, xprv)


def test_verify_then_sign_happy_path(fixture) -> None:
    proposal, xprv, xpub = fixture
    result = s.verify_then_sign(proposal, xpub, make_deriver(xprv))
    assert isinstance(result, s.SignedResult)
    assert result.raw_hex
    assert result.txid
    assert result.size > 0
    assert result.fee_sats == 500


def test_signed_tx_parses_back_to_transaction(fixture) -> None:
    proposal, xprv, xpub = fixture
    result = s.verify_then_sign(proposal, xpub, make_deriver(xprv))
    parsed = Transaction.from_hex(result.raw_hex)
    assert parsed.txid() == result.txid
    assert len(parsed.inputs) == len(proposal.inputs)
    assert len(parsed.outputs) == len(proposal.outputs)


def test_signed_tx_has_unlocking_scripts(fixture) -> None:
    proposal, xprv, xpub = fixture
    result = s.verify_then_sign(proposal, xpub, make_deriver(xprv))
    parsed = Transaction.from_hex(result.raw_hex)
    for i, inp in enumerate(parsed.inputs):
        assert inp.unlocking_script is not None
        assert len(inp.unlocking_script.serialize()) > 0, f"input {i} unsigned"


def test_signed_tx_outputs_match_proposal(fixture) -> None:
    proposal, xprv, xpub = fixture
    result = s.verify_then_sign(proposal, xpub, make_deriver(xprv))
    parsed = Transaction.from_hex(result.raw_hex)
    for i, out in enumerate(parsed.outputs):
        assert out.satoshis == proposal.outputs[i].sats
        assert out.locking_script.hex() == proposal.outputs[i].script_hex


def test_signed_tx_input_amounts_dont_inflate(fixture) -> None:
    """Belt-and-suspenders: the verified prevout sats came from the prior tx
    (50_000), not anything the proposal could lie about."""
    proposal, xprv, xpub = fixture
    result = s.verify_then_sign(proposal, xpub, make_deriver(xprv))
    assert result.verified.total_in == 50_000
    assert result.verified.total_out == 49_500
    assert result.fee_sats == 500


def test_to_signed_envelope_roundtrips(fixture) -> None:
    proposal, xprv, xpub = fixture
    result = s.verify_then_sign(proposal, xpub, make_deriver(xprv))
    seed = mnem.seed_from_mnemonic(CANONICAL_MNEMONIC)
    master = deriv.master_xprv_from_seed(seed)
    fp = deriv.derive_account(master).fingerprint
    envelope = s.to_signed_envelope(result, wallet_fp=fp)
    blob = env.encode(envelope)
    decoded = env.decode(blob)
    assert isinstance(decoded, env.SignedTx)
    assert decoded.raw_hex == result.raw_hex
    assert decoded.txid == result.txid
    assert decoded.wallet_fp == fp


def test_sign_aborts_when_verify_fails(fixture) -> None:
    """A proposal that fails verification must not produce a signature."""
    import dataclasses

    proposal, xprv, xpub = fixture
    bad_proposal = dataclasses.replace(proposal, header_anchors={})
    with pytest.raises(v.ProposalVerificationError):
        s.verify_then_sign(bad_proposal, xpub, make_deriver(xprv))


def test_sign_aborts_on_change_swap(fixture) -> None:
    """Phone tries to redirect change to its own address. Must not sign."""
    import dataclasses

    proposal, xprv, xpub = fixture
    evil = dataclasses.replace(
        proposal.outputs[1],
        script_hex="76a914" + "ff" * 20 + "88ac",
    )
    bad = dataclasses.replace(proposal, outputs=(proposal.outputs[0], evil))
    with pytest.raises(v.ProposalVerificationError):
        s.verify_then_sign(bad, xpub, make_deriver(xprv))


def test_build_signed_tx_with_explicit_verified_proposal(fixture) -> None:
    """Two-phase API: verify, then sign separately."""
    proposal, xprv, xpub = fixture
    verified = v.verify_proposal(proposal, xpub)
    result = s.build_signed_tx(verified, make_deriver(xprv))
    parsed = Transaction.from_hex(result.raw_hex)
    assert parsed.txid() == result.txid


def test_sign_with_wrong_xprv_produces_invalid_signature(fixture) -> None:
    """If the deriver returns a wrong key, the resulting tx still serializes
    but won't validate scripts. Confirm tx still produced (signing is a
    purely local op; on-chain validation is the broadcaster's problem).

    The point of this test is to lock in that we never raise on a bad key
    here -- the transaction just won't be acceptable on chain. SPV-style
    verification was upstream; signing is mechanical.
    """
    proposal, _xprv, xpub = fixture
    other = mnem.generate(12)
    other_seed = mnem.seed_from_mnemonic(other)
    other_master = deriv.master_xprv_from_seed(other_seed)
    other_account = deriv.derive_account(other_master)
    result = s.build_signed_tx(
        v.verify_proposal(proposal, xpub),
        make_deriver(other_account.xprv),
    )
    # Tx was produced, but it would fail script verification on chain.
    parsed = Transaction.from_hex(result.raw_hex)
    assert parsed.txid()
    assert len(parsed.inputs[0].unlocking_script.serialize()) > 0
