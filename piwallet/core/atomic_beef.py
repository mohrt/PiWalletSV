"""BRC-95 Atomic BEEF (single-tx BEEF) helpers.

`Atomic BEEF`_ is a thin wrapper around a regular BRC-62 BEEF that
declares a single "subject" transaction. The wire encoding is::

    [4 bytes : magic 0x01010101 (little-endian uint32)]
    [32 bytes : subject txid in raw byte order (display hex reversed)]
    [variable : regular BRC-62 BEEF body]

The Pi emits Atomic BEEF for ``signed_tx`` envelopes so any BRC-62 /
BRC-100-aware receiver (companion, hot wallet, indexer) can treat the
signed transaction as a fully self-described atomic action without
consulting an external "which tx is the new one?" hint. The companion
already has the ancestor BEEF (it built the proposal), so the inner
BEEF body in our case will typically just describe the signed tx
itself plus whatever ancestors `bsv.Transaction.to_beef()` chose to
include given the source-transaction graph attached during signing.

This module is intentionally a small, dependency-free codec so the
on-device parse stays trivial. The ``bsv`` Python SDK in use does not
expose Atomic BEEF natively (only ``from_beef`` / ``to_beef``); we add
BRC-95 here.

.. _Atomic BEEF: https://bsv.brc.dev/transactions/0095
"""

from __future__ import annotations

from bsv import Transaction

ATOMIC_BEEF_MAGIC: bytes = b"\x01\x01\x01\x01"
"""Wire-magic prefix for Atomic BEEF (4-byte little-endian 0x01010101)."""

ATOMIC_BEEF_HEADER_LEN: int = 4 + 32
"""Magic (4) + subject TXID (32) = 36 bytes before the inner BEEF body."""


class AtomicBeefError(ValueError):
    """Raised on malformed Atomic BEEF blobs."""


def encode(tx: Transaction) -> bytes:
    """Wrap ``tx`` (and its ``source_transaction`` graph, when present)
    as Atomic BEEF.

    The subject TXID is taken from ``tx.txid()`` and written in
    raw byte order (i.e. reversed relative to the displayed hex).
    """
    body = tx.to_beef()
    if not isinstance(body, (bytes, bytearray)):
        raise AtomicBeefError(
            f"tx.to_beef() returned {type(body).__name__}, expected bytes"
        )
    txid_bytes = bytes.fromhex(tx.txid())[::-1]
    if len(txid_bytes) != 32:
        raise AtomicBeefError("subject txid must hash to 32 bytes")
    return ATOMIC_BEEF_MAGIC + txid_bytes + bytes(body)


def split(blob: bytes) -> tuple[str, bytes]:
    """Inverse of :func:`encode` for inspection / logging.

    Returns ``(subject_txid_hex, inner_beef_bytes)``. Raises
    :class:`AtomicBeefError` if ``blob`` is not in BRC-95 form.
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise AtomicBeefError("atomic beef blob must be bytes")
    b = bytes(blob)
    if len(b) < ATOMIC_BEEF_HEADER_LEN:
        raise AtomicBeefError(
            f"atomic beef blob is {len(b)} bytes; need at least "
            f"{ATOMIC_BEEF_HEADER_LEN}"
        )
    if b[:4] != ATOMIC_BEEF_MAGIC:
        raise AtomicBeefError(
            "atomic beef magic mismatch: "
            f"expected {ATOMIC_BEEF_MAGIC.hex()}, got {b[:4].hex()}"
        )
    subject_txid_hex = b[4:36][::-1].hex()
    return subject_txid_hex, b[ATOMIC_BEEF_HEADER_LEN:]


def to_transaction(blob: bytes) -> Transaction:
    """Decode an Atomic BEEF blob back into a :class:`bsv.Transaction`.

    Convenience helper that splits the BRC-95 envelope and feeds the
    inner BEEF body to :meth:`Transaction.from_beef`. The returned
    transaction's ``txid()`` is verified against the subject TXID
    declared in the BRC-95 header.
    """
    subject_txid_hex, inner = split(blob)
    try:
        tx = Transaction.from_beef(inner)
    except Exception as exc:  # noqa: BLE001 — bsv-sdk error surface is broad
        raise AtomicBeefError(f"inner BEEF parse failed: {exc}") from exc
    actual = tx.txid()
    if actual != subject_txid_hex:
        # ``from_beef`` returns the *child* (top-level) tx in the inner
        # BEEF; if a malformed blob declares a subject TXID that doesn't
        # match the top-level tx, that's a protocol violation we surface
        # rather than letting downstream verification fail with a less
        # helpful message.
        raise AtomicBeefError(
            f"subject txid {subject_txid_hex} does not match inner tx "
            f"{actual}"
        )
    return tx


__all__ = [
    "ATOMIC_BEEF_HEADER_LEN",
    "ATOMIC_BEEF_MAGIC",
    "AtomicBeefError",
    "encode",
    "split",
    "to_transaction",
]
