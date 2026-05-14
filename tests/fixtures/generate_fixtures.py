"""Synthetic-but-cryptographically-valid fixtures for verify/sign tests.

We build a tiny "blockchain" entirely in-process:

- a funding tx that pays to our wallet's ``m/44'/236'/0'/0/0``
- a 2-leaf BUMP Merkle path for that funding tx
- a single ``height -> merkle_root`` anchor (just one entry, since
  there's a single input in this fixture and therefore a single
  block to anchor)
- an ``unsigned_proposal`` envelope that wraps everything and pays
  one external address + one change output back to ``m/44'/236'/0'/1/0``

These are not real transactions on chain, but they pass every check
``verify_proposal()`` makes. That is exactly what we want from a
unit-test fixture: full structural and BUMP-internal cryptographic
validity without any RPC.

Run from the repo root with the venv activated::

    python -m tests.fixtures.generate_fixtures
"""

from __future__ import annotations

import json
from pathlib import Path

from bsv import P2PKH, MerklePath, Transaction
from bsv.transaction_input import TransactionInput
from bsv.transaction_output import TransactionOutput

from piwallet.core import derivation as deriv
from piwallet.core import envelope as env
from piwallet.core import mnemonic as mnem

CANONICAL_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon about"
)

FIXTURE_DIR = Path(__file__).parent
PROPOSAL_PATH = FIXTURE_DIR / "proposal_01.cbor"
META_PATH = FIXTURE_DIR / "proposal_01.json"

# Arbitrary realistic-ish block heights. The exact values don't matter
# for verification — verify_proposal only checks that an anchor exists
# at the BUMP's claimed height — but pinning them in the fixture
# stabilises decoded-form snapshots for tests/test_decoded_envelope_fixture.
_FIXTURE_BLOCK_HEIGHT_MAIN: int = 850_000
_FIXTURE_BLOCK_HEIGHT_TEST: int = 1_700_000


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
    import hashlib

    sibling_bytes = hashlib.sha256(
        hashlib.sha256(b"piwallet-fixture-sibling-tx").digest()
    ).digest()
    sibling_hex = sibling_bytes[::-1].hex()  # display form

    block_height = (
        _FIXTURE_BLOCK_HEIGHT_MAIN
        if network == "main"
        else _FIXTURE_BLOCK_HEIGHT_TEST
    )

    mp = MerklePath(
        block_height=block_height,
        path=[
            [
                {"offset": 0, "hash_str": funding_txid, "txid": True},
                {"offset": 1, "hash_str": sibling_hex},
            ]
        ],
    )
    # The merkle root the BUMP path computes; the anchor map below
    # publishes this same value at ``block_height`` so verification
    # passes.
    expected_root = mp.compute_root(funding_txid)
    anchor_root_bytes = bytes.fromhex(expected_root)[::-1]  # raw byte order

    # Attach merkle path to the funding tx so to_beef serializes it.
    funding.merkle_path = mp

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
        header_anchors={block_height: anchor_root_bytes},
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
        "network": network,
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
