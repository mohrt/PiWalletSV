"""Tests for piwallet.core.verify.

Uses the fixture generator to build a fresh proposal in-memory each test,
which lets us mutate it cheaply to exercise every failure mode without
touching disk.
"""

from __future__ import annotations

import dataclasses

import pytest

from piwallet.core import derivation as deriv
from piwallet.core import envelope as env
from piwallet.core import mnemonic as mnem
from piwallet.core import verify as v
from tests.fixtures.generate_fixtures import (
    CANONICAL_MNEMONIC,
    build_proposal_01,
)


@pytest.fixture
def account_xpub_str() -> str:
    """Account xpub for the canonical mnemonic."""
    seed = mnem.seed_from_mnemonic(CANONICAL_MNEMONIC)
    master = deriv.master_xprv_from_seed(seed)
    return str(deriv.derive_account(master).xpub)


@pytest.fixture
def proposal() -> env.UnsignedProposal:
    blob, _meta = build_proposal_01()
    decoded = env.decode(blob)
    assert isinstance(decoded, env.UnsignedProposal)
    return decoded


# ---- happy path ----------------------------------------------------------


def test_happy_path(proposal: env.UnsignedProposal, account_xpub_str: str) -> None:
    result = v.verify_proposal(proposal, account_xpub_str)
    assert isinstance(result, v.VerifiedProposal)
    assert len(result.inputs) == 1
    assert result.inputs[0].prevout_sats == 50_000
    assert result.inputs[0].derivation == (0, 0)
    assert result.change_index == 1
    assert result.change_derivation == (1, 0)
    assert result.fee_sats == 500


def test_returns_real_prevout_values_not_claimed(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    result = v.verify_proposal(proposal, account_xpub_str)
    # The verified prevout sats came from the prior tx, not the proposal claim.
    assert result.inputs[0].prevout_sats == 50_000


# ---- header anchor failures --------------------------------------------


def test_missing_anchors(proposal: env.UnsignedProposal, account_xpub_str: str) -> None:
    bad = dataclasses.replace(proposal, header_anchors={})
    with pytest.raises(v.ProposalVerificationError, match="anchor"):
        v.verify_proposal(bad, account_xpub_str)


def test_anchor_root_mismatch(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    h, _ = next(iter(proposal.header_anchors.items()))
    bad = dataclasses.replace(proposal, header_anchors={h: bytes(32)})
    with pytest.raises(v.ProposalVerificationError, match="merkle root mismatch"):
        v.verify_proposal(bad, account_xpub_str)


def test_anchor_at_wrong_height(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    _, root = next(iter(proposal.header_anchors.items()))
    bad = dataclasses.replace(proposal, header_anchors={999_999: root})
    with pytest.raises(v.ProposalVerificationError, match="merkle root mismatch"):
        v.verify_proposal(bad, account_xpub_str)


# ---- input-level failures -----------------------------------------------


def test_corrupted_beef(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    # Truncate the BEEF for the first input.
    bad_input = dataclasses.replace(proposal.inputs[0], beef=b"\xde\xad\xbe\xef")
    bad = dataclasses.replace(proposal, inputs=(bad_input,))
    with pytest.raises(v.ProposalVerificationError, match="BEEF"):
        v.verify_proposal(bad, account_xpub_str)


def test_input_sats_lie(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    """If the proposal claims input.sats != actual prevout.sats, reject."""
    bad_input = dataclasses.replace(proposal.inputs[0], sats=99_999_999)
    bad = dataclasses.replace(proposal, inputs=(bad_input,))
    with pytest.raises(v.ProposalVerificationError, match="sats mismatch"):
        v.verify_proposal(bad, account_xpub_str)


def test_input_wrong_derivation(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    """If the proposal claims a derivation that doesn't match the prior script, reject."""
    bad_input = dataclasses.replace(proposal.inputs[0], derivation=(0, 5))
    bad = dataclasses.replace(proposal, inputs=(bad_input,))
    with pytest.raises(v.ProposalVerificationError, match="derivation"):
        v.verify_proposal(bad, account_xpub_str)


def test_input_vout_out_of_range(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    bad_input = dataclasses.replace(proposal.inputs[0], vout=99)
    bad = dataclasses.replace(proposal, inputs=(bad_input,))
    with pytest.raises(v.ProposalVerificationError, match="vout"):
        v.verify_proposal(bad, account_xpub_str)


# ---- change output verification -----------------------------------------


def test_change_script_doesnt_match_derivation(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    """A malicious phone could swap the change script to its own. Catch it."""
    bad_change = dataclasses.replace(
        proposal.outputs[1],
        script_hex="76a914" + "ff" * 20 + "88ac",
    )
    bad_outputs = (proposal.outputs[0], bad_change)
    bad = dataclasses.replace(proposal, outputs=bad_outputs)
    with pytest.raises(v.ProposalVerificationError, match="change output"):
        v.verify_proposal(bad, account_xpub_str)


def test_change_derivation_mismatch(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    """If the proposal lies about the change derivation index, reject."""
    bad = dataclasses.replace(proposal, change_derivation=(1, 99))
    with pytest.raises(v.ProposalVerificationError, match="change output"):
        v.verify_proposal(bad, account_xpub_str)


# ---- fee / value sanity --------------------------------------------------


def test_outputs_exceed_inputs_rejected(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    huge_change = dataclasses.replace(proposal.outputs[1], sats=10_000_000)
    bad = dataclasses.replace(
        proposal, outputs=(proposal.outputs[0], huge_change)
    )
    # Need to also re-derive the change script so the value-check fires
    # (otherwise the change-script-mismatch fires first).
    # Simpler: also bump the recv output.
    big_recv = dataclasses.replace(proposal.outputs[0], sats=999_999)
    bad = dataclasses.replace(
        proposal, outputs=(big_recv, proposal.outputs[1])
    )
    with pytest.raises(v.ProposalVerificationError, match="exceed"):
        v.verify_proposal(bad, account_xpub_str)


def test_fee_rate_cap_enforced(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    with pytest.raises(v.ProposalVerificationError, match="fee rate"):
        v.verify_proposal(
            proposal, account_xpub_str, max_fee_rate_satskb=10
        )


def test_fee_rate_cap_at_or_above_passes(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    result = v.verify_proposal(
        proposal, account_xpub_str, max_fee_rate_satskb=10_000
    )
    assert result.fee_sats == 500


# ---- network kwarg plumbing ----------------------------------------------
#
# Note: P2PKH scripts are network-invariant at the bytes level — the
# HASH160 payload is the same for both networks, only the rendered
# base58check address string differs. So the network kwarg on
# verify_proposal does NOT gate verification. These tests cover the
# pieces that DO need network awareness: positive testnet verification,
# default-network preservation, and the script_address_or_none helper.


@pytest.fixture
def testnet_proposal() -> env.UnsignedProposal:
    blob, _meta = build_proposal_01(network="test")
    decoded = env.decode(blob)
    assert isinstance(decoded, env.UnsignedProposal)
    return decoded


def test_testnet_proposal_verifies_under_testnet(
    testnet_proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    """A testnet proposal must verify when the wallet is configured for testnet."""
    result = v.verify_proposal(testnet_proposal, account_xpub_str, network="test")
    assert result.inputs[0].derivation == (0, 0)
    assert result.fee_sats == 500


def test_default_network_is_main(
    proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    """Calling verify_proposal without a network kwarg keeps mainnet behaviour."""
    result = v.verify_proposal(proposal, account_xpub_str)
    assert result.fee_sats == 500


def test_p2pkh_script_invariance_across_networks(
    testnet_proposal: env.UnsignedProposal, account_xpub_str: str
) -> None:
    """A testnet proposal verifies even under network='main' because P2PKH
    scripts are bytes-identical across networks for the same key. Lock this
    invariant in so a future contributor doesn't accidentally weaken the
    network kwarg into a false safety claim.
    """
    # Both calls succeed; the rendered addresses in any error message
    # would differ but the verification result itself is the same.
    main_result = v.verify_proposal(testnet_proposal, account_xpub_str, network="main")
    test_result = v.verify_proposal(testnet_proposal, account_xpub_str, network="test")
    assert main_result.fee_sats == test_result.fee_sats


def test_script_address_or_none_renders_for_network() -> None:
    """script_address_or_none uses the network's base58check prefix."""
    h160_bytes = b"\x00" * 20
    h160_list = list(h160_bytes)
    from bsv import P2PKH as _P2PKH
    from bsv import to_base58_check
    from bsv.constants import ADDRESS_MAINNET_PREFIX, ADDRESS_TESTNET_PREFIX

    main_addr = to_base58_check(h160_list, prefix=list(ADDRESS_MAINNET_PREFIX))
    test_addr = to_base58_check(h160_list, prefix=list(ADDRESS_TESTNET_PREFIX))
    script_hex = _P2PKH().lock(main_addr).hex()

    assert v.script_address_or_none(script_hex) == main_addr
    assert v.script_address_or_none(script_hex, network="main") == main_addr
    assert v.script_address_or_none(script_hex, network="test") == test_addr


# ---- offline chain tracker -----------------------------------------------


def test_offline_chain_tracker_recognizes_anchor() -> None:
    import asyncio

    tracker = v.OfflineChainTracker({812345: "abcdef" * 10})
    assert asyncio.run(tracker.is_valid_root_for_height("abcdef" * 10, 812345))
    assert not asyncio.run(tracker.is_valid_root_for_height("00" * 32, 812345))
    assert not asyncio.run(tracker.is_valid_root_for_height("abcdef" * 10, 999_999))


def test_offline_chain_tracker_case_insensitive() -> None:
    import asyncio

    tracker = v.OfflineChainTracker({1: "ABCDEF"})
    assert asyncio.run(tracker.is_valid_root_for_height("abcdef", 1))
