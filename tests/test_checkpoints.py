"""Sanity tests for piwallet.core.checkpoints.

Locks down the invariant that every baked-in checkpoint's
``hash_hex`` is exactly the double-SHA256 of its
``raw_header_hex`` — i.e. the firmware can never ship a checkpoint
where the declared hash doesn't match the bytes it claims to point
at. A failing test here means a checkpoint update was incomplete.
"""

from __future__ import annotations

import pytest

from piwallet.core import checkpoints as cp
from piwallet.core import headers as h


@pytest.mark.parametrize("entry", cp.ALL_CHECKPOINTS, ids=lambda e: f"{e.network}-{e.height}")
def test_checkpoint_hash_matches_raw_header(entry: cp.HardcodedCheckpoint) -> None:
    """``hash_hex`` is the displayed (big-endian) form of
    ``double_sha256(raw_header_hex)``. A drift here would cascade
    into a forged checkpoint accepted at runtime."""
    raw = bytes.fromhex(entry.raw_header_hex)
    assert len(raw) == h.HEADER_SIZE, (
        f"{entry.network}-{entry.height}: raw header is {len(raw)} bytes, "
        f"expected {h.HEADER_SIZE}"
    )
    expected = h.header_hash(raw)[::-1].hex()
    assert expected == entry.hash_hex.lower(), (
        f"{entry.network}-{entry.height}: hash_hex does not match "
        f"double_sha256(raw_header_hex); refresh the checkpoint or "
        "fix the typo before shipping firmware"
    )


@pytest.mark.parametrize(
    "entry", cp.ALL_CHECKPOINTS, ids=lambda e: f"{e.network}-{e.height}"
)
def test_checkpoint_pow_self_consistent(entry: cp.HardcodedCheckpoint) -> None:
    """Every baked-in header must satisfy its own PoW. This is a
    weaker invariant than 'is on the canonical chain', but it
    forces a checkpoint update to use real header bytes instead of
    a hand-rolled fixture that would otherwise look superficially
    valid."""
    raw = bytes.fromhex(entry.raw_header_hex)
    header = h.parse_header(raw)
    h.verify_pow(header)


def test_for_network_returns_recent_per_network() -> None:
    assert cp.for_network("main") is cp.MAINNET_RECENT
    assert cp.for_network("test") is cp.TESTNET_RECENT


def test_for_network_rejects_unknown_network() -> None:
    with pytest.raises(ValueError, match="unknown network"):
        cp.for_network("regtest")


def test_genesis_checkpoints_are_at_height_zero() -> None:
    assert cp.MAINNET_GENESIS.height == 0
    assert cp.TESTNET_GENESIS.height == 0


def test_recent_checkpoints_are_at_or_after_genesis() -> None:
    """A recent checkpoint may equal genesis (the default fallback)
    or live further down the chain. It must NEVER claim to be
    earlier than genesis — that would mean a typo or a corrupted
    file, never a legitimate value."""
    assert cp.MAINNET_RECENT.height >= cp.MAINNET_GENESIS.height
    assert cp.TESTNET_RECENT.height >= cp.TESTNET_GENESIS.height
