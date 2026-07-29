"""Authoritative wallet-state persistence and migration tests."""

from __future__ import annotations

import dataclasses
import stat
from functools import partial

import cbor2
import pytest
from bsv import Transaction

from piwallet.core import atomic_beef, verify
from piwallet.core import envelope as env
from piwallet.core import sign as signing
from piwallet.core.state import (
    ZERO_STATE_HASH,
    WalletStateError,
    WalletStateStore,
    outpoint,
)
from piwallet.core.vault import Vault
from tests.fixtures.generate_fixtures import CANONICAL_MNEMONIC, build_proposal_01

PIN = "123456"


def _wallet(tmp_path, name: str = "device", pin: str = PIN):
    device_dir = tmp_path / name
    device_dir.mkdir()
    vault = Vault(device_dir / "vault.bin")
    vault.create(pin)
    wallet = vault.add_wallet(pin, CANONICAL_MNEMONIC, "state test")
    key = vault.derive_state_key(pin, wallet.id)
    xpub = vault.get_account_xpub(pin, wallet.id)
    proposal_blob, metadata = build_proposal_01()
    proposal = env.decode(proposal_blob)
    assert isinstance(proposal, env.UnsignedProposal)
    return vault, wallet, key, xpub, proposal, metadata


def _sync_from_proposal(
    wallet, proposal: env.UnsignedProposal, metadata: dict, *, request_id: str = "sync-1"
) -> env.StateSync:
    funding = Transaction.from_beef(proposal.inputs[0].beef)
    output = funding.outputs[proposal.inputs[0].vout]
    coin = env.StateCoin(
        txid=proposal.inputs[0].txid,
        vout=proposal.inputs[0].vout,
        sats=int(output.satoshis),
        locking_script=output.locking_script.hex(),
        derivation=proposal.inputs[0].derivation,
        status="confirmed",
        transaction_reference=proposal.inputs[0].txid,
        block_height=metadata["block_height"],
    )
    return env.StateSync(
        wallet_fp=wallet.fingerprint,
        request_id=request_id,
        expected_revision=0,
        expected_state_hash=ZERO_STATE_HASH,
        next_receive_index=1,
        next_change_index=0,
        coins=(env.StateSyncCoin(coin=coin, atomic_beef=atomic_beef.encode(funding)),),
        header_anchors=proposal.header_anchors,
    )


def test_state_key_survives_new_pin_and_wallet_uuid(tmp_path) -> None:
    first, first_wallet, first_key, *_ = _wallet(tmp_path, "first", "123456")
    second, second_wallet, second_key, *_ = _wallet(tmp_path, "second", "654321")

    assert first_wallet.id != second_wallet.id
    assert first_key == second_key
    first.close()
    second.close()


def test_state_file_is_encrypted_authenticated_and_tamper_evident(tmp_path) -> None:
    _vault, wallet, key, _xpub, proposal, metadata = _wallet(tmp_path)
    store = WalletStateStore(tmp_path / "device" / "state.bin")
    sync = _sync_from_proposal(wallet, proposal, metadata)
    state, _receipt = store.apply_sync(wallet, key, sync, _xpub)

    raw = store.path.read_bytes()
    assert proposal.inputs[0].txid.encode() not in raw
    assert state.total_sats == 50_000
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600

    outer = cbor2.loads(raw)
    entry = next(iter(outer["wallets"].values()))
    ciphertext = bytearray(entry["ciphertext"])
    ciphertext[-1] ^= 1
    entry["ciphertext"] = bytes(ciphertext)
    store.path.write_bytes(cbor2.dumps(outer, canonical=True))
    with pytest.raises(WalletStateError, match="authentication failed"):
        store.load(wallet, key)


def test_authenticated_but_internally_inconsistent_journal_is_rejected(tmp_path) -> None:
    _vault, wallet, key, xpub, proposal, metadata = _wallet(tmp_path)
    store = WalletStateStore(tmp_path / "device" / "state.bin")
    state, _ = store.apply_sync(
        wallet,
        key,
        _sync_from_proposal(wallet, proposal, metadata),
        xpub,
    )
    state.transaction_journal[0]["resultHash"] = b"\x00" * 32
    store.save(wallet, key, state)

    with pytest.raises(WalletStateError, match="latest journal result"):
        store.load(wallet, key)


def test_confirmed_atomic_beef_sync_is_verified_committed_and_idempotent(tmp_path) -> None:
    _vault, wallet, key, xpub, proposal, metadata = _wallet(tmp_path)
    store = WalletStateStore(tmp_path / "device" / "state.bin")
    sync = _sync_from_proposal(wallet, proposal, metadata)

    state, receipt = store.apply_sync(wallet, key, sync, xpub)
    coin_key = outpoint(proposal.inputs[0].txid, 0)
    assert state.revision == 1
    assert state.next_receive_index == 1
    assert state.coins[coin_key].sats == 50_000
    assert receipt.old_revision == 0
    assert receipt.new_revision == 1
    assert receipt.new_state_hash == state.state_hash()

    replayed, replay_receipt = store.apply_sync(wallet, key, sync, xpub)
    assert replayed.revision == 1
    assert replay_receipt == receipt


def test_state_envelopes_and_nested_signed_receipt_round_trip(tmp_path) -> None:
    vault, wallet, key, xpub, proposal, metadata = _wallet(tmp_path)
    sync = _sync_from_proposal(wallet, proposal, metadata)
    decoded_sync = env.decode(env.encode(sync))
    assert decoded_sync == sync

    store = WalletStateStore(tmp_path / "device" / "state.bin")
    synced, _ = store.apply_sync(wallet, key, sync, xpub)
    bound = dataclasses.replace(
        proposal,
        state_revision=synced.revision,
        state_hash=synced.state_hash(),
        proposal_id="roundtrip-spend",
    )
    verified = verify.verify_proposal(bound, xpub)
    signed = signing.build_signed_tx(
        verified,
        partial(vault.derive_signing_key, PIN, wallet.id),
    )
    _updated, receipt = store.commit_signed(wallet, key, bound, verified, signed.atomic_beef)
    response = signing.to_signed_envelope(signed, wallet.fingerprint, state_receipt=receipt)
    assert env.decode(env.encode(response)) == response


def test_state_bound_proposal_requires_complete_binding_and_id(tmp_path) -> None:
    _vault, _wallet_rec, _key, _xpub, proposal, _metadata = _wallet(tmp_path)
    body = proposal.to_cbor()
    body["stateRevision"] = 0
    body["stateHash"] = b"\x00" * 32
    with pytest.raises(env.EnvelopeError, match="proposalId"):
        env.UnsignedProposal.from_cbor(body)

    body["proposalId"] = "proposal-complete"
    del body["stateHash"]
    with pytest.raises(env.EnvelopeError, match="supplied together"):
        env.UnsignedProposal.from_cbor(body)


def test_sync_rejects_unowned_output_bad_anchor_and_stale_state(tmp_path) -> None:
    _vault, wallet, key, xpub, proposal, metadata = _wallet(tmp_path)
    store = WalletStateStore(tmp_path / "device" / "state.bin")
    sync = _sync_from_proposal(wallet, proposal, metadata)

    wrong_derivation = dataclasses.replace(sync.coins[0].coin, derivation=(0, 9))
    with pytest.raises(WalletStateError, match="does not pay"):
        store.apply_sync(
            wallet,
            key,
            dataclasses.replace(
                sync,
                request_id="wrong-derivation",
                coins=(dataclasses.replace(sync.coins[0], coin=wrong_derivation),),
            ),
            xpub,
        )

    with pytest.raises(WalletStateError, match="not anchored"):
        store.apply_sync(
            wallet,
            key,
            dataclasses.replace(
                sync,
                request_id="bad-anchor",
                header_anchors={metadata["block_height"]: b"\x11" * 32},
            ),
            xpub,
        )

    store.apply_sync(wallet, key, sync, xpub)
    with pytest.raises(WalletStateError, match="stale"):
        store.apply_sync(
            wallet,
            key,
            dataclasses.replace(sync, request_id="stale"),
            xpub,
        )


def test_bound_spend_commits_before_export_and_replays_after_restart(tmp_path) -> None:
    vault, wallet, key, xpub, proposal, metadata = _wallet(tmp_path)
    store = WalletStateStore(tmp_path / "device" / "state.bin")
    sync = _sync_from_proposal(wallet, proposal, metadata)
    synced, sync_receipt = store.apply_sync(wallet, key, sync, xpub)
    bound = dataclasses.replace(
        proposal,
        state_revision=synced.revision,
        state_hash=synced.state_hash(),
        proposal_id="proposal-1",
    )
    verified = verify.verify_proposal(bound, xpub)
    signed = signing.build_signed_tx(
        verified,
        partial(vault.derive_signing_key, PIN, wallet.id),
    )

    updated, receipt = store.commit_signed(wallet, key, bound, verified, signed.atomic_beef)
    assert updated.revision == 2
    assert updated.total_sats == metadata["change_amount_sats"]
    assert updated.coins[f"{signed.txid}:1"].status == "pending"
    assert receipt.removed_outpoints == (f"{metadata['funding_txid']}:0",)

    reopened = WalletStateStore(store.path)
    replay = reopened.pending_for_request(wallet, key, "proposal-1")
    assert replay is not None
    replay_beef, replay_receipt = replay
    assert replay_beef == signed.atomic_beef
    assert replay_receipt == receipt
    assert reopened.pending_for_proposal(wallet, key, bound) == replay

    # Idempotency metadata must remain exact even after later transitions.
    current, old_sync_receipt = reopened.apply_sync(wallet, key, sync, xpub)
    assert current.revision == 2
    assert old_sync_receipt == sync_receipt

    with pytest.raises(WalletStateError, match="already signed"):
        reopened.commit_signed(wallet, key, bound, verified, signed.atomic_beef)


def test_first_legacy_spend_migrates_then_requires_state_binding(tmp_path) -> None:
    vault, wallet, key, xpub, proposal, _metadata = _wallet(tmp_path)
    store = WalletStateStore(tmp_path / "device" / "state.bin")
    verified = verify.verify_proposal(proposal, xpub)
    signed = signing.build_signed_tx(
        verified,
        partial(vault.derive_signing_key, PIN, wallet.id),
    )

    migrated, receipt = store.commit_signed(wallet, key, proposal, verified, signed.atomic_beef)
    assert migrated.revision == 1
    assert receipt.old_revision == 0
    assert receipt.removed_outpoints == (f"{proposal.inputs[0].txid}:0",)

    with pytest.raises(WalletStateError, match="state-bound"):
        store.validate_proposal_binding(wallet, key, proposal)


def test_wallet_removal_and_vault_wipe_destroy_state_entries(tmp_path) -> None:
    vault, wallet, _key, *_ = _wallet(tmp_path)
    state_path = tmp_path / "device" / "state.bin"
    assert state_path.exists()

    vault.remove_wallet(PIN, wallet.id)
    outer = cbor2.loads(state_path.read_bytes())
    assert outer["wallets"] == {}

    replacement = vault.add_wallet(PIN, CANONICAL_MNEMONIC, "replacement")
    assert replacement.id
    vault.wipe()
    assert not state_path.exists()
