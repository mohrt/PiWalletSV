"""Tests for piwallet.core.derivation.

Locks in the canonical outputs for the BIP39 zero-entropy 12-word mnemonic at
`m/44'/236'/0'` (BSV). If these change, something is wrong with our derivation
chain or with the underlying bsv-sdk and we need to investigate.
"""

from __future__ import annotations

import pytest

from piwallet.core import derivation as d
from piwallet.core import mnemonic as m

CANONICAL_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon about"
)
"""BIP39 zero-entropy 12-word vector. Used as our canonical fixture seed."""

# Captured locally with bsv-sdk 1.0.11. Locking these in detects regressions
# in the dependency or our derivation wrapper.
CANONICAL_ACCOUNT_XPRV = (
    "xprv9ydzpAw8scxgS53bvJyqSwDvfxDQZZtaJV98SYjZto3Pg7MCsPBjCcYqUtnWPR"
    "NayEXUcSYZDvXux545bHZwda7YUWvReJiRkx38VXathgK"
)
CANONICAL_ACCOUNT_XPUB = (
    "xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQvVykQsKLARZdb"
    "qKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R"
)
CANONICAL_FINGERPRINT_HEX = "cf987d8c"

CANONICAL_RECEIVE_ADDRESSES = [
    "1K6LZdwpKT5XkEZo2T2kW197aMXYbYMc4f",
    "1DhquSu6ky8QQnf88b1d3tRYeUkMLASZg9",
    "155Vurs4bMMu5BemtZ6cVPhryGWef4VxZu",
]
CANONICAL_CHANGE_ADDRESSES = [
    "125GFsvYsDtyzGkExfsX8DoHuXu2UsMUEZ",
    "1HB1TYZAQBu84TUfAVVkqnZDWX1JTizALU",
    "1FVCwj1goPiMWb5qCUrerT3FRkW7cfthL7",
]

# Same xpub bytes, but rendered with the testnet P2PKH version byte
# (0x6F). Locks the testnet path against silent prefix-byte regressions
# in bsv-sdk or our wrapper.
CANONICAL_TESTNET_RECEIVE_ADDRESSES = [
    "mycHrh2o8UWnXM3Qk218KvMSSM8FWgNxFH",
    "mtDoCVz5ZzZfBu8jr9yzsodsWUM4Fc7Q14",
    "mjbTCux3QNo9rJ8Pc84zKJvBqG7MYWcUDa",
]
CANONICAL_TESTNET_CHANGE_ADDRESSES = [
    "mgbDYw1XgFLEmPDrgEqtx91cmXVjPGg6un",
    "mwgxkbe9DDLNqZxGt4U8fhmYNWc1P4Wxvq",
    "mv1AEn6fcR9cHhZSv3q2gNFaHk6pZEDcyu",
]


@pytest.fixture
def canonical_master():
    seed = m.seed_from_mnemonic(CANONICAL_MNEMONIC, passphrase="")
    return d.master_xprv_from_seed(seed)


def test_master_xprv_from_seed_rejects_short_seed() -> None:
    with pytest.raises(ValueError, match="64 bytes"):
        d.master_xprv_from_seed(b"\x00" * 32)


def test_master_xprv_from_seed_rejects_non_bytes() -> None:
    with pytest.raises(TypeError):
        d.master_xprv_from_seed("not bytes")  # type: ignore[arg-type]


def test_master_xprv_depth_zero(canonical_master) -> None:
    assert canonical_master.depth == 0


def test_account_path_default_is_bsv() -> None:
    assert d.account_path() == "m/44'/236'/0'"


def test_account_path_custom() -> None:
    assert d.account_path(coin_type=0, account=2) == "m/44'/0'/2'"


def test_derive_account_canonical_outputs(canonical_master) -> None:
    """Lock in the exact xprv/xpub/fingerprint for the canonical mnemonic."""
    acct = d.derive_account(canonical_master)
    assert str(acct.xprv) == CANONICAL_ACCOUNT_XPRV
    assert str(acct.xpub) == CANONICAL_ACCOUNT_XPUB
    assert acct.fingerprint.hex() == CANONICAL_FINGERPRINT_HEX
    assert acct.path == "m/44'/236'/0'"
    assert acct.coin_type == 236
    assert acct.account == 0


def test_derive_account_rejects_non_master(canonical_master) -> None:
    """`derive_account` should refuse non-master inputs."""
    once_derived = canonical_master.ckd(0)
    assert once_derived.depth == 1
    with pytest.raises(ValueError, match="depth"):
        d.derive_account(once_derived)


def test_derive_account_xpub_is_subset_of_xprv(canonical_master) -> None:
    acct = d.derive_account(canonical_master)
    # xpub.public_key() must equal xprv.public_key() at the same path
    assert acct.xpub.public_key().serialize() == acct.xprv.public_key().serialize()


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_derive_address_receive_canonical(canonical_master, idx: int) -> None:
    acct = d.derive_account(canonical_master)
    assert d.derive_address(acct.xpub, d.CHANGE_RECEIVE, idx) == CANONICAL_RECEIVE_ADDRESSES[idx]


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_derive_address_change_canonical(canonical_master, idx: int) -> None:
    acct = d.derive_account(canonical_master)
    assert d.derive_address(acct.xpub, d.CHANGE_INTERNAL, idx) == CANONICAL_CHANGE_ADDRESSES[idx]


@pytest.mark.parametrize("bad_change", [-1, 2, 3, 100])
def test_derive_address_rejects_bad_change(canonical_master, bad_change: int) -> None:
    acct = d.derive_account(canonical_master)
    with pytest.raises(ValueError, match="change"):
        d.derive_address(acct.xpub, bad_change, 0)


@pytest.mark.parametrize("bad_index", [-1, d.BIP32_HARDENED, d.BIP32_HARDENED + 1])
def test_derive_address_rejects_bad_index(canonical_master, bad_index: int) -> None:
    acct = d.derive_account(canonical_master)
    with pytest.raises(ValueError, match="index"):
        d.derive_address(acct.xpub, 0, bad_index)


def test_derive_signing_key_matches_address(canonical_master) -> None:
    """The Pi's signing key for /0/0 must produce the same address as the watch-only path."""
    acct = d.derive_account(canonical_master)
    sk = d.derive_signing_key(acct.xprv, 0, 0)
    assert sk.address() == d.derive_address(acct.xpub, 0, 0)
    assert sk.address() == CANONICAL_RECEIVE_ADDRESSES[0]


def test_xpub_round_trip(canonical_master) -> None:
    """Serialize xpub to base58, parse back, derive same address."""
    acct = d.derive_account(canonical_master)
    xpub_str = str(acct.xpub)
    parsed = d.parse_xpub(xpub_str)
    assert d.derive_address(parsed, 0, 0) == CANONICAL_RECEIVE_ADDRESSES[0]


# ---------------------------------------------------------------------------
# Network-aware address rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_derive_address_testnet_receive_canonical(canonical_master, idx: int) -> None:
    """Testnet P2PKH version (0x6F) on the same xpub gives the canonical 'm…' addresses."""
    acct = d.derive_account(canonical_master)
    got = d.derive_address(acct.xpub, d.CHANGE_RECEIVE, idx, network="test")
    assert got == CANONICAL_TESTNET_RECEIVE_ADDRESSES[idx]


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_derive_address_testnet_change_canonical(canonical_master, idx: int) -> None:
    acct = d.derive_account(canonical_master)
    got = d.derive_address(acct.xpub, d.CHANGE_INTERNAL, idx, network="test")
    assert got == CANONICAL_TESTNET_CHANGE_ADDRESSES[idx]


def test_derive_address_default_network_is_main(canonical_master) -> None:
    """Omitting network must keep the pre-testnet behaviour byte-for-byte."""
    acct = d.derive_account(canonical_master)
    assert d.derive_address(acct.xpub, 0, 0) == CANONICAL_RECEIVE_ADDRESSES[0]


def test_derive_address_main_explicit_matches_default(canonical_master) -> None:
    acct = d.derive_account(canonical_master)
    assert d.derive_address(acct.xpub, 0, 0) == d.derive_address(
        acct.xpub, 0, 0, network="main"
    )


def test_derive_address_rejects_unknown_network(canonical_master) -> None:
    acct = d.derive_account(canonical_master)
    with pytest.raises(ValueError, match="network must be"):
        d.derive_address(acct.xpub, 0, 0, network="testnet")  # type: ignore[arg-type]


def test_derive_address_main_and_test_differ(canonical_master) -> None:
    """The same xpub branch produces different rendered addresses per network."""
    acct = d.derive_account(canonical_master)
    main = d.derive_address(acct.xpub, 0, 0, network="main")
    test = d.derive_address(acct.xpub, 0, 0, network="test")
    assert main != test
    # Mainnet legacy P2PKH addresses start with '1'; testnet with 'm' or 'n'.
    assert main.startswith("1")
    assert test[0] in ("m", "n")


def test_network_constants_exist() -> None:
    assert d.NETWORK_MAIN == "main"
    assert d.NETWORK_TEST == "test"
    assert set(d.NETWORK_VALUES) == {"main", "test"}
    assert d.DEFAULT_NETWORK == "main"


def test_different_account_indices_produce_different_xpubs(canonical_master) -> None:
    a0 = d.derive_account(canonical_master, account=0)
    a1 = d.derive_account(canonical_master, account=1)
    assert str(a0.xpub) != str(a1.xpub)
    assert a0.fingerprint != a1.fingerprint


def test_different_coin_types_produce_different_xpubs(canonical_master) -> None:
    bsv = d.derive_account(canonical_master, coin_type=236)
    btc = d.derive_account(canonical_master, coin_type=0)
    assert str(bsv.xpub) != str(btc.xpub)


def test_key_fingerprint_is_self_not_parent(canonical_master) -> None:
    """`key_fingerprint(xpub)` returns this key's own fp; bsv-sdk's `.fingerprint` is the parent's."""
    acct = d.derive_account(canonical_master)
    assert d.key_fingerprint(acct.xpub).hex() == CANONICAL_FINGERPRINT_HEX
    # Sanity: parent fingerprint is different (we derived 3 hardened steps, so
    # parent fp = fp of m/44'/236' which is not this key's fp).
    assert acct.xpub.fingerprint != d.key_fingerprint(acct.xpub)


def test_key_fingerprint_works_on_xprv(canonical_master) -> None:
    acct = d.derive_account(canonical_master)
    assert d.key_fingerprint(acct.xprv) == d.key_fingerprint(acct.xpub)
