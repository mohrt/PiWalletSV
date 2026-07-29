"""Encrypted, authoritative wallet state for scan-free normal operation.

``vault.bin`` continues to own keys and PIN policy.  This module owns the
transaction facts those keys alone cannot recover: coins, a deduplicated
Atomic-BEEF store, header anchors, derivation counters, transition journal,
and signed responses that may need to be re-exported after a power loss.

Each wallet entry in ``state.bin`` is encrypted independently with a key
derived by :class:`piwallet.core.vault.Vault` from a domain-separated hardened
account child.  The outer file contains only routing metadata, so a state file
copied from USB remains decryptable after restoring the same mnemonic/account
under a different PIN or wallet UUID.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cbor2
from bsv import P2PKH, Transaction
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from piwallet.core import atomic_beef
from piwallet.core import derivation as deriv
from piwallet.core.envelope import (
    StateCoin,
    StateReceipt,
    StateSync,
    UnsignedProposal,
)
from piwallet.core.verify import OfflineChainTracker, VerifiedProposal

STATE_FILE_VERSION = 1
STATE_SCHEMA_VERSION = 1
STATE_NONCE_LEN = 12
ZERO_STATE_HASH = b"\x00" * 32


class WalletStateError(Exception):
    """State decryption, validation, or transition failure."""


@dataclass(frozen=True)
class WalletIdentity:
    fingerprint: bytes
    account_path: str
    network: str

    @property
    def storage_id(self) -> str:
        material = (
            self.fingerprint.hex() + "\0" + self.account_path + "\0" + self.network
        ).encode()
        return hashlib.sha256(material).hexdigest()

    @property
    def aad(self) -> bytes:
        return (
            b"PiWalletSV/state.bin/entry/v1\0"
            + self.fingerprint
            + b"\0"
            + self.account_path.encode()
            + b"\0"
            + self.network.encode()
        )


def identity_from_wallet(wallet: Any) -> WalletIdentity:
    return WalletIdentity(
        fingerprint=bytes(wallet.fingerprint),
        account_path=str(wallet.derivation_path),
        network=str(wallet.network),
    )


def outpoint(txid: str, vout: int) -> str:
    return f"{txid}:{vout}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _coin_from_cbor(raw: Any) -> StateCoin:
    if not isinstance(raw, dict):
        raise WalletStateError("coin entry must be a map")
    try:
        derivation = raw["derivation"]
        coin = StateCoin(
            txid=str(raw["txid"]),
            vout=int(raw["vout"]),
            sats=int(raw["sats"]),
            locking_script=str(raw["script"]),
            derivation=(int(derivation[0]), int(derivation[1])),
            status=str(raw["status"]),
            transaction_reference=str(raw["txRef"]),
            block_height=int(raw["height"]),
        )
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise WalletStateError(f"invalid coin entry: {exc}") from exc
    if (
        len(coin.txid) != 64
        or any(c not in "0123456789abcdefABCDEF" for c in coin.txid)
        or coin.vout < 0
        or coin.sats <= 0
        or coin.block_height < 0
        or coin.status not in {"confirmed", "pending"}
        or coin.derivation[0] not in {0, 1}
        or not 0 <= coin.derivation[1] < deriv.BIP32_HARDENED
        or (coin.status == "confirmed") != (coin.block_height > 0)
    ):
        raise WalletStateError("invalid coin values")
    return coin


@dataclass
class WalletState:
    wallet_fingerprint: bytes
    account_path: str
    network: str
    schema_version: int = STATE_SCHEMA_VERSION
    revision: int = 0
    previous_state_hash: bytes = ZERO_STATE_HASH
    next_receive_index: int = 0
    next_change_index: int = 0
    coins: dict[str, StateCoin] = field(default_factory=dict)
    beef_store: dict[str, bytes] = field(default_factory=dict)
    header_anchors: dict[int, bytes] = field(default_factory=dict)
    pending_spends: list[dict[str, Any]] = field(default_factory=list)
    transaction_journal: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def empty(cls, identity: WalletIdentity) -> WalletState:
        return cls(
            wallet_fingerprint=identity.fingerprint,
            account_path=identity.account_path,
            network=identity.network,
        )

    def to_cbor(self, *, for_hash: bool = False) -> dict[str, Any]:
        journal: list[dict[str, Any]] = []
        for event in self.transaction_journal:
            item = dict(event)
            if for_hash:
                # ``resultHash`` records the digest produced by this exact
                # transition. Excluding that one self-reference makes the
                # digest deterministic while the rest of the journal remains
                # hash-protected.
                item.pop("resultHash", None)
            journal.append(item)
        pending: list[dict[str, Any]] = []
        for item in self.pending_spends:
            entry = dict(item)
            if for_hash:
                entry.pop("newStateHash", None)
            pending.append(entry)
        return {
            "schemaVersion": self.schema_version,
            "walletFingerprint": self.wallet_fingerprint,
            "accountPath": self.account_path,
            "network": self.network,
            "stateRevision": self.revision,
            "previousStateHash": self.previous_state_hash,
            "nextReceiveIndex": self.next_receive_index,
            "nextChangeIndex": self.next_change_index,
            "coins": [self.coins[k].to_cbor() for k in sorted(self.coins)],
            "beefStore": {k: self.beef_store[k] for k in sorted(self.beef_store)},
            "headerAnchors": {str(k): self.header_anchors[k] for k in sorted(self.header_anchors)},
            "pendingSpends": pending,
            "transactionJournal": journal,
        }

    @classmethod
    def from_cbor(cls, raw: Any, identity: WalletIdentity) -> WalletState:
        if not isinstance(raw, dict):
            raise WalletStateError("state plaintext must be a map")
        if int(raw.get("schemaVersion", 0)) != STATE_SCHEMA_VERSION:
            raise WalletStateError(f"unsupported state schema: {raw.get('schemaVersion')!r}")
        fingerprint = bytes(raw.get("walletFingerprint", b""))
        account_path = str(raw.get("accountPath", ""))
        network = str(raw.get("network", ""))
        if (
            fingerprint != identity.fingerprint
            or account_path != identity.account_path
            or network != identity.network
        ):
            raise WalletStateError("state identity does not match wallet")
        raw_coins = raw.get("coins", [])
        if not isinstance(raw_coins, list):
            raise WalletStateError("state coins must be a list")
        coins = {}
        for item in raw_coins:
            coin = _coin_from_cbor(item)
            coins[outpoint(coin.txid, coin.vout)] = coin
        raw_beef = raw.get("beefStore", {})
        raw_anchors = raw.get("headerAnchors", {})
        if not isinstance(raw_beef, dict) or not isinstance(raw_anchors, dict):
            raise WalletStateError("state transaction stores must be maps")
        beef_store = {str(k): bytes(v) for k, v in raw_beef.items()}
        anchors = {int(k): bytes(v) for k, v in raw_anchors.items()}
        for root in anchors.values():
            if len(root) != 32:
                raise WalletStateError("state header anchor must be 32 bytes")
        revision = int(raw.get("stateRevision", 0))
        previous_hash = bytes(raw.get("previousStateHash", ZERO_STATE_HASH))
        next_receive = int(raw.get("nextReceiveIndex", 0))
        next_change = int(raw.get("nextChangeIndex", 0))
        if revision < 0 or next_receive < 0 or next_change < 0:
            raise WalletStateError("state counters must be non-negative")
        if len(previous_hash) != 32:
            raise WalletStateError("previousStateHash must be 32 bytes")
        pending = raw.get("pendingSpends", [])
        journal = raw.get("transactionJournal", [])
        if not isinstance(pending, list) or not isinstance(journal, list):
            raise WalletStateError("state journals must be lists")
        return cls(
            wallet_fingerprint=fingerprint,
            account_path=account_path,
            network=network,
            revision=revision,
            previous_state_hash=previous_hash,
            next_receive_index=next_receive,
            next_change_index=next_change,
            coins=coins,
            beef_store=beef_store,
            header_anchors=anchors,
            pending_spends=[dict(v) for v in pending],
            transaction_journal=[dict(v) for v in journal],
        )

    def state_hash(self) -> bytes:
        encoded = cbor2.dumps(self.to_cbor(for_hash=True), canonical=True)
        return hashlib.sha256(encoded).digest()

    def validate_integrity(self) -> None:
        """Validate the authenticated revision chain and transaction references."""
        if len(self.transaction_journal) != self.revision:
            raise WalletStateError("state revision does not match journal length")
        previous_result: bytes | None = None
        events_by_request: dict[str, dict[str, Any]] = {}
        last_old_hash = ZERO_STATE_HASH
        for index, event in enumerate(self.transaction_journal):
            try:
                request_id = str(event["requestId"])
                old_revision = int(event["oldRevision"])
                new_revision = int(event["newRevision"])
                old_hash = bytes(event["oldStateHash"])
                result_hash = bytes(event["resultHash"])
            except (KeyError, TypeError, ValueError) as exc:
                raise WalletStateError(f"invalid journal event {index}: {exc}") from exc
            if (
                not request_id
                or request_id in events_by_request
                or old_revision != index
                or new_revision != index + 1
                or len(old_hash) != 32
                or len(result_hash) != 32
            ):
                raise WalletStateError(f"invalid journal transition at revision {index}")
            if previous_result is not None and old_hash != previous_result:
                raise WalletStateError(f"broken state hash chain at revision {index}")
            if index == 0:
                genesis = WalletState(
                    wallet_fingerprint=self.wallet_fingerprint,
                    account_path=self.account_path,
                    network=self.network,
                ).state_hash()
                if old_hash != genesis:
                    raise WalletStateError("state journal does not begin at wallet genesis")
            events_by_request[request_id] = event
            previous_result = result_hash
            last_old_hash = old_hash

        if self.transaction_journal:
            if self.previous_state_hash != last_old_hash:
                raise WalletStateError("previousStateHash does not match latest transition")
            if previous_result != self.state_hash():
                raise WalletStateError("latest journal result does not match wallet state")
        elif self.previous_state_hash != ZERO_STATE_HASH:
            raise WalletStateError("empty state has a non-zero previous hash")

        pending_ids: set[str] = set()
        for item in self.pending_spends:
            try:
                request_id = str(item["requestId"])
                txid = str(item["txid"])
                atomic = bytes(item["atomicBeef"])
                event = events_by_request[request_id]
            except (KeyError, TypeError, ValueError) as exc:
                raise WalletStateError(f"invalid pending spend: {exc}") from exc
            if request_id in pending_ids or event.get("type") != "spend":
                raise WalletStateError("pending spend has no unique journal transition")
            try:
                subject_txid, _ = atomic_beef.split(atomic)
            except atomic_beef.AtomicBeefError as exc:
                raise WalletStateError(f"pending spend Atomic BEEF is invalid: {exc}") from exc
            if (
                subject_txid != txid
                or bytes(item.get("oldStateHash", b"")) != bytes(event.get("oldStateHash", b""))
                or bytes(item.get("newStateHash", b"")) != bytes(event.get("resultHash", b""))
            ):
                raise WalletStateError("pending spend does not match its journal transition")
            pending_ids.add(request_id)

        for reference, atomic in self.beef_store.items():
            try:
                subject_txid, _ = atomic_beef.split(atomic)
            except atomic_beef.AtomicBeefError as exc:
                raise WalletStateError(f"stored Atomic BEEF is invalid: {exc}") from exc
            if subject_txid != reference:
                raise WalletStateError("stored Atomic BEEF transaction reference is invalid")
        if any(coin.transaction_reference not in self.beef_store for coin in self.coins.values()):
            raise WalletStateError("state coin references missing Atomic BEEF")

    @property
    def total_sats(self) -> int:
        return sum(c.sats for c in self.coins.values())


class WalletStateStore:
    """Atomic multi-wallet ``state.bin`` reader/writer."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def _read_outer(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"stateFileVersion": STATE_FILE_VERSION, "wallets": {}}
        try:
            outer = cbor2.loads(self.path.read_bytes())
        except (OSError, cbor2.CBORDecodeError, EOFError) as exc:
            raise WalletStateError(f"cannot read state file: {exc}") from exc
        if not isinstance(outer, dict):
            raise WalletStateError("state file must be a map")
        if int(outer.get("stateFileVersion", 0)) != STATE_FILE_VERSION:
            raise WalletStateError(
                f"unsupported state file version: {outer.get('stateFileVersion')!r}"
            )
        if not isinstance(outer.get("wallets"), dict):
            raise WalletStateError("state file wallets must be a map")
        return outer

    def _write_outer(self, outer: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("wb") as f:
            f.write(cbor2.dumps(outer, canonical=True))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            # FAT-formatted backup/test media may not implement Unix modes.
            pass

    def load(self, wallet: Any, state_key: bytes) -> WalletState:
        identity = identity_from_wallet(wallet)
        outer = self._read_outer()
        entry = outer["wallets"].get(identity.storage_id)
        if entry is None:
            return WalletState.empty(identity)
        if not isinstance(entry, dict):
            raise WalletStateError("state wallet entry must be a map")
        blob = entry.get("ciphertext")
        if not isinstance(blob, (bytes, bytearray)) or len(blob) < STATE_NONCE_LEN + 16:
            raise WalletStateError("state ciphertext is truncated")
        try:
            plaintext = AESGCM(state_key).decrypt(
                bytes(blob[:STATE_NONCE_LEN]),
                bytes(blob[STATE_NONCE_LEN:]),
                identity.aad,
            )
            raw = cbor2.loads(plaintext)
        except Exception as exc:
            raise WalletStateError("state decryption or authentication failed") from exc
        state = WalletState.from_cbor(raw, identity)
        state.validate_integrity()
        return state

    def save(self, wallet: Any, state_key: bytes, state: WalletState) -> None:
        identity = identity_from_wallet(wallet)
        if (
            state.wallet_fingerprint != identity.fingerprint
            or state.account_path != identity.account_path
            or state.network != identity.network
        ):
            raise WalletStateError("refusing to save state under a different wallet")
        plaintext = cbor2.dumps(state.to_cbor(), canonical=True)
        nonce = secrets.token_bytes(STATE_NONCE_LEN)
        ciphertext = nonce + AESGCM(state_key).encrypt(nonce, plaintext, identity.aad)
        outer = self._read_outer()
        outer["wallets"][identity.storage_id] = {
            "fingerprint": identity.fingerprint,
            "accountPath": identity.account_path,
            "network": identity.network,
            "schemaVersion": STATE_SCHEMA_VERSION,
            "ciphertext": ciphertext,
        }
        self._write_outer(outer)

    def ensure_wallet(self, wallet: Any, state_key: bytes) -> WalletState:
        state = self.load(wallet, state_key)
        outer = self._read_outer()
        identity = identity_from_wallet(wallet)
        if identity.storage_id not in outer["wallets"]:
            self.save(wallet, state_key, state)
        return state

    def delete_wallet(self, wallet: Any) -> None:
        identity = identity_from_wallet(wallet)
        outer = self._read_outer()
        if outer["wallets"].pop(identity.storage_id, None) is not None:
            self._write_outer(outer)

    def clear(self) -> None:
        if not self.path.exists():
            return
        try:
            size = self.path.stat().st_size
            with self.path.open("r+b") as f:
                f.write(secrets.token_bytes(size))
                f.flush()
                os.fsync(f.fileno())
        finally:
            self.path.unlink(missing_ok=True)

    def apply_sync(
        self,
        wallet: Any,
        state_key: bytes,
        sync: StateSync,
        account_xpub_str: str,
    ) -> tuple[WalletState, StateReceipt]:
        state = self.load(wallet, state_key)
        if sync.wallet_fp != state.wallet_fingerprint:
            raise WalletStateError("state sync is for a different wallet")

        replay = _receipt_for_request(state, sync.request_id)
        if replay is not None:
            return state, replay

        old_hash = state.state_hash()
        initial_sentinel = (
            state.revision == 0
            and not state.coins
            and sync.expected_revision == 0
            and sync.expected_state_hash == ZERO_STATE_HASH
        )
        if not initial_sentinel and (
            sync.expected_revision != state.revision or sync.expected_state_hash != old_hash
        ):
            raise WalletStateError(
                "state sync is stale; import the Pi's latest state receipt first"
            )

        updated = copy.deepcopy(state)
        xpub = deriv.parse_xpub(account_xpub_str)
        added: list[StateCoin] = []
        for package in sync.coins:
            verified = _verify_sync_coin(
                package.coin,
                package.atomic_beef,
                sync.header_anchors,
                xpub,
                wallet.network,
            )
            key = outpoint(verified.txid, verified.vout)
            existing = updated.coins.get(key)
            if existing is not None and (
                existing.sats != verified.sats
                or existing.locking_script != verified.locking_script
                or existing.derivation != verified.derivation
            ):
                raise WalletStateError(f"conflicting update for coin {key}")
            if existing != verified:
                updated.coins[key] = verified
                added.append(verified)
            updated.beef_store[verified.transaction_reference] = package.atomic_beef
        updated.header_anchors.update(sync.header_anchors)
        updated.next_receive_index = max(updated.next_receive_index, sync.next_receive_index)
        updated.next_change_index = max(updated.next_change_index, sync.next_change_index)

        updated.previous_state_hash = old_hash
        updated.revision += 1
        event = {
            "at": _now_iso(),
            "type": "sync",
            "requestId": sync.request_id,
            "oldRevision": state.revision,
            "newRevision": updated.revision,
            "oldStateHash": old_hash,
            "addedCoins": [c.to_cbor() for c in added],
            "removedOutpoints": [],
        }
        updated.transaction_journal.append(event)
        new_hash = updated.state_hash()
        event["resultHash"] = new_hash
        receipt = StateReceipt(
            wallet_fp=state.wallet_fingerprint,
            request_id=sync.request_id,
            old_revision=state.revision,
            new_revision=updated.revision,
            old_state_hash=old_hash,
            new_state_hash=new_hash,
            added_coins=tuple(added),
        )
        self.save(wallet, state_key, updated)
        return updated, receipt

    def validate_proposal_binding(
        self, wallet: Any, state_key: bytes, proposal: UnsignedProposal
    ) -> WalletState:
        """Reject stale/unbound active-state proposals before any signing."""
        state = self.load(wallet, state_key)
        has_binding = proposal.state_revision is not None or proposal.state_hash is not None
        if has_binding:
            if proposal.state_revision is None or proposal.state_hash is None:
                raise WalletStateError("proposal state binding is incomplete")
            if (
                proposal.state_revision != state.revision
                or proposal.state_hash != state.state_hash()
            ):
                raise WalletStateError("proposal was built from stale wallet state")
        elif state.revision != 0 or state.coins:
            raise WalletStateError(
                "active wallet state requires a state-bound proposal; update the companion"
            )
        return state

    def commit_signed(
        self,
        wallet: Any,
        state_key: bytes,
        proposal: UnsignedProposal,
        verified: VerifiedProposal,
        signed_atomic_beef: bytes,
    ) -> tuple[WalletState, StateReceipt]:
        state = self.load(wallet, state_key)
        request_id = proposal.proposal_id or _legacy_proposal_id(proposal)
        replay = _receipt_for_request(state, request_id)
        if replay is not None:
            raise WalletStateError(
                "proposal was already signed; re-export the pending signed transaction"
            )

        old_hash = state.state_hash()
        has_binding = proposal.state_revision is not None or proposal.state_hash is not None
        if has_binding:
            if proposal.state_revision is None or proposal.state_hash is None:
                raise WalletStateError("proposal state binding is incomplete")
            if proposal.state_revision != state.revision or proposal.state_hash != old_hash:
                raise WalletStateError("proposal was built from stale wallet state")
        elif state.revision != 0 or state.coins:
            raise WalletStateError(
                "active wallet state requires a state-bound proposal; update the companion"
            )

        updated = copy.deepcopy(state)
        # Backward-compatible migration: the first legacy proposal already
        # carries verified BEEF and anchors. Adopt those inputs into the empty
        # state and consume them in this same atomic transition.
        if not has_binding:
            for ip, vin, height in zip(
                proposal.inputs, verified.inputs, verified.input_heights, strict=True
            ):
                coin = StateCoin(
                    txid=vin.txid,
                    vout=vin.vout,
                    sats=vin.prevout_sats,
                    locking_script=vin.prevout_script_hex,
                    derivation=vin.derivation,
                    status="confirmed",
                    transaction_reference=vin.txid,
                    block_height=height,
                )
                updated.coins[outpoint(coin.txid, coin.vout)] = coin
                updated.beef_store[coin.txid] = _as_atomic_beef(ip.txid, ip.beef)
            updated.header_anchors.update(proposal.header_anchors)

        removed: list[str] = []
        for vin in verified.inputs:
            key = outpoint(vin.txid, vin.vout)
            coin = updated.coins.get(key)
            if coin is None:
                raise WalletStateError(f"proposal input {key} is not in signer state")
            if (
                coin.sats != vin.prevout_sats
                or coin.locking_script != vin.prevout_script_hex
                or coin.derivation != vin.derivation
            ):
                raise WalletStateError(f"proposal input {key} conflicts with signer state")
            del updated.coins[key]
            removed.append(key)

        try:
            signed_tx = atomic_beef.to_transaction(signed_atomic_beef)
        except atomic_beef.AtomicBeefError as exc:
            raise WalletStateError(f"signed transaction BEEF is invalid: {exc}") from exc
        change_output = signed_tx.outputs[proposal.change_index]
        change_coin = StateCoin(
            txid=signed_tx.txid(),
            vout=proposal.change_index,
            sats=int(change_output.satoshis),
            locking_script=change_output.locking_script.hex(),
            derivation=proposal.change_derivation,
            status="pending",
            transaction_reference=signed_tx.txid(),
            block_height=0,
        )
        updated.coins[outpoint(change_coin.txid, change_coin.vout)] = change_coin
        updated.beef_store[signed_tx.txid()] = signed_atomic_beef
        updated.header_anchors.update(proposal.header_anchors)
        updated.next_change_index = max(
            updated.next_change_index, proposal.change_derivation[1] + 1
        )
        updated.previous_state_hash = old_hash
        updated.revision += 1
        event = {
            "at": _now_iso(),
            "type": "spend",
            "requestId": request_id,
            "txid": signed_tx.txid(),
            "oldRevision": state.revision,
            "newRevision": updated.revision,
            "oldStateHash": old_hash,
            "addedCoins": [change_coin.to_cbor()],
            "removedOutpoints": removed,
        }
        updated.transaction_journal.append(event)
        pending = {
            "requestId": request_id,
            "txid": signed_tx.txid(),
            "atomicBeef": signed_atomic_beef,
            "oldRevision": state.revision,
            "newRevision": updated.revision,
            "oldStateHash": old_hash,
            "addedCoins": [change_coin.to_cbor()],
            "removedOutpoints": removed,
            "createdAt": _now_iso(),
        }
        updated.pending_spends.append(pending)
        new_hash = updated.state_hash()
        event["resultHash"] = new_hash
        pending["newStateHash"] = new_hash
        receipt = StateReceipt(
            wallet_fp=state.wallet_fingerprint,
            request_id=request_id,
            old_revision=state.revision,
            new_revision=updated.revision,
            old_state_hash=old_hash,
            new_state_hash=new_hash,
            added_coins=(change_coin,),
            removed_outpoints=tuple(removed),
        )
        self.save(wallet, state_key, updated)
        return updated, receipt

    def pending_for_request(
        self, wallet: Any, state_key: bytes, request_id: str
    ) -> tuple[bytes, StateReceipt] | None:
        state = self.load(wallet, state_key)
        for item in reversed(state.pending_spends):
            if item.get("requestId") != request_id:
                continue
            return bytes(item["atomicBeef"]), _receipt_from_pending(state, item)
        return None

    def pending_for_proposal(
        self,
        wallet: Any,
        state_key: bytes,
        proposal: UnsignedProposal,
    ) -> tuple[bytes, StateReceipt] | None:
        """Return a persisted response for either modern or legacy proposals."""
        request_id = proposal.proposal_id or _legacy_proposal_id(proposal)
        return self.pending_for_request(wallet, state_key, request_id)

    def latest_pending(self, wallet: Any, state_key: bytes) -> tuple[bytes, StateReceipt] | None:
        state = self.load(wallet, state_key)
        if not state.pending_spends:
            return None
        item = state.pending_spends[-1]
        return bytes(item["atomicBeef"]), _receipt_from_pending(state, item)


def _verify_sync_coin(
    claimed: StateCoin,
    atomic: bytes,
    anchors: dict[int, bytes],
    account_xpub: Any,
    network: deriv.Network,
) -> StateCoin:
    try:
        tx = atomic_beef.to_transaction(atomic)
    except atomic_beef.AtomicBeefError as exc:
        raise WalletStateError(f"incoming Atomic BEEF failed: {exc}") from exc
    if tx.txid() != claimed.txid or claimed.transaction_reference != claimed.txid:
        raise WalletStateError("incoming transaction reference does not match BEEF")
    if claimed.vout >= len(tx.outputs):
        raise WalletStateError(f"incoming vout {claimed.vout} is out of range")
    output = tx.outputs[claimed.vout]
    actual_script = output.locking_script.hex()
    actual_sats = int(output.satoshis)
    if claimed.sats != actual_sats or claimed.locking_script != actual_script:
        raise WalletStateError("incoming coin amount/script does not match transaction")
    try:
        address = deriv.derive_address(
            account_xpub,
            claimed.derivation[0],
            claimed.derivation[1],
            network=network,
        )
        expected_script = P2PKH().lock(address).hex()
    except Exception as exc:
        raise WalletStateError(f"incoming coin derivation is invalid: {exc}") from exc
    if expected_script != actual_script:
        raise WalletStateError("incoming output does not pay the declared derivation")
    if tx.merkle_path is None:
        raise WalletStateError("incoming transaction has no Merkle proof")
    height = int(tx.merkle_path.block_height)
    if height != claimed.block_height or height not in anchors:
        raise WalletStateError("incoming transaction has no matching header anchor")
    tracker = OfflineChainTracker({h: root[::-1].hex() for h, root in anchors.items()})
    try:
        anchored = asyncio.run(tx.merkle_path.verify(tx.txid(), tracker))
    except Exception:
        anchored = False
    if not anchored:
        raise WalletStateError("incoming transaction Merkle proof is not anchored")
    return StateCoin(
        txid=claimed.txid,
        vout=claimed.vout,
        sats=actual_sats,
        locking_script=actual_script,
        derivation=claimed.derivation,
        status="confirmed",
        transaction_reference=claimed.txid,
        block_height=height,
    )


def _as_atomic_beef(txid: str, beef: bytes) -> bytes:
    # Proposal BEEF may contain the funding transaction as the top-level tx.
    # Normalize it to the BRC-95 wrapper used by the global state store.
    tx = Transaction.from_beef(beef)
    if tx.txid() == txid:
        return atomic_beef.encode(tx)
    for tx_input in tx.inputs:
        prior = tx_input.source_transaction
        if prior is not None and prior.txid() == txid:
            return atomic_beef.encode(prior)
    raise WalletStateError(f"proposal BEEF does not contain {txid[:8]}…")


def _legacy_proposal_id(proposal: UnsignedProposal) -> str:
    raw = cbor2.dumps(proposal.to_cbor(), canonical=True)
    return "legacy-" + hashlib.sha256(raw).hexdigest()


def _receipt_for_request(state: WalletState, request_id: str) -> StateReceipt | None:
    for event in reversed(state.transaction_journal):
        if event.get("requestId") != request_id or "resultHash" not in event:
            continue
        return StateReceipt(
            wallet_fp=state.wallet_fingerprint,
            request_id=request_id,
            old_revision=int(event["oldRevision"]),
            new_revision=int(event["newRevision"]),
            old_state_hash=(
                bytes(event["oldStateHash"])
                if "oldStateHash" in event
                else state.previous_state_hash
            ),
            new_state_hash=bytes(event["resultHash"]),
            added_coins=tuple(_coin_from_cbor(v) for v in event.get("addedCoins", [])),
            removed_outpoints=tuple(str(v) for v in event.get("removedOutpoints", [])),
        )
    return None


def _receipt_from_pending(state: WalletState, item: dict[str, Any]) -> StateReceipt:
    return StateReceipt(
        wallet_fp=state.wallet_fingerprint,
        request_id=str(item["requestId"]),
        old_revision=int(item["oldRevision"]),
        new_revision=int(item["newRevision"]),
        old_state_hash=bytes(item["oldStateHash"]),
        new_state_hash=bytes(item["newStateHash"]),
        added_coins=tuple(_coin_from_cbor(v) for v in item.get("addedCoins", [])),
        removed_outpoints=tuple(str(v) for v in item.get("removedOutpoints", [])),
    )


__all__ = [
    "STATE_FILE_VERSION",
    "STATE_SCHEMA_VERSION",
    "ZERO_STATE_HASH",
    "WalletIdentity",
    "WalletState",
    "WalletStateError",
    "WalletStateStore",
    "identity_from_wallet",
    "outpoint",
]
