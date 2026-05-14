"""Synthetic-but-cryptographically-valid fixtures for verify/sign tests.

We build a small "blockchain" entirely in-process:

- a funding tx that pays to our wallet's ``m/44'/236'/0'/0/0``
- a 2-leaf BUMP Merkle path for that funding tx
- a synthetic header chain that starts at the network's firmware
  checkpoint, embeds the BUMP-derived Merkle root in the funding
  block's header, and extends far enough past the funding height to
  satisfy :data:`piwallet.core.verify.MIN_CONFIRMATION_DEPTH`
- an ``unsigned_proposal`` envelope that wraps everything and pays
  one external address + one change output back to ``m/44'/236'/0'/1/0``

These are not real transactions on chain, but they pass every check
our on-device ``verify_proposal()`` makes. That is what we want from
a unit-test fixture: full structural and cryptographic validity (PoW
included) without any RPC.

Run from the repo root with the venv activated::

    python -m tests.fixtures.generate_fixtures
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bsv import P2PKH, MerklePath, Transaction
from bsv.transaction_input import TransactionInput
from bsv.transaction_output import TransactionOutput

from piwallet.core import checkpoints as cp
from piwallet.core import derivation as deriv
from piwallet.core import envelope as env
from piwallet.core import headers as hdr
from piwallet.core import mnemonic as mnem
from piwallet.core import verify as vfy

CANONICAL_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon about"
)

FIXTURE_DIR = Path(__file__).parent
PROPOSAL_PATH = FIXTURE_DIR / "proposal_01.cbor"
META_PATH = FIXTURE_DIR / "proposal_01.json"


_EASY_TARGET_BITS: int = 0x207FFFFF
"""Maximum representable compact target. About half of all hashes
satisfy it, so a deterministic nonce search of a few iterations
suffices to forge a "valid" PoW for a synthetic header. This is the
same easy-target value tests/test_headers.py uses, kept in sync so
fixture-built headers exercise the real verify_chain comparison
path without slowing test runs."""


def _double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _mine_header(
    *,
    prev_hash: bytes,
    merkle_root: bytes,
    time: int,
) -> bytes:
    """Construct an 80-byte header that satisfies the easy PoW target.

    Searches deterministic nonces starting at zero. The synthetic
    ``time`` and ``prev_hash`` values keep each fixture header's
    hash domain disjoint, so chain-walking tests that depend on
    exact bytes stay reproducible across machines.
    """
    target = hdr.bits_to_target(_EASY_TARGET_BITS)
    base = (
        (1).to_bytes(4, "little")
        + prev_hash
        + merkle_root
        + time.to_bytes(4, "little")
        + _EASY_TARGET_BITS.to_bytes(4, "little")
    )
    for nonce in range(1 << 16):
        candidate = base + nonce.to_bytes(4, "little")
        digest = _double_sha256(candidate)
        if int.from_bytes(digest, "little") <= target:
            return candidate
    raise AssertionError("synthetic header search exhausted 65k nonces")


def build_proposal_01(*, network: deriv.Network = "main") -> tuple[bytes, dict]:
    """Build the canonical fixture and return (cbor_blob, metadata_json).

    ``network`` selects whether the prevout + change addresses are
    encoded as BSV mainnet (``"main"``, default — backwards-compatible
    with the original fixture) or BSV testnet (``"test"``). Verification
    paths that don't match the proposal's network must fail at the
    change-script equality check.
    """
    seed = mnem.seed_from_mnemonic(CANONICAL_MNEMONIC)
    master = deriv.master_xprv_from_seed(seed)
    account = deriv.derive_account(master)

    # Addresses and scripts we need.
    receive_address = deriv.derive_address(
        account.xpub, deriv.CHANGE_RECEIVE, 0, network=network
    )
    change_address = deriv.derive_address(
        account.xpub, deriv.CHANGE_INTERNAL, 0, network=network
    )
    funding_script = P2PKH().lock(receive_address)

    # ----- funding tx: pays 50_000 sats to our /0/0 address -----------------
    funding_amount = 50_000
    funding = Transaction(
        tx_inputs=[
            TransactionInput(
                source_txid="00" * 32,
                source_output_index=0,
                unlocking_script=None,
            )
        ],
        tx_outputs=[TransactionOutput(funding_script, funding_amount)],
        version=1,
        locktime=0,
    )
    funding_txid = funding.txid()

    # ----- fake 2-leaf merkle path ----------------------------------------
    # Sibling leaf: hash of arbitrary bytes. Its hex form (big-endian) goes
    # into the merkle path as the right-hand sibling.
    sibling_bytes = _double_sha256(b"piwallet-fixture-sibling-tx")
    sibling_hex = sibling_bytes[::-1].hex()  # display form

    # Pick a funding height just above the firmware's recent checkpoint
    # for the target network. The header chain we build below has to
    # cover heights ``[checkpoint+1, checkpoint+1+MIN_CONFIRMATION_DEPTH]``
    # so the funding input lands at confirmation depth exactly equal
    # to ``MIN_CONFIRMATION_DEPTH`` and the chain's tip equals
    # ``funding_height + (MIN_CONFIRMATION_DEPTH - 1)``.
    checkpoint = cp.for_network(network)
    checkpoint_hash_raw = bytes.fromhex(checkpoint.hash_hex)[::-1]
    funding_height = checkpoint.height + 1
    chain_len = vfy.MIN_CONFIRMATION_DEPTH  # smallest chain that meets the depth rule
    block_height = funding_height

    mp = MerklePath(
        block_height=block_height,
        path=[
            [
                {"offset": 0, "hash_str": funding_txid, "txid": True},
                {"offset": 1, "hash_str": sibling_hex},
            ]
        ],
    )
    expected_root = mp.compute_root(funding_txid)

    # Attach merkle path to the funding tx so to_beef serializes it.
    funding.merkle_path = mp

    # Build the synthetic header chain:
    #   headers[0] == funding block (carries `expected_root` as its merkle root)
    #   headers[1..MIN_DEPTH-1] == burying blocks (arbitrary roots, link forward)
    headers: list[bytes] = []
    prev_hash = checkpoint_hash_raw
    funding_root_bytes = bytes.fromhex(expected_root)[::-1]
    for offset in range(chain_len):
        if offset == 0:
            merkle_root = funding_root_bytes
        else:
            # Arbitrary roots for the burying blocks; only their PoW +
            # linkage matters because no input references their height.
            merkle_root = hashlib.sha256(
                b"piwallet-fixture-burying-block:" + offset.to_bytes(2, "big")
            ).digest()
        h = _mine_header(prev_hash=prev_hash, merkle_root=merkle_root, time=offset + 1)
        headers.append(h)
        prev_hash = _double_sha256(h)

    # ----- spending (proposal) tx -----------------------------------------
    # We don't actually serialize this through bsv-sdk; we just describe it
    # via the envelope. For BEEF transport, we wrap the funding tx as a
    # standalone BEEF (top-level == funding) so verify_proposal's
    # `_resolve_prior` finds it via the txid match.
    beef_blob = funding.to_beef()

    pay_amount = 30_000
    fee = 500
    change_amount = funding_amount - pay_amount - fee  # 19_500
    # Arbitrary valid external address (one of the canonical BIP39
    # zero-entropy mnemonic's m/44'/236'/0'/0/2 addresses; we just
    # want a non-self target). Pick the matching network's encoding so
    # the script bytes parse correctly under that network's nodes.
    pay_address = deriv.derive_address(
        account.xpub, deriv.CHANGE_RECEIVE, 2, network=network
    )
    pay_script = P2PKH().lock(pay_address)
    change_script = P2PKH().lock(change_address)

    proposal = env.UnsignedProposal(
        wallet_fp=account.fingerprint,
        inputs=(
            env.ProposalInput(
                txid=funding_txid,
                vout=0,
                sats=funding_amount,
                beef=beef_blob,
                derivation=(0, 0),
            ),
        ),
        outputs=(
            env.ProposalOutput(script_hex=pay_script.hex(), sats=pay_amount),
            env.ProposalOutput(script_hex=change_script.hex(), sats=change_amount),
        ),
        change_index=1,
        change_derivation=(1, 0),
        fee_rate_satskb=500,
        locktime=0,
        checkpoint_height=checkpoint.height,
        headers=tuple(headers),
    )

    blob = env.encode(proposal)
    meta = {
        "mnemonic": CANONICAL_MNEMONIC,
        "account_xpub": str(account.xpub),
        "wallet_fingerprint_hex": account.fingerprint.hex(),
        "funding_txid": funding_txid,
        "funding_amount_sats": funding_amount,
        "pay_address": pay_address,
        "pay_amount_sats": pay_amount,
        "change_address": change_address,
        "change_amount_sats": change_amount,
        "fee_sats": fee,
        "block_height": block_height,
        "merkle_root_hex": expected_root,
        "checkpoint_network": network,
        "checkpoint_height": checkpoint.height,
        "checkpoint_hash_hex": checkpoint.hash_hex,
        "chain_length": len(headers),
        "tip_height": checkpoint.height + len(headers),
        "envelope_path": str(PROPOSAL_PATH.relative_to(FIXTURE_DIR.parent)),
        "envelope_size_bytes": len(blob),
    }
    return blob, meta


def main() -> None:
    blob, meta = build_proposal_01()
    PROPOSAL_PATH.write_bytes(blob)
    META_PATH.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {PROPOSAL_PATH}  ({len(blob)} bytes)")
    print(f"wrote {META_PATH}")


if __name__ == "__main__":
    main()
