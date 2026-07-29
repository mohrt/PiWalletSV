"""CBOR-coded versioned envelopes that travel between Pi and PWA over QR.

Five message kinds are defined; all share a small header so a receiver
can route them to the right handler before decoding the rest:

- `xpub_export`        Pi -> phone, on pairing. Contains the account xpub.
- `unsigned_proposal`  phone -> Pi, on send. Contains the unsigned tx,
                       per-input BEEF (BRC-62), a small ``height -> merkle
                       root`` map of header anchors (one entry per unique
                       block referenced by the inputs' BUMP paths), and
                       the change derivation index.
- `signed_tx`          Pi -> phone, after successful sign. Contains the
                       signed transaction as Atomic BEEF (BRC-95) and its
                       state transition receipt when state tracking is active.
- `state_sync`         phone -> Pi. Delivers confirmed Atomic BEEF payments
                       and the public derivation metadata needed to secure them.
- `state_receipt`      Pi -> phone. Commits a state revision/hash transition so
                       the companion can update its public mirror without a scan.

On-the-wire encoding is **CBOR + gzip**. Larger blobs are split into
``PW1|`` multipart barcode lines in :mod:`piwallet.qr`; that layer is
intentionally separate from this codec.

Schema versioning: every payload carries an integer ``v``. Bump on
breaking changes; the receiver MUST refuse unknown versions. v2
(this revision) keeps v1's ``headerAnchors`` (a trusted
``height -> root`` map supplied by the companion), drops the
redundant standalone per-input ``merklePath`` field (the BEEF
already carries the BUMP), and uses Atomic BEEF (BRC-95) for the
``signed_tx`` payload.

The CBOR shapes are deliberately flat dicts with short string keys to keep
multipart QR payloads small.
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from typing import Any, ClassVar

import cbor2

ENVELOPE_VERSION: int = 2
MAX_DERIVATION_INDEX: int = 0x80000000
"""Current envelope schema version. Bump for breaking changes.

History:
    v1 — initial release. Carried per-input ``merklePath`` (redundant
         with BEEF) and a hex-string + separate txid for ``signed_tx``.
    v2 — drop the redundant per-input ``merklePath`` field (the BEEF
         payload already carries it); switch the ``signed_tx`` payload
         from a hex-string + separate txid to a single ``atomicBeef``
         bytes field (BRC-95). The ``header_anchors`` shape is
         unchanged from v1. v1 envelopes are intentionally rejected by
         this build; the schema bump is the documented signal that a
         v1 producer should be upgraded.
"""

KIND_XPUB_EXPORT: str = "xpub"
KIND_UNSIGNED_PROPOSAL: str = "tx"
KIND_SIGNED_TX: str = "signed"
KIND_STATE_SYNC: str = "stateSync"
KIND_STATE_RECEIPT: str = "stateReceipt"

VALID_KINDS: frozenset[str] = frozenset(
    {
        KIND_XPUB_EXPORT,
        KIND_UNSIGNED_PROPOSAL,
        KIND_SIGNED_TX,
        KIND_STATE_SYNC,
        KIND_STATE_RECEIPT,
    }
)


class EnvelopeError(ValueError):
    """Raised for malformed or unsupported envelopes."""


# ---------------------------------------------------------------------------
# Dataclasses representing decoded payloads.
# ---------------------------------------------------------------------------


#: Allowed values for the xpub_export envelope's ``net`` field.
VALID_NETWORKS: frozenset[str] = frozenset({"main", "test"})


@dataclass(frozen=True)
class XpubExport:
    """Pi -> phone pairing payload.

    ``network`` is ``"main"`` for BSV mainnet (legacy P2PKH prefix
    0x00) or ``"test"`` for BSV testnet (prefix 0x6F). The companion
    keys its address renderer + WhatsOnChain endpoint off this value
    so a paired wallet hits the right network end-to-end. Older
    envelopes that predate this field are accepted on the receive
    side as ``"main"`` (the only network the Pi supported pre-v1.1).
    """

    KIND: ClassVar[str] = KIND_XPUB_EXPORT

    xpub: str
    path: str
    label: str
    fingerprint: bytes  # 4 bytes, self-fingerprint (hash160(pubkey)[:4])
    network: str = "main"

    def to_cbor(self) -> dict[str, Any]:
        return {
            "v": ENVELOPE_VERSION,
            "kind": self.KIND,
            "xpub": self.xpub,
            "path": self.path,
            "label": self.label,
            "fp": self.fingerprint,
            "net": self.network,
        }

    @classmethod
    def from_cbor(cls, body: dict[str, Any]) -> XpubExport:
        _require_keys(body, {"xpub", "path", "label", "fp"}, cls.KIND)
        fp = body["fp"]
        if not isinstance(fp, (bytes, bytearray)) or len(fp) != 4:
            raise EnvelopeError("fingerprint 'fp' must be 4 bytes")
        # Forward-migrate pre-v1.1 envelopes that lack the `net` key:
        # everything before testnet support shipped was mainnet, so
        # treat the absence as an explicit "main".
        net = str(body.get("net", "main"))
        if net not in VALID_NETWORKS:
            raise EnvelopeError(
                f"network 'net' must be one of {sorted(VALID_NETWORKS)!r}; got {net!r}"
            )
        return cls(
            xpub=str(body["xpub"]),
            path=str(body["path"]),
            label=str(body["label"]),
            fingerprint=bytes(fp),
            network=net,
        )


@dataclass(frozen=True)
class ProposalInput:
    """One input in an `unsigned_proposal`.

    ``beef`` is the BRC-62 BEEF bytes covering the prior tx that funds
    this input, including the prior tx's BRC-74 BUMP Merkle path. The
    standalone ``merklePath`` field that earlier revisions of this
    schema also carried per input was always redundant with the BEEF
    payload; it was removed in envelope version 2.

    ``derivation`` is the index pair this input's key was derived from
    (change, index). The Pi uses it to derive the matching signing key.
    """

    txid: str
    vout: int
    sats: int
    beef: bytes
    derivation: tuple[int, int]  # (change, index)


@dataclass(frozen=True)
class ProposalOutput:
    """One output in an `unsigned_proposal`.

    `script_hex` is the locking script (P2PKH for v1). `sats` is the amount.
    Outputs are ordered as the eventual signed tx will serialize them.
    """

    script_hex: str
    sats: int


@dataclass(frozen=True)
class StateCoin:
    """Public description of one coin in the signer/companion state mirror."""

    txid: str
    vout: int
    sats: int
    locking_script: str
    derivation: tuple[int, int]
    status: str
    transaction_reference: str
    block_height: int

    def to_cbor(self) -> dict[str, Any]:
        return {
            "txid": self.txid,
            "vout": self.vout,
            "sats": self.sats,
            "script": self.locking_script,
            "derivation": list(self.derivation),
            "status": self.status,
            "txRef": self.transaction_reference,
            "height": self.block_height,
        }


@dataclass(frozen=True)
class StateSyncCoin:
    """A coin plus the confirmed Atomic BEEF that proves its transaction."""

    coin: StateCoin
    atomic_beef: bytes

    def to_cbor(self) -> dict[str, Any]:
        return {**self.coin.to_cbor(), "atomicBeef": self.atomic_beef}


@dataclass(frozen=True)
class UnsignedProposal:
    """Phone -> Pi spend request. The Pi MUST verify before signing.

    ``change_derivation`` is a ``(branch, index)`` pair the Pi uses to
    re-derive the change output's address from the wallet's account
    xpub. If the re-derived address doesn't match the script at
    ``outputs[change_index]``, signing must abort. This is the plan's
    "verify, then sign" rule.

    ``header_anchors`` is a ``height -> merkle_root`` map: one entry
    for each unique block height referenced by an input's BUMP path.
    The companion fetches each block's header from a trusted
    block-explorer source (WhatsOnChain by default) and packs the
    Merkle root in raw byte order (32 bytes). The Pi compares the
    BUMP-derived root for each input against the anchored root; a
    mismatch fails verification.

    Trust model: the Pi trusts the companion (and by extension the
    explorer the companion talked to) for the ``height -> root``
    correspondence. A malicious companion can at most cause the Pi
    to sign a transaction whose inputs do not exist on chain — the
    broadcast then fails. The Pi's keys, change re-derivation, and
    on-screen output review are unaffected. Strong on-device SPV
    (PoW-validated header chain back to a firmware checkpoint) is a
    documented future direction; see ``docs/protocol/spv.md``.
    """

    KIND: ClassVar[str] = KIND_UNSIGNED_PROPOSAL

    wallet_fp: bytes
    inputs: tuple[ProposalInput, ...]
    outputs: tuple[ProposalOutput, ...]
    change_index: int  # index in `outputs` that the Pi must re-derive
    change_derivation: tuple[int, int]  # (branch, index) for the change address
    fee_rate_satskb: int
    header_anchors: dict[int, bytes]  # height -> merkle_root (32 bytes, raw byte order)
    locktime: int = 0
    # Additive v2 fields. They are optional so pre-state companions remain
    # decodable and can perform the one-time empty-state migration.
    state_revision: int | None = None
    state_hash: bytes | None = None
    proposal_id: str = ""

    def to_cbor(self) -> dict[str, Any]:
        # CBOR allows int keys, but to keep multipart-QR text dumps
        # easy on the eye and to match the companion's JSON-friendly
        # encoder, we serialize anchors as a map of decimal-string
        # keys to bytes values.
        anchors = {str(h): root for h, root in sorted(self.header_anchors.items())}
        body = {
            "v": ENVELOPE_VERSION,
            "kind": self.KIND,
            "walletFp": self.wallet_fp,
            "inputs": [
                {
                    "txid": ip.txid,
                    "vout": ip.vout,
                    "sats": ip.sats,
                    "beef": ip.beef,
                    "derivation": list(ip.derivation),
                }
                for ip in self.inputs
            ],
            "outputs": [{"script": op.script_hex, "sats": op.sats} for op in self.outputs],
            "changeIndex": self.change_index,
            "changeDerivation": list(self.change_derivation),
            "feeRate": self.fee_rate_satskb,
            "locktime": self.locktime,
            "headerAnchors": anchors,
        }
        if self.state_revision is not None:
            body["stateRevision"] = self.state_revision
        if self.state_hash is not None:
            body["stateHash"] = self.state_hash
        if self.proposal_id:
            body["proposalId"] = self.proposal_id
        return body

    @classmethod
    def from_cbor(cls, body: dict[str, Any]) -> UnsignedProposal:
        _require_keys(
            body,
            {
                "walletFp",
                "inputs",
                "outputs",
                "changeIndex",
                "changeDerivation",
                "feeRate",
                "headerAnchors",
            },
            cls.KIND,
        )
        wallet_fp = body["walletFp"]
        if not isinstance(wallet_fp, (bytes, bytearray)) or len(wallet_fp) != 4:
            raise EnvelopeError("walletFp must be 4 bytes")

        raw_inputs = body["inputs"]
        if not isinstance(raw_inputs, list) or not raw_inputs:
            raise EnvelopeError("inputs must be a non-empty list")
        inputs = tuple(_decode_input(i) for i in raw_inputs)

        raw_outputs = body["outputs"]
        if not isinstance(raw_outputs, list) or not raw_outputs:
            raise EnvelopeError("outputs must be a non-empty list")
        outputs = tuple(_decode_output(o) for o in raw_outputs)

        change_index = int(body["changeIndex"])
        if change_index < 0 or change_index >= len(outputs):
            raise EnvelopeError(
                f"changeIndex {change_index} out of range for {len(outputs)} outputs"
            )

        cd = body["changeDerivation"]
        if not (isinstance(cd, (list, tuple)) and len(cd) == 2):
            raise EnvelopeError("changeDerivation must be [branch, index]")
        change_derivation = (int(cd[0]), int(cd[1]))

        anchors_raw = body["headerAnchors"]
        if not isinstance(anchors_raw, dict):
            raise EnvelopeError("headerAnchors must be a map of height -> 32-byte root")
        anchors: dict[int, bytes] = {}
        for raw_height, raw_root in anchors_raw.items():
            try:
                height = int(raw_height)
            except (TypeError, ValueError) as exc:
                raise EnvelopeError(
                    f"headerAnchors key {raw_height!r} is not an integer height"
                ) from exc
            if height < 0:
                raise EnvelopeError(f"headerAnchors height {height} must be non-negative")
            if not isinstance(raw_root, (bytes, bytearray)) or len(raw_root) != 32:
                raise EnvelopeError(
                    f"headerAnchors[{height}] must be 32 bytes, got "
                    f"{type(raw_root).__name__} of length "
                    f"{len(raw_root) if isinstance(raw_root, (bytes, bytearray)) else 'n/a'}"
                )
            anchors[height] = bytes(raw_root)
        if not anchors:
            raise EnvelopeError("headerAnchors must contain at least one entry")

        state_revision: int | None = None
        state_hash: bytes | None = None
        if "stateRevision" in body or "stateHash" in body:
            if "stateRevision" not in body or "stateHash" not in body:
                raise EnvelopeError("stateRevision and stateHash must be supplied together")
            state_revision = int(body["stateRevision"])
            if state_revision < 0:
                raise EnvelopeError("stateRevision must be non-negative")
            raw_state_hash = body["stateHash"]
            if not isinstance(raw_state_hash, (bytes, bytearray)) or len(raw_state_hash) != 32:
                raise EnvelopeError("stateHash must be 32 bytes")
            state_hash = bytes(raw_state_hash)

        proposal_id = str(body.get("proposalId", ""))
        if state_revision is not None and not proposal_id:
            raise EnvelopeError("state-bound proposals require proposalId")
        if len(proposal_id) > 128:
            raise EnvelopeError("proposalId must be at most 128 characters")

        return cls(
            wallet_fp=bytes(wallet_fp),
            inputs=inputs,
            outputs=outputs,
            change_index=change_index,
            change_derivation=change_derivation,
            fee_rate_satskb=int(body["feeRate"]),
            locktime=int(body.get("locktime", 0)),
            header_anchors=anchors,
            state_revision=state_revision,
            state_hash=state_hash,
            proposal_id=proposal_id,
        )


def _decode_input(raw: Any) -> ProposalInput:
    if not isinstance(raw, dict):
        raise EnvelopeError("each input must be a dict")
    _require_keys(raw, {"txid", "vout", "sats", "beef", "derivation"}, "input")
    deriv = raw["derivation"]
    if not (isinstance(deriv, (list, tuple)) and len(deriv) == 2):
        raise EnvelopeError("input.derivation must be [change, index]")
    return ProposalInput(
        txid=str(raw["txid"]),
        vout=int(raw["vout"]),
        sats=int(raw["sats"]),
        beef=bytes(raw["beef"]),
        derivation=(int(deriv[0]), int(deriv[1])),
    )


def _decode_output(raw: Any) -> ProposalOutput:
    if not isinstance(raw, dict):
        raise EnvelopeError("each output must be a dict")
    _require_keys(raw, {"script", "sats"}, "output")
    return ProposalOutput(script_hex=str(raw["script"]), sats=int(raw["sats"]))


@dataclass(frozen=True)
class SignedTx:
    """Pi -> phone signed transaction payload.

    The signed transaction is carried in **Atomic BEEF (BRC-95)**
    form, which is a regular BRC-62 BEEF body prefixed with a 4-byte
    magic and the 32-byte subject TXID. The companion uses the
    subject TXID for routing and feedback, and decodes the inner BEEF
    to recover the raw signed tx hex it broadcasts.

    The previously-separate ``raw_hex`` / ``txid`` fields were dropped
    in envelope v2: ``raw_hex`` is reproducible from the BEEF body,
    and ``txid`` is already declared in the Atomic BEEF header.
    """

    KIND: ClassVar[str] = KIND_SIGNED_TX

    wallet_fp: bytes
    atomic_beef: bytes
    state_receipt: StateReceipt | None = None

    @property
    def txid(self) -> str:
        """Subject TXID declared in the Atomic BEEF header.

        Returns the displayed (big-endian-hex) form. Lazily computed;
        the dataclass intentionally does not store it as a separate
        field, since the BRC-95 header is the canonical source.
        """
        from piwallet.core.atomic_beef import split

        subject_txid_hex, _ = split(self.atomic_beef)
        return subject_txid_hex

    def to_cbor(self) -> dict[str, Any]:
        body = {
            "v": ENVELOPE_VERSION,
            "kind": self.KIND,
            "walletFp": self.wallet_fp,
            "atomicBeef": self.atomic_beef,
        }
        if self.state_receipt is not None:
            body["stateReceipt"] = self.state_receipt.to_cbor(include_header=False)
        return body

    @classmethod
    def from_cbor(cls, body: dict[str, Any]) -> SignedTx:
        _require_keys(body, {"walletFp", "atomicBeef"}, cls.KIND)
        fp = body["walletFp"]
        if not isinstance(fp, (bytes, bytearray)) or len(fp) != 4:
            raise EnvelopeError("walletFp must be 4 bytes")
        atomic = body["atomicBeef"]
        if not isinstance(atomic, (bytes, bytearray)):
            raise EnvelopeError("atomicBeef must be bytes")
        receipt = None
        if "stateReceipt" in body:
            receipt = StateReceipt.from_cbor(body["stateReceipt"], nested=True)
        return cls(
            wallet_fp=bytes(fp),
            atomic_beef=bytes(atomic),
            state_receipt=receipt,
        )


@dataclass(frozen=True)
class StateSync:
    """Companion -> Pi delivery of confirmed wallet transactions."""

    KIND: ClassVar[str] = KIND_STATE_SYNC

    wallet_fp: bytes
    request_id: str
    expected_revision: int
    expected_state_hash: bytes
    next_receive_index: int
    next_change_index: int
    coins: tuple[StateSyncCoin, ...]
    header_anchors: dict[int, bytes]

    def to_cbor(self) -> dict[str, Any]:
        return {
            "v": ENVELOPE_VERSION,
            "kind": self.KIND,
            "walletFp": self.wallet_fp,
            "requestId": self.request_id,
            "expectedRevision": self.expected_revision,
            "expectedStateHash": self.expected_state_hash,
            "nextReceiveIndex": self.next_receive_index,
            "nextChangeIndex": self.next_change_index,
            "coins": [c.to_cbor() for c in self.coins],
            "headerAnchors": {str(h): root for h, root in sorted(self.header_anchors.items())},
        }

    @classmethod
    def from_cbor(cls, body: dict[str, Any]) -> StateSync:
        _require_keys(
            body,
            {
                "walletFp",
                "requestId",
                "expectedRevision",
                "expectedStateHash",
                "nextReceiveIndex",
                "nextChangeIndex",
                "coins",
                "headerAnchors",
            },
            cls.KIND,
        )
        fp = _decode_fingerprint(body["walletFp"])
        request_id = str(body["requestId"]).strip()
        if not request_id or len(request_id) > 128:
            raise EnvelopeError("stateSync.requestId must be 1..128 characters")
        expected_revision = int(body["expectedRevision"])
        expected_hash = body["expectedStateHash"]
        if expected_revision < 0:
            raise EnvelopeError("stateSync.expectedRevision must be non-negative")
        if not isinstance(expected_hash, (bytes, bytearray)) or len(expected_hash) != 32:
            raise EnvelopeError("stateSync.expectedStateHash must be 32 bytes")
        next_receive = int(body["nextReceiveIndex"])
        next_change = int(body["nextChangeIndex"])
        if not (
            0 <= next_receive < MAX_DERIVATION_INDEX and 0 <= next_change < MAX_DERIVATION_INDEX
        ):
            raise EnvelopeError("stateSync counters must be valid non-hardened indices")
        raw_coins = body["coins"]
        if not isinstance(raw_coins, list) or not raw_coins:
            raise EnvelopeError("stateSync.coins must be a non-empty list")
        coins = tuple(_decode_state_sync_coin(c) for c in raw_coins)
        anchors = _decode_header_anchors(body["headerAnchors"], "stateSync")
        return cls(
            wallet_fp=fp,
            request_id=request_id,
            expected_revision=expected_revision,
            expected_state_hash=bytes(expected_hash),
            next_receive_index=next_receive,
            next_change_index=next_change,
            coins=coins,
            header_anchors=anchors,
        )


@dataclass(frozen=True)
class StateReceipt:
    """Pi-authored receipt for an atomic wallet-state transition."""

    KIND: ClassVar[str] = KIND_STATE_RECEIPT

    wallet_fp: bytes
    request_id: str
    old_revision: int
    new_revision: int
    old_state_hash: bytes
    new_state_hash: bytes
    added_coins: tuple[StateCoin, ...] = ()
    removed_outpoints: tuple[str, ...] = ()

    def to_cbor(self, *, include_header: bool = True) -> dict[str, Any]:
        body: dict[str, Any] = {
            "walletFp": self.wallet_fp,
            "requestId": self.request_id,
            "oldRevision": self.old_revision,
            "newRevision": self.new_revision,
            "oldStateHash": self.old_state_hash,
            "newStateHash": self.new_state_hash,
            "addedCoins": [c.to_cbor() for c in self.added_coins],
            "removedOutpoints": list(self.removed_outpoints),
        }
        if include_header:
            body = {"v": ENVELOPE_VERSION, "kind": self.KIND, **body}
        return body

    @classmethod
    def from_cbor(cls, body: Any, *, nested: bool = False) -> StateReceipt:
        if not isinstance(body, dict):
            raise EnvelopeError("stateReceipt must be a map")
        _require_keys(
            body,
            {
                "walletFp",
                "requestId",
                "oldRevision",
                "newRevision",
                "oldStateHash",
                "newStateHash",
                "addedCoins",
                "removedOutpoints",
            },
            "stateReceipt",
        )
        old_hash = body["oldStateHash"]
        new_hash = body["newStateHash"]
        if not isinstance(old_hash, (bytes, bytearray)) or len(old_hash) != 32:
            raise EnvelopeError("stateReceipt.oldStateHash must be 32 bytes")
        if not isinstance(new_hash, (bytes, bytearray)) or len(new_hash) != 32:
            raise EnvelopeError("stateReceipt.newStateHash must be 32 bytes")
        old_revision = int(body["oldRevision"])
        new_revision = int(body["newRevision"])
        if old_revision < 0 or new_revision != old_revision + 1:
            raise EnvelopeError("stateReceipt revision transition is invalid")
        raw_added = body["addedCoins"]
        raw_removed = body["removedOutpoints"]
        if not isinstance(raw_added, list) or not isinstance(raw_removed, list):
            raise EnvelopeError("stateReceipt coin delta must be arrays")
        request_id = str(body["requestId"]).strip()
        if not request_id or len(request_id) > 128:
            raise EnvelopeError("stateReceipt.requestId must be 1..128 characters")
        removed = tuple(str(v) for v in raw_removed)
        if any(not _valid_outpoint(value) for value in removed):
            raise EnvelopeError("stateReceipt removedOutpoints entry is invalid")
        return cls(
            wallet_fp=_decode_fingerprint(body["walletFp"]),
            request_id=request_id,
            old_revision=old_revision,
            new_revision=new_revision,
            old_state_hash=bytes(old_hash),
            new_state_hash=bytes(new_hash),
            added_coins=tuple(_decode_state_coin(c) for c in raw_added),
            removed_outpoints=removed,
        )


def _decode_fingerprint(raw: Any) -> bytes:
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != 4:
        raise EnvelopeError("walletFp must be 4 bytes")
    return bytes(raw)


def _decode_state_coin(raw: Any) -> StateCoin:
    if not isinstance(raw, dict):
        raise EnvelopeError("state coin must be a map")
    _require_keys(
        raw,
        {"txid", "vout", "sats", "script", "derivation", "status", "txRef", "height"},
        "state coin",
    )
    derivation = raw["derivation"]
    if not isinstance(derivation, (list, tuple)) or len(derivation) != 2:
        raise EnvelopeError("state coin derivation must be [branch, index]")
    txid = str(raw["txid"])
    if not _valid_txid(txid):
        raise EnvelopeError("state coin txid must be 64 hex characters")
    coin = StateCoin(
        txid=txid,
        vout=int(raw["vout"]),
        sats=int(raw["sats"]),
        locking_script=str(raw["script"]),
        derivation=(int(derivation[0]), int(derivation[1])),
        status=str(raw["status"]),
        transaction_reference=str(raw["txRef"]),
        block_height=int(raw["height"]),
    )
    if (
        coin.vout < 0
        or coin.sats <= 0
        or coin.block_height < 0
        or coin.derivation[0] not in {0, 1}
        or not 0 <= coin.derivation[1] < MAX_DERIVATION_INDEX
        or not _valid_hex(coin.locking_script)
        or not _valid_txid(coin.transaction_reference)
    ):
        raise EnvelopeError("state coin numeric fields are invalid")
    if coin.status not in {"confirmed", "pending"}:
        raise EnvelopeError("state coin status must be confirmed or pending")
    if (coin.status == "confirmed") != (coin.block_height > 0):
        raise EnvelopeError("state coin status does not match its block height")
    return coin


def _decode_state_sync_coin(raw: Any) -> StateSyncCoin:
    coin = _decode_state_coin(raw)
    atomic = raw.get("atomicBeef")
    if not isinstance(atomic, (bytes, bytearray)):
        raise EnvelopeError("stateSync coin atomicBeef must be bytes")
    if coin.status != "confirmed" or coin.block_height <= 0:
        raise EnvelopeError("stateSync coins must be confirmed")
    return StateSyncCoin(coin=coin, atomic_beef=bytes(atomic))


def _decode_header_anchors(raw: Any, context: str) -> dict[int, bytes]:
    if not isinstance(raw, dict):
        raise EnvelopeError(f"{context}.headerAnchors must be a map")
    anchors: dict[int, bytes] = {}
    for raw_height, raw_root in raw.items():
        height = int(raw_height)
        if height < 0 or not isinstance(raw_root, (bytes, bytearray)) or len(raw_root) != 32:
            raise EnvelopeError(f"{context}.headerAnchors[{height}] is invalid")
        anchors[height] = bytes(raw_root)
    if not anchors:
        raise EnvelopeError(f"{context}.headerAnchors must not be empty")
    return anchors


def _valid_txid(value: str) -> bool:
    return len(value) == 64 and _valid_hex(value)


def _valid_hex(value: str) -> bool:
    return len(value) % 2 == 0 and bool(value) and all(c in "0123456789abcdefABCDEF" for c in value)


def _valid_outpoint(value: str) -> bool:
    txid, separator, raw_vout = value.partition(":")
    return _valid_txid(txid) and separator == ":" and raw_vout.isdigit()


# ---------------------------------------------------------------------------
# Codec entrypoints.
# ---------------------------------------------------------------------------

Envelope = XpubExport | UnsignedProposal | SignedTx | StateSync | StateReceipt


def encode(envelope: Envelope) -> bytes:
    """Serialize an envelope to CBOR + gzip bytes for QR transport."""
    cbor_bytes = cbor2.dumps(envelope.to_cbor())
    return gzip.compress(cbor_bytes, compresslevel=9, mtime=0)


def decode(blob: bytes) -> Envelope:
    """Parse `blob` (CBOR + gzip) into the appropriate envelope dataclass.

    Raises `EnvelopeError` on:
    - corrupted gzip / CBOR
    - unknown schema version
    - unknown kind
    - missing or wrongly-typed required fields
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise EnvelopeError("envelope blob must be bytes")
    try:
        cbor_bytes = gzip.decompress(blob)
    except (OSError, EOFError) as exc:
        raise EnvelopeError(f"gzip decompress failed: {exc}") from exc
    try:
        body = cbor2.loads(cbor_bytes)
    except cbor2.CBORDecodeError as exc:
        raise EnvelopeError(f"CBOR decode failed: {exc}") from exc

    if not isinstance(body, dict):
        raise EnvelopeError(f"top-level CBOR must be a map, got {type(body).__name__}")
    version = body.get("v")
    if version != ENVELOPE_VERSION:
        raise EnvelopeError(f"unsupported envelope version: {version!r}")
    kind = body.get("kind")
    if kind not in VALID_KINDS:
        raise EnvelopeError(f"unknown envelope kind: {kind!r}")

    if kind == KIND_XPUB_EXPORT:
        return XpubExport.from_cbor(body)
    if kind == KIND_UNSIGNED_PROPOSAL:
        return UnsignedProposal.from_cbor(body)
    if kind == KIND_SIGNED_TX:
        return SignedTx.from_cbor(body)
    if kind == KIND_STATE_SYNC:
        return StateSync.from_cbor(body)
    if kind == KIND_STATE_RECEIPT:
        return StateReceipt.from_cbor(body)
    raise EnvelopeError(f"no decoder for kind {kind!r}")  # unreachable


def _require_keys(body: dict[str, Any], required: set[str], context: str) -> None:
    missing = required - set(body.keys())
    if missing:
        raise EnvelopeError(f"{context}: missing required key(s) {sorted(missing)}")
