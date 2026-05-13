"""CBOR-coded versioned envelopes that travel between Pi and PWA over QR.

Three message kinds are defined for v1; all share a small header so a receiver
can route them to the right handler before decoding the rest:

- `xpub_export`        Pi -> phone, on pairing. Contains the account xpub.
- `unsigned_proposal`  phone -> Pi, on send. Contains the unsigned tx, BEEF
                       per input, MerklePaths, header anchors, change index.
- `signed_tx`          Pi -> phone, after successful sign. Contains the raw
                       signed tx hex and txid.

On-the-wire encoding is **CBOR + gzip**. Larger blobs are split into
``PW1|`` multipart barcode lines in :mod:`piwallet.qr`; that layer is
intentionally separate from this codec.

Schema versioning: every payload carries `v: 1`. Bump on breaking changes;
the receiver MUST refuse unknown versions.

The CBOR shapes are deliberately flat dicts with short string keys to keep
multipart QR payloads small.
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from typing import Any, ClassVar

import cbor2

ENVELOPE_VERSION: int = 1
"""Current envelope schema version. Bump for breaking changes."""

KIND_XPUB_EXPORT: str = "xpub"
KIND_UNSIGNED_PROPOSAL: str = "tx"
KIND_SIGNED_TX: str = "signed"

VALID_KINDS: frozenset[str] = frozenset({KIND_XPUB_EXPORT, KIND_UNSIGNED_PROPOSAL, KIND_SIGNED_TX})


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
                f"network 'net' must be one of {sorted(VALID_NETWORKS)!r}; "
                f"got {net!r}"
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

    `beef` is the full BEEF bytes covering the prior tx that funds this input.
    `merkle_path` is the structured MerklePath bytes (as `to_binary()`).
    `derivation` is the index pair this input's key was derived from
    (change, index). The Pi uses it to derive the matching signing key.
    """

    txid: str
    vout: int
    sats: int
    beef: bytes
    merkle_path: bytes
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
class UnsignedProposal:
    """Phone -> Pi spend request. The Pi MUST verify before signing.

    `change_derivation` is a `(branch, index)` pair the Pi uses to re-derive
    the change output's address from the wallet's account xpub. If the
    re-derived address doesn't match the script at `outputs[change_index]`,
    signing must abort. This is the plan's "verify, then sign" rule.
    """

    KIND: ClassVar[str] = KIND_UNSIGNED_PROPOSAL

    wallet_fp: bytes
    inputs: tuple[ProposalInput, ...]
    outputs: tuple[ProposalOutput, ...]
    change_index: int  # index in `outputs` that the Pi must re-derive
    change_derivation: tuple[int, int]  # (branch, index) for the change address
    fee_rate_satskb: int
    locktime: int = 0
    header_anchors: dict[int, bytes] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.header_anchors is None:
            object.__setattr__(self, "header_anchors", {})

    def to_cbor(self) -> dict[str, Any]:
        return {
            "v": ENVELOPE_VERSION,
            "kind": self.KIND,
            "walletFp": self.wallet_fp,
            "inputs": [
                {
                    "txid": ip.txid,
                    "vout": ip.vout,
                    "sats": ip.sats,
                    "beef": ip.beef,
                    "merklePath": ip.merkle_path,
                    "derivation": list(ip.derivation),
                }
                for ip in self.inputs
            ],
            "outputs": [{"script": op.script_hex, "sats": op.sats} for op in self.outputs],
            "changeIndex": self.change_index,
            "changeDerivation": list(self.change_derivation),
            "feeRate": self.fee_rate_satskb,
            "locktime": self.locktime,
            "headerAnchors": {h: r for h, r in self.header_anchors.items()},
        }

    @classmethod
    def from_cbor(cls, body: dict[str, Any]) -> UnsignedProposal:
        _require_keys(
            body,
            {"walletFp", "inputs", "outputs", "changeIndex", "changeDerivation", "feeRate"},
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

        anchors_raw = body.get("headerAnchors") or {}
        header_anchors: dict[int, bytes] = {}
        for h, r in anchors_raw.items():
            if not isinstance(r, (bytes, bytearray)) or len(r) != 32:
                raise EnvelopeError(f"header anchor at height {h} must be 32 bytes")
            header_anchors[int(h)] = bytes(r)

        return cls(
            wallet_fp=bytes(wallet_fp),
            inputs=inputs,
            outputs=outputs,
            change_index=change_index,
            change_derivation=change_derivation,
            fee_rate_satskb=int(body["feeRate"]),
            locktime=int(body.get("locktime", 0)),
            header_anchors=header_anchors,
        )


def _decode_input(raw: Any) -> ProposalInput:
    if not isinstance(raw, dict):
        raise EnvelopeError("each input must be a dict")
    _require_keys(raw, {"txid", "vout", "sats", "beef", "merklePath", "derivation"}, "input")
    deriv = raw["derivation"]
    if not (isinstance(deriv, (list, tuple)) and len(deriv) == 2):
        raise EnvelopeError("input.derivation must be [change, index]")
    return ProposalInput(
        txid=str(raw["txid"]),
        vout=int(raw["vout"]),
        sats=int(raw["sats"]),
        beef=bytes(raw["beef"]),
        merkle_path=bytes(raw["merklePath"]),
        derivation=(int(deriv[0]), int(deriv[1])),
    )


def _decode_output(raw: Any) -> ProposalOutput:
    if not isinstance(raw, dict):
        raise EnvelopeError("each output must be a dict")
    _require_keys(raw, {"script", "sats"}, "output")
    return ProposalOutput(script_hex=str(raw["script"]), sats=int(raw["sats"]))


@dataclass(frozen=True)
class SignedTx:
    """Pi -> phone signed transaction payload."""

    KIND: ClassVar[str] = KIND_SIGNED_TX

    wallet_fp: bytes
    raw_hex: str
    txid: str

    def to_cbor(self) -> dict[str, Any]:
        return {
            "v": ENVELOPE_VERSION,
            "kind": self.KIND,
            "walletFp": self.wallet_fp,
            "rawHex": self.raw_hex,
            "txid": self.txid,
        }

    @classmethod
    def from_cbor(cls, body: dict[str, Any]) -> SignedTx:
        _require_keys(body, {"walletFp", "rawHex", "txid"}, cls.KIND)
        fp = body["walletFp"]
        if not isinstance(fp, (bytes, bytearray)) or len(fp) != 4:
            raise EnvelopeError("walletFp must be 4 bytes")
        return cls(
            wallet_fp=bytes(fp),
            raw_hex=str(body["rawHex"]),
            txid=str(body["txid"]),
        )


# ---------------------------------------------------------------------------
# Codec entrypoints.
# ---------------------------------------------------------------------------

Envelope = XpubExport | UnsignedProposal | SignedTx


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
    raise EnvelopeError(f"no decoder for kind {kind!r}")  # unreachable


def _require_keys(body: dict[str, Any], required: set[str], context: str) -> None:
    missing = required - set(body.keys())
    if missing:
        raise EnvelopeError(f"{context}: missing required key(s) {sorted(missing)}")
