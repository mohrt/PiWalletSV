"""CBOR-coded versioned envelopes that travel between Pi and PWA over QR.

Three message kinds are defined; all share a small header so a receiver
can route them to the right handler before decoding the rest:

- `xpub_export`        Pi -> phone, on pairing. Contains the account xpub.
- `unsigned_proposal`  phone -> Pi, on send. Contains the unsigned tx,
                       per-input BEEF (BRC-62), the validated header chain
                       walked from a firmware checkpoint to a tip, and the
                       change derivation index.
- `signed_tx`          Pi -> phone, after successful sign. Contains the
                       signed transaction as Atomic BEEF (BRC-95) and its
                       txid for convenience.

On-the-wire encoding is **CBOR + gzip**. Larger blobs are split into
``PW1|`` multipart barcode lines in :mod:`piwallet.qr`; that layer is
intentionally separate from this codec.

Schema versioning: every payload carries an integer ``v``. Bump on
breaking changes; the receiver MUST refuse unknown versions. v2
(this revision) replaces v1's ``headerAnchors`` (a trusted
``height -> root`` map supplied by the companion) with a raw
``headers`` chain that the Pi PoW-validates from a baked-in
checkpoint, drops the redundant standalone per-input ``merklePath``
field (the BEEF carries it), and uses Atomic BEEF (BRC-95) for the
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
"""Current envelope schema version. Bump for breaking changes.

History:
    v1 — initial release.
    v2 — drop the redundant per-input ``merklePath`` field (the BEEF
         payload already carries it); switch the ``signed_tx`` payload
         from a hex-string + separate txid to a single ``atomicBeef``
         bytes field (BRC-95). v1 envelopes are intentionally rejected
         by this build; the schema bump is the documented signal that
         a v1 producer should be upgraded.
"""

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
class UnsignedProposal:
    """Phone -> Pi spend request. The Pi MUST verify before signing.

    ``change_derivation`` is a ``(branch, index)`` pair the Pi uses to
    re-derive the change output's address from the wallet's account
    xpub. If the re-derived address doesn't match the script at
    ``outputs[change_index]``, signing must abort. This is the plan's
    "verify, then sign" rule.

    ``checkpoint_height`` and ``headers`` together carry the SPV
    chain the Pi must independently validate before trusting any
    Merkle proof in the BEEFs:

    - ``checkpoint_height`` is the height of the firmware checkpoint
      whose hash the first header's ``prev_hash`` must equal. The
      companion picks the network's recent-checkpoint height from
      :mod:`piwallet.core.checkpoints` so the Pi can refuse a stale
      / wrong-network chain at the first comparison.
    - ``headers`` is a contiguous list of 80-byte headers, in
      ascending height order, starting at ``checkpoint_height + 1``.
      Each header is independently PoW-validated by
      :func:`piwallet.core.headers.verify_chain`; the resulting
      ``height -> merkle_root`` map is what the SPV verifier uses.

    The previous schema (envelope v1) carried a
    ``header_anchors: dict[height, root]`` map directly. v2 replaces
    it with the raw header chain so the Pi no longer has to *trust*
    the companion's claimed roots — it derives them from headers it
    has independently checked.
    """

    KIND: ClassVar[str] = KIND_UNSIGNED_PROPOSAL

    wallet_fp: bytes
    inputs: tuple[ProposalInput, ...]
    outputs: tuple[ProposalOutput, ...]
    change_index: int  # index in `outputs` that the Pi must re-derive
    change_derivation: tuple[int, int]  # (branch, index) for the change address
    fee_rate_satskb: int
    checkpoint_height: int
    headers: tuple[bytes, ...] = ()
    locktime: int = 0

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
                    "derivation": list(ip.derivation),
                }
                for ip in self.inputs
            ],
            "outputs": [{"script": op.script_hex, "sats": op.sats} for op in self.outputs],
            "changeIndex": self.change_index,
            "changeDerivation": list(self.change_derivation),
            "feeRate": self.fee_rate_satskb,
            "locktime": self.locktime,
            "checkpointHeight": self.checkpoint_height,
            "headers": list(self.headers),
        }

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
                "checkpointHeight",
                "headers",
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

        checkpoint_height = int(body["checkpointHeight"])
        if checkpoint_height < 0:
            raise EnvelopeError(
                f"checkpointHeight must be non-negative, got {checkpoint_height}"
            )

        headers_raw = body["headers"]
        if not isinstance(headers_raw, list):
            raise EnvelopeError("headers must be a list of 80-byte byte strings")
        headers: list[bytes] = []
        for i, hb in enumerate(headers_raw):
            if not isinstance(hb, (bytes, bytearray)) or len(hb) != 80:
                raise EnvelopeError(
                    f"headers[{i}] must be 80 bytes, got "
                    f"{type(hb).__name__} of length "
                    f"{len(hb) if isinstance(hb, (bytes, bytearray)) else 'n/a'}"
                )
            headers.append(bytes(hb))

        return cls(
            wallet_fp=bytes(wallet_fp),
            inputs=inputs,
            outputs=outputs,
            change_index=change_index,
            change_derivation=change_derivation,
            fee_rate_satskb=int(body["feeRate"]),
            locktime=int(body.get("locktime", 0)),
            checkpoint_height=checkpoint_height,
            headers=tuple(headers),
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
        return {
            "v": ENVELOPE_VERSION,
            "kind": self.KIND,
            "walletFp": self.wallet_fp,
            "atomicBeef": self.atomic_beef,
        }

    @classmethod
    def from_cbor(cls, body: dict[str, Any]) -> SignedTx:
        _require_keys(body, {"walletFp", "atomicBeef"}, cls.KIND)
        fp = body["walletFp"]
        if not isinstance(fp, (bytes, bytearray)) or len(fp) != 4:
            raise EnvelopeError("walletFp must be 4 bytes")
        atomic = body["atomicBeef"]
        if not isinstance(atomic, (bytes, bytearray)):
            raise EnvelopeError("atomicBeef must be bytes")
        return cls(
            wallet_fp=bytes(fp),
            atomic_beef=bytes(atomic),
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
