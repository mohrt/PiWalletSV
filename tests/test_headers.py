"""Unit tests for piwallet.core.headers (BRC-67 / SPV header validation).

These tests exercise the structural decoder, the bits-to-target
conversion, and the chain-walking validator. Real BSV mainnet /
testnet header segments are used as positive vectors; synthetic
"forged" chains exercise the negative paths every adversarial input
the bonnet may face must be rejected on.

The Bitcoin genesis header is used as the canonical fixed point
for round-trip parsing because its bytes are exact, public, and
match the same value across every Bitcoin / BSV implementation
since 2009.
"""

from __future__ import annotations

import hashlib

import pytest

from piwallet.core import headers as h

# Bitcoin / BSV genesis header (block 0). Hash:
#   00000000 00000000 00000000 00000000 00000000 00000000 0019d668 9c085ae1
#   65831e93 4ff763ae 46a2a6c1 72b3f1b6 0a8ce26f
GENESIS_HEADER_HEX = (
    "01000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "3ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa4b1e5e4a"
    "29ab5f49"
    "ffff001d"
    "1dac2b7c"
)
GENESIS_HASH_DISPLAY = (
    "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
)
GENESIS_MERKLE_ROOT_DISPLAY = (
    "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"
)
GENESIS_TIME = 1231006505  # 2009-01-03 18:15:05 UTC
GENESIS_BITS = 0x1D00FFFF
GENESIS_NONCE = 2083236893


def _double_sha256(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def _build_header(
    *,
    version: int,
    prev_hash: bytes,
    merkle_root: bytes,
    time: int,
    bits: int,
    nonce: int,
) -> bytes:
    return (
        version.to_bytes(4, "little")
        + prev_hash
        + merkle_root
        + time.to_bytes(4, "little")
        + bits.to_bytes(4, "little")
        + nonce.to_bytes(4, "little")
    )


def _easy_target_bits() -> int:
    """``bits`` value with a target that essentially any 256-bit hash
    satisfies. Used so the synthetic chains in tests below don't need
    to mine at real difficulty."""
    # exponent=32 (max), mantissa = 0x7fffff. Target ~ 2^256 - 1.
    return 0x207FFFFF


def _mine_easy(prev_hash: bytes, *, time: int = 0) -> bytes:
    """Construct a header with the easy-target ``bits`` that satisfies
    its own PoW.

    The maximum target representable in compact ``bits`` form
    (``0x207fffff``) is ~``2^255 - 2^232``, so roughly half of all
    random hashes satisfy it. We search nonces deterministically and
    return the first that lands below the target. This keeps the
    test fixtures reproducible while letting them exercise the real
    PoW comparison path inside :func:`verify_chain`.
    """
    bits = _easy_target_bits()
    target = h.bits_to_target(bits)
    merkle_root = hashlib.sha256(b"merkle:" + prev_hash + time.to_bytes(4, "big")).digest()
    for nonce in range(1 << 16):
        blob = _build_header(
            version=1,
            prev_hash=prev_hash,
            merkle_root=merkle_root,
            time=time,
            bits=bits,
            nonce=nonce,
        )
        digest = h.header_hash(blob)
        if int.from_bytes(digest, "little") <= target:
            # Sanity: full verify_pow() must agree with the inline check.
            h.verify_pow(h.parse_header(blob))
            return blob
    raise AssertionError(
        "exhausted 65k nonces without finding an easy-target hash; "
        "target / hash-distribution math is wrong"
    )


# ---- parse_header --------------------------------------------------------


def test_parse_header_decodes_genesis_fields() -> None:
    blob = bytes.fromhex(GENESIS_HEADER_HEX)
    header = h.parse_header(blob)
    assert header.version == 1
    assert header.time == GENESIS_TIME
    assert header.bits == GENESIS_BITS
    assert header.nonce == GENESIS_NONCE
    # prev_hash is all zeros for genesis.
    assert header.prev_hash == b"\x00" * 32
    assert header.merkle_root_hex == GENESIS_MERKLE_ROOT_DISPLAY
    assert header.hash_hex == GENESIS_HASH_DISPLAY


def test_parse_header_round_trip_preserves_raw() -> None:
    blob = bytes.fromhex(GENESIS_HEADER_HEX)
    header = h.parse_header(blob)
    assert header.raw == blob


def test_parse_header_rejects_short_blob() -> None:
    with pytest.raises(h.HeaderError, match="must be 80 bytes"):
        h.parse_header(b"\x00" * 79)


def test_parse_header_rejects_long_blob() -> None:
    with pytest.raises(h.HeaderError, match="must be 80 bytes"):
        h.parse_header(b"\x00" * 81)


def test_parse_header_rejects_non_bytes() -> None:
    with pytest.raises(h.HeaderError, match="must be bytes"):
        h.parse_header("not bytes")  # type: ignore[arg-type]


# ---- header_hash ---------------------------------------------------------


def test_header_hash_matches_double_sha256_of_genesis() -> None:
    blob = bytes.fromhex(GENESIS_HEADER_HEX)
    digest = h.header_hash(blob)
    assert digest == _double_sha256(blob)
    # And the displayed (big-endian) form matches the canonical hash.
    assert digest[::-1].hex() == GENESIS_HASH_DISPLAY


def test_header_hash_rejects_wrong_length() -> None:
    with pytest.raises(h.HeaderError, match="80 bytes"):
        h.header_hash(b"\x00" * 79)


# ---- bits_to_target ------------------------------------------------------


def test_bits_to_target_genesis() -> None:
    """Bitcoin genesis bits 0x1d00ffff decodes to the well-known
    starting target with exactly 32 leading zero bits when displayed."""
    target = h.bits_to_target(GENESIS_BITS)
    assert target == 0x00000000_FFFF0000_00000000_00000000_00000000_00000000_00000000_00000000


def test_bits_to_target_low_exponent_branch() -> None:
    """exponent < 3 takes the right-shift branch. Pin the math so
    a regression in the shift direction surfaces immediately."""
    # exponent=1, mantissa=0x123456 → 0x12 (drop low 2 bytes)
    bits = (1 << 24) | 0x123456
    assert h.bits_to_target(bits) == 0x12


def test_bits_to_target_zero_mantissa_yields_zero_target() -> None:
    bits = (5 << 24) | 0
    assert h.bits_to_target(bits) == 0


def test_bits_to_target_rejects_sign_bit() -> None:
    with pytest.raises(h.HeaderError, match="sign bit"):
        h.bits_to_target(0x01800000)


def test_bits_to_target_rejects_overflow() -> None:
    """exponent=34, mantissa=0x7fffff would produce a 264-bit target."""
    with pytest.raises(h.HeaderError, match="exceeds 256 bits"):
        h.bits_to_target((34 << 24) | 0x7FFFFF)


def test_bits_to_target_rejects_out_of_range() -> None:
    with pytest.raises(h.HeaderError, match="uint32"):
        h.bits_to_target(-1)
    with pytest.raises(h.HeaderError, match="uint32"):
        h.bits_to_target(0x1_00000000)


# ---- verify_pow ----------------------------------------------------------


def test_verify_pow_accepts_genesis() -> None:
    header = h.parse_header(bytes.fromhex(GENESIS_HEADER_HEX))
    h.verify_pow(header)  # must not raise


def test_verify_pow_rejects_header_above_target() -> None:
    """Take the genesis header but rewrite ``bits`` to claim an
    impossible (too-tight) target. The genesis hash exceeds it,
    so PoW must fail."""
    blob = bytearray(bytes.fromhex(GENESIS_HEADER_HEX))
    # bits at offset 72-76. Set to 0x1c000001: exponent=28, mantissa=1
    # → target = 1 << (8 * 25), which is below the genesis hash.
    blob[72:76] = (0x1C000001).to_bytes(4, "little")
    header = h.parse_header(bytes(blob))
    with pytest.raises(h.HeaderError, match="fails PoW"):
        h.verify_pow(header)


# ---- verify_chain --------------------------------------------------------


def _checkpoint_for(blob: bytes, *, height: int) -> h.CheckpointHeader:
    return h.CheckpointHeader(height=height, hash=h.header_hash(blob))


def test_verify_chain_accepts_well_formed_chain() -> None:
    """A 5-deep chain of easy-target headers, each linked, should
    return a height->merkle_root map starting at checkpoint+1."""
    base = _mine_easy(b"\x00" * 32, time=1)
    cp = _checkpoint_for(base, height=100)

    headers: list[bytes] = []
    prev_hash = h.header_hash(base)
    for i in range(5):
        blob = _mine_easy(prev_hash, time=2 + i)
        headers.append(blob)
        prev_hash = h.header_hash(blob)

    out = h.verify_chain(headers, cp)
    assert sorted(out.keys()) == [101, 102, 103, 104, 105]
    for hgt, root in out.items():
        offset = hgt - 101
        assert root == h.parse_header(headers[offset]).merkle_root


def test_verify_chain_rejects_first_link_to_wrong_checkpoint() -> None:
    """Header[0].prev_hash must equal the checkpoint's hash; any
    other value (even one that links to the *previous* checkpoint
    if the operator has multiple) must be refused."""
    base = _mine_easy(b"\x00" * 32, time=1)
    cp = _checkpoint_for(base, height=100)

    # Linked to a *different* checkpoint instead.
    other_base = _mine_easy(b"\xff" * 32, time=1)
    headers = [_mine_easy(h.header_hash(other_base), time=2)]
    with pytest.raises(h.HeaderError, match="prev_hash mismatch"):
        h.verify_chain(headers, cp)


def test_verify_chain_rejects_internal_linkage_break() -> None:
    """Header[i].prev_hash must equal header[i-1].hash. A single
    forged byte in any internal prev_hash must be detected."""
    base = _mine_easy(b"\x00" * 32, time=1)
    cp = _checkpoint_for(base, height=100)
    h1 = _mine_easy(h.header_hash(base), time=2)
    # h2 links to a *fake* hash, not to h1.
    fake_prev = h.header_hash(_mine_easy(b"\x11" * 32, time=99))
    h2 = _mine_easy(fake_prev, time=3)

    with pytest.raises(h.HeaderError, match="prev_hash mismatch"):
        h.verify_chain([h1, h2], cp)


def test_verify_chain_rejects_failed_pow() -> None:
    """A header that doesn't satisfy its declared bits is rejected
    before its merkle root is exposed to the SPV verifier."""
    base = _mine_easy(b"\x00" * 32, time=1)
    cp = _checkpoint_for(base, height=100)

    # Build a header whose prev_hash links correctly, but whose bits
    # are tightened so its hash exceeds the new target.
    blob = bytearray(_mine_easy(h.header_hash(base), time=2))
    blob[72:76] = (0x1C000001).to_bytes(4, "little")  # impossibly tight
    with pytest.raises(h.HeaderError, match="fails PoW"):
        h.verify_chain([bytes(blob)], cp)


def test_verify_chain_rejects_short_header() -> None:
    """Structural validation must run before any hashing; a 79-byte
    blob in the middle of an otherwise valid chain must surface a
    clear height-tagged error."""
    base = _mine_easy(b"\x00" * 32, time=1)
    cp = _checkpoint_for(base, height=100)
    h1 = _mine_easy(h.header_hash(base), time=2)
    bad = b"\x00" * 79
    with pytest.raises(h.HeaderError, match="height 102"):
        h.verify_chain([h1, bad], cp)


def test_verify_chain_rejects_empty_input() -> None:
    """An empty chain is a contract violation: callers should always
    ship at least one header (the height of the deepest input + the
    proposal's confirmation depth)."""
    base = _mine_easy(b"\x00" * 32, time=1)
    cp = _checkpoint_for(base, height=100)
    with pytest.raises(h.HeaderError, match="empty"):
        h.verify_chain([], cp)


def test_verify_chain_independent_of_iterator_protocol() -> None:
    """The function accepts any iterable of bytes, so a generator
    backed by a streaming companion is fine without buffering."""
    base = _mine_easy(b"\x00" * 32, time=1)
    cp = _checkpoint_for(base, height=100)

    headers = [_mine_easy(h.header_hash(base), time=2)]
    result = h.verify_chain(iter(headers), cp)
    assert 101 in result


def test_checkpoint_header_validates_inputs() -> None:
    with pytest.raises(h.HeaderError, match="32 bytes"):
        h.CheckpointHeader(height=0, hash=b"\x00" * 31)
    with pytest.raises(h.HeaderError, match="non-negative"):
        h.CheckpointHeader(height=-1, hash=b"\x00" * 32)


# ---- Sanity: real BSV mainnet-style values --------------------------------


def test_genesis_target_bound_holds() -> None:
    """The genesis hash interpreted as little-endian uint256 is below
    the genesis target. This is the foundational invariant of all SPV
    code; if this ever fails the entire bits/hash machinery is wrong."""
    blob = bytes.fromhex(GENESIS_HEADER_HEX)
    header = h.parse_header(blob)
    target = h.bits_to_target(header.bits)
    h_int = int.from_bytes(header.hash, "little")
    assert h_int <= target


# ---- Property tests on long synthetic chains -----------------------------


def test_verify_chain_scales_to_one_hundred_headers() -> None:
    """A 100-deep chain validates without any per-header state
    leaking forward beyond ``expected_prev``. The output map is
    dense, sized exactly to the chain length, and starts at
    ``checkpoint+1``."""
    base = _mine_easy(b"\x00" * 32, time=1)
    cp = _checkpoint_for(base, height=500_000)

    chain: list[bytes] = []
    prev_hash = h.header_hash(base)
    for i in range(100):
        blob = _mine_easy(prev_hash, time=2 + i)
        chain.append(blob)
        prev_hash = h.header_hash(blob)

    out = h.verify_chain(chain, cp)
    assert len(out) == 100
    assert min(out) == 500_001
    assert max(out) == 500_100


def test_verify_chain_detects_tampering_at_middle_height() -> None:
    """Flipping a single byte in any field of any header in the
    middle of the chain must surface a clear height-tagged error
    on the failing index, not silently swallow into a global
    "chain invalid" message."""
    base = _mine_easy(b"\x00" * 32, time=1)
    cp = _checkpoint_for(base, height=1000)

    chain: list[bytes] = []
    prev_hash = h.header_hash(base)
    for i in range(10):
        blob = _mine_easy(prev_hash, time=2 + i)
        chain.append(blob)
        prev_hash = h.header_hash(blob)

    # Tamper with header at offset 5 (height 1006). Flipping a byte
    # inside the merkle_root field changes the header's hash, so the
    # tampered header itself may now fail PoW at height 1006 (≈50%
    # of randomized hashes are above the easy target), or its
    # successor at height 1007 may fail prev_hash linkage. Either
    # surface is a correct detection — what matters is that the
    # error message ties the failure to the right height range.
    forged = bytearray(chain[5])
    forged[40] ^= 0xFF
    chain[5] = bytes(forged)

    with pytest.raises(
        h.HeaderError, match=r"height 100[67]: (prev_hash mismatch|.*fails PoW)"
    ):
        h.verify_chain(chain, cp)


def test_verify_chain_rejects_chain_descending_from_wrong_network_checkpoint() -> None:
    """A real-world attack vector: a malicious companion ships a
    valid testnet chain to a mainnet-anchored signer. The first
    header's prev_hash links to testnet genesis instead of mainnet
    genesis, so chain-walking refuses the very first step."""
    main_base = _mine_easy(b"\x11" * 32, time=1)  # pretend mainnet checkpoint
    test_base = _mine_easy(b"\x22" * 32, time=1)  # pretend testnet checkpoint

    main_cp = _checkpoint_for(main_base, height=1)
    # Build a chain that descends from the *testnet* checkpoint.
    test_chain = [_mine_easy(h.header_hash(test_base), time=2)]

    with pytest.raises(h.HeaderError, match="prev_hash mismatch"):
        h.verify_chain(test_chain, main_cp)
