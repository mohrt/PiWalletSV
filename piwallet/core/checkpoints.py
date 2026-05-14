"""Hard-coded BSV header checkpoints baked into firmware.

A checkpoint is the **absolute trust anchor** for the Pi's SPV
machinery: the companion ships a contiguous chain of block headers
that descends from this checkpoint to the deepest input's block
height (plus the configured confirmation depth), and
:func:`piwallet.core.headers.verify_chain` walks that chain forward
applying per-header PoW + linkage checks.

Tradeoff between checkpoint *recency* and per-proposal QR size:

- A genesis-block checkpoint is incorruptible (the genesis hash is
  the same in every Bitcoin / BSV implementation since 2009) but
  forces the companion to ship every header since 2009 ​​—​​
  ~870 000 headers ≈ 70 MB, intractable over a multipart-QR
  transport.
- A recent checkpoint (say, 4 weeks of confirmations ago) requires
  the operator to *trust the firmware that baked it in*, but lets
  the companion ship only ~4 000 headers (~320 KB) per proposal.

The reference implementation keeps **both** entries below: genesis
as an unconditional fallback that any operator can verify against
public sources, and a recent checkpoint as the practical default.
The recent checkpoint is **expected to be refreshed with every
firmware release**; see "Update procedure" below for the exact
steps and what to commit alongside any change.

This module is deliberately data-only: it does not import
:mod:`piwallet.core.headers` for the :class:`CheckpointHeader`
dataclass (which would create an import cycle once headers.py
imports from anywhere). Callers compose the two by passing
``CheckpointHeader(**MAINNET_RECENT)`` (or similar) into
``verify_chain``.

Update procedure
----------------

1. Pick a block at least 4 weeks deep on the target network. WoC's
   ``GET /block/<hash>/header`` returns the 80-byte header bytes;
   any BSV explorer with a full archive is also fine.
2. Sanity-check the height + hash against at least two independent
   sources to defend against an explorer being compromised at the
   moment you query it.
3. Update :data:`MAINNET_RECENT` (or :data:`TESTNET_RECENT`) below
   with the new ``height``, ``hash``, ``raw_header_hex``, and the
   short ``source`` annotation.
4. Run ``pytest tests/test_checkpoints.py``: the tests cross-check
   each baked-in entry's hash against ``header_hash(raw_header_hex)``
   and ensure heights are monotonic across releases.
5. Bump the firmware version and note the checkpoint update in the
   release notes — operators upgrading from a stale build will see
   the same proposal-time chain length they're used to, with the
   new checkpoint as the visible trust anchor on the bonnet.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HardcodedCheckpoint:
    """A baked-in firmware checkpoint.

    ``raw_header_hex`` is the 80-byte block header at ``height`` in
    its standard wire encoding (little-endian fields, raw byte-order
    hashes — i.e. the value WoC returns from
    ``GET /block/<hash>/header``). It is kept alongside ``hash`` so
    the unit tests can recompute the double-SHA256 and pin both
    values in one place.

    ``source`` is a short free-text note (e.g. "WoC + sv-cli
    block-data, 2026-05-01") so a future operator looking at a
    suspicious checkpoint can reproduce the verification we did
    when we baked it in.
    """

    network: str  # "main" | "test"
    height: int
    hash_hex: str  # displayed (big-endian) form, 64 hex chars
    raw_header_hex: str  # 80-byte serialized header (160 hex chars)
    source: str


# ---- Bitcoin / BSV mainnet -----------------------------------------------

MAINNET_GENESIS: HardcodedCheckpoint = HardcodedCheckpoint(
    network="main",
    height=0,
    hash_hex="000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f",
    raw_header_hex=(
        "01000000"
        "0000000000000000000000000000000000000000000000000000000000000000"
        "3ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a"
        "29ab5f49"
        "ffff001d"
        "1dac2b7c"
    ),
    source=(
        "Bitcoin / BSV genesis block, hard-coded since 2009 in every "
        "implementation. Public-domain knowledge."
    ),
)

# Recent mainnet checkpoint. Refresh with every firmware release
# following the "Update procedure" in this module's docstring.
#
# This file ships an entry that is INTENTIONALLY just the genesis
# checkpoint duplicated under a different name. A firmware build that
# leaves this here will work — the SPV machinery will simply require
# the companion to ship a chain from genesis — but the QR-payload
# size will be impractical. Real production builds MUST replace
# this with a recent height + header from the public chain. The
# `tests/test_checkpoints.py` suite verifies the hash matches the
# raw header bytes; it does NOT enforce that the checkpoint is
# "recent enough" because that is a release-process concern, not a
# wire-format invariant.
MAINNET_RECENT: HardcodedCheckpoint = MAINNET_GENESIS


# ---- BSV testnet ---------------------------------------------------------

TESTNET_GENESIS: HardcodedCheckpoint = HardcodedCheckpoint(
    network="test",
    height=0,
    hash_hex="000000000933ea01ad0ee984209779baaec3ced90fa3f408719526f8d77f4943",
    raw_header_hex=(
        "01000000"
        "0000000000000000000000000000000000000000000000000000000000000000"
        "3ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a"
        "dae5494d"
        "ffff001d"
        "1aa4ae18"
    ),
    source=(
        "Bitcoin / BSV testnet3 genesis block, public-domain since 2011."
    ),
)

TESTNET_RECENT: HardcodedCheckpoint = TESTNET_GENESIS


# ---- Lookup helpers ------------------------------------------------------


ALL_CHECKPOINTS: tuple[HardcodedCheckpoint, ...] = (
    MAINNET_GENESIS,
    MAINNET_RECENT,
    TESTNET_GENESIS,
    TESTNET_RECENT,
)


def for_network(network: str) -> HardcodedCheckpoint:
    """Return the *recent* checkpoint for ``network``.

    ``network`` is ``"main"`` or ``"test"`` (matching
    :data:`piwallet.core.envelope.VALID_NETWORKS`). Falls through to
    the genesis entry if no recent override is configured for the
    requested network — see the module docstring for why a firmware
    that hasn't refreshed its checkpoint will still function (just
    with much larger QR payloads).
    """
    if network == "main":
        return MAINNET_RECENT
    if network == "test":
        return TESTNET_RECENT
    raise ValueError(
        f"unknown network {network!r}; expected 'main' or 'test'"
    )


__all__ = [
    "ALL_CHECKPOINTS",
    "HardcodedCheckpoint",
    "MAINNET_GENESIS",
    "MAINNET_RECENT",
    "TESTNET_GENESIS",
    "TESTNET_RECENT",
    "for_network",
]
