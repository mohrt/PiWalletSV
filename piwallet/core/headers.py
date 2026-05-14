"""Block-header parsing and proof-of-work validation for SPV.

This module implements the parts of `BRC-67`_ (Simplified Payment
Verification) the Pi needs to *trust* a header chain that the
companion ships across the QR boundary. Specifically:

- :func:`parse_header` decodes a fixed-width 80-byte block header
  into a :class:`BlockHeader` dataclass.
- :func:`header_hash` computes the double-SHA256 of an 80-byte
  header (in raw byte order; the displayed-hex form is the
  byte-reverse).
- :func:`bits_to_target` decodes a ``bits`` compact-target field
  into a 256-bit difficulty target.
- :func:`verify_chain` walks a sequence of consecutive headers
  starting from a baked-in ``checkpoint`` and produces a
  ``height -> merkle_root`` map the SPV verifier in
  :mod:`piwallet.core.verify` can use.

The Pi does NOT verify that each header's ``bits`` is the
*correct* difficulty for its height — implementing the BSV
difficulty-adjustment algorithm on the device would require
tracking a much wider window of consensus state and offers little
extra security against the only attacker we model here (a malicious
companion). What we *do* enforce per header is sufficient for
SPV-from-checkpoint:

1. **Linkage.** Each header's ``prev_hash`` matches the predecessor's
   double-SHA256.
2. **Self-consistent PoW.** Each header's hash interpreted as a
   little-endian 256-bit integer is less than or equal to the target
   declared by its own ``bits`` field. This is the same rule a full
   node uses to accept a block at all.

A companion that hands the Pi a chain of self-consistent low-
difficulty headers cannot forge real proofs of inclusion for a real
on-chain transaction, because the BUMP it would need to anchor would
have to root in a real block's Merkle tree — which would not be
present in a forged chain. The combination of ``verify_chain``
(headers independently validated) + BUMP (Merkle paths anchored to
those validated roots) closes the trust gap that ``header_anchors``
left open in the v1 envelope flow.

.. _BRC-67: https://bsv.brc.dev/transactions/0067
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

HEADER_SIZE: int = 80
"""Length of a Bitcoin block header on the wire (always 80 bytes)."""


class HeaderError(ValueError):
    """Raised on malformed headers, broken linkage, or failed PoW."""


@dataclass(frozen=True)
class BlockHeader:
    """A decoded 80-byte block header.

    Field semantics match Bitcoin / BSV consensus:

    - ``version`` and ``time`` / ``bits`` / ``nonce`` are little-endian
      32-bit unsigned integers.
    - ``prev_hash`` and ``merkle_root`` are 32 bytes in **raw** byte
      order (NOT the byte-reversed displayed hex form). The
      ``hash_hex`` and ``prev_hash_hex`` properties on this class
      give the displayed forms.
    - ``raw`` is the 80-byte serialization, kept for re-hashing and
      for embedding back into a parent envelope.
    """

    version: int
    prev_hash: bytes
    merkle_root: bytes
    time: int
    bits: int
    nonce: int
    raw: bytes

    @property
    def hash(self) -> bytes:
        """Double-SHA256 of ``raw``, in raw byte order (32 bytes)."""
        return header_hash(self.raw)

    @property
    def hash_hex(self) -> str:
        """Displayed (big-endian) hex of this header's hash."""
        return self.hash[::-1].hex()

    @property
    def prev_hash_hex(self) -> str:
        """Displayed (big-endian) hex of ``prev_hash``."""
        return self.prev_hash[::-1].hex()

    @property
    def merkle_root_hex(self) -> str:
        """Displayed (big-endian) hex of ``merkle_root``."""
        return self.merkle_root[::-1].hex()


def parse_header(blob: bytes) -> BlockHeader:
    """Decode an 80-byte header into a :class:`BlockHeader`.

    Raises :class:`HeaderError` if the input is not exactly 80 bytes.
    Per-field validation (PoW, linkage) is the job of
    :func:`verify_chain`; this function is purely structural.
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise HeaderError("header must be bytes")
    if len(blob) != HEADER_SIZE:
        raise HeaderError(f"header must be {HEADER_SIZE} bytes, got {len(blob)}")
    raw = bytes(blob)
    return BlockHeader(
        version=int.from_bytes(raw[0:4], "little", signed=False),
        prev_hash=raw[4:36],
        merkle_root=raw[36:68],
        time=int.from_bytes(raw[68:72], "little", signed=False),
        bits=int.from_bytes(raw[72:76], "little", signed=False),
        nonce=int.from_bytes(raw[76:80], "little", signed=False),
        raw=raw,
    )


def header_hash(blob: bytes) -> bytes:
    """Double-SHA256 of an 80-byte header, returned in raw byte order.

    The displayed (big-endian) hex form is the byte-reverse of this
    value; downstream callers that need to compare against an
    explorer-style hex should ``.[::-1].hex()`` the return value, or
    use :attr:`BlockHeader.hash_hex` instead.
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise HeaderError("header must be bytes")
    if len(blob) != HEADER_SIZE:
        raise HeaderError(f"header must be {HEADER_SIZE} bytes, got {len(blob)}")
    return hashlib.sha256(hashlib.sha256(blob).digest()).digest()


def bits_to_target(bits: int) -> int:
    """Decode a Bitcoin-style ``bits`` compact target into a 256-bit int.

    The wire encoding is::

        exponent = bits >> 24
        mantissa = bits & 0x007fffff
        sign     = bits & 0x00800000     # invalid for a difficulty target

    and the resulting target is::

        target = mantissa << (8 * (exponent - 3))   # exponent >= 3
        target = mantissa >> (8 * (3 - exponent))   # exponent <  3

    The sign bit (``0x00800000``) is reserved for arithmetic forms of
    the same compact encoding and MUST NOT appear in a header's
    ``bits`` field. We refuse to decode it rather than silently
    coercing to zero, since a malicious header could otherwise sneak
    past PoW with a "trivially satisfiable" zero target.

    Raises :class:`HeaderError` for out-of-range ``bits``.
    """
    if not isinstance(bits, int) or bits < 0 or bits > 0xFFFFFFFF:
        raise HeaderError(f"bits must be a uint32, got {bits!r}")
    sign_bit = bits & 0x00800000
    if sign_bit:
        raise HeaderError(
            f"bits 0x{bits:08x} has the sign bit set; not a valid PoW target"
        )
    exponent = (bits >> 24) & 0xFF
    mantissa = bits & 0x007FFFFF
    if mantissa == 0:
        return 0
    if exponent <= 3:
        target = mantissa >> (8 * (3 - exponent))
    else:
        target = mantissa << (8 * (exponent - 3))
    # A legitimate Bitcoin target fits in 256 bits; anything bigger is a
    # malformed header. Catching it here protects the per-header
    # comparison from a meaningless wraparound.
    if target.bit_length() > 256:
        raise HeaderError(
            f"bits 0x{bits:08x} decodes to {target.bit_length()}-bit target; "
            "exceeds 256 bits"
        )
    return target


def verify_pow(header: BlockHeader) -> None:
    """Raise if ``header`` does not satisfy its declared PoW target.

    The hash is interpreted as a little-endian uint256 (i.e. the raw
    byte order *is* the natural integer encoding for this comparison;
    no further reversal is needed). A real header has a small
    integer (lots of leading zero bytes when displayed); the target
    is the upper bound that integer must not exceed.
    """
    target = bits_to_target(header.bits)
    h = int.from_bytes(header.hash, "little", signed=False)
    if h > target:
        raise HeaderError(
            f"header {header.hash_hex} fails PoW: hash > target "
            f"(target=0x{target:064x})"
        )


@dataclass(frozen=True)
class CheckpointHeader:
    """A baked-in trusted starting point for a header-chain walk.

    The Pi ships with a small set of these in :mod:`piwallet.core.
    checkpoints`. The companion's job at proposal time is to send a
    contiguous chain of headers starting at ``height + 1`` whose
    first header's ``prev_hash`` equals this checkpoint's ``hash``.
    """

    height: int
    hash: bytes
    """Double-SHA256 of the checkpoint's 80-byte header, raw byte order."""

    def __post_init__(self) -> None:
        if not isinstance(self.hash, (bytes, bytearray)) or len(self.hash) != 32:
            raise HeaderError("checkpoint hash must be 32 bytes")
        if self.height < 0:
            raise HeaderError(f"checkpoint height must be non-negative, got {self.height}")


def verify_chain(
    headers: Iterable[bytes],
    checkpoint: CheckpointHeader,
) -> dict[int, bytes]:
    """Walk a chain of consecutive 80-byte headers from ``checkpoint``.

    On success, returns ``{height: merkle_root}`` for every header in
    the input. The map's heights start at ``checkpoint.height + 1``
    and are dense (no gaps).

    Each header is validated for:

    1. Structural integrity (80 bytes, fields decode).
    2. **Chain linkage.** Header ``i``'s ``prev_hash`` must equal
       header ``i-1``'s ``double_sha256``; header ``0``'s
       ``prev_hash`` must equal ``checkpoint.hash``.
    3. **Self-consistent PoW.** ``hash <= bits_to_target(bits)``.

    The function is intentionally pure / stateless: it does not
    consult any external chain database, does not persist anything,
    and does not enforce difficulty-adjustment rules. The only thing
    a caller hard-trusts is the checkpoint hash + height — every
    other byte of input is derived structurally from public network
    data the companion already needed to fetch to build the proposal.

    Raises :class:`HeaderError` with a short, single-line message
    suitable for the bonnet display on the first failing header.
    """
    parsed: list[BlockHeader] = []
    expected_prev = bytes(checkpoint.hash)
    base_height = checkpoint.height
    out: dict[int, bytes] = {}

    for offset, blob in enumerate(headers):
        height = base_height + offset + 1
        try:
            h = parse_header(blob)
        except HeaderError as exc:
            raise HeaderError(f"height {height}: {exc}") from exc

        if h.prev_hash != expected_prev:
            raise HeaderError(
                f"height {height}: prev_hash mismatch "
                f"(expected {expected_prev[::-1].hex()}, got {h.prev_hash_hex})"
            )

        try:
            verify_pow(h)
        except HeaderError as exc:
            raise HeaderError(f"height {height}: {exc}") from exc

        parsed.append(h)
        out[height] = h.merkle_root
        expected_prev = h.hash

    if not parsed:
        # An empty chain is a programmer error; verify_chain's contract
        # is that a chain of length N produces N entries. The bonnet
        # surface refuses to sign without anchored inputs anyway, but
        # we surface a clear message here for operators who hit this
        # via the CLI.
        raise HeaderError("verify_chain called with an empty header sequence")

    return out


__all__ = [
    "BlockHeader",
    "CheckpointHeader",
    "HEADER_SIZE",
    "HeaderError",
    "bits_to_target",
    "header_hash",
    "parse_header",
    "verify_chain",
    "verify_pow",
]
