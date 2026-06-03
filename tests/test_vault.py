"""Tests for piwallet.core.vault.

Covers create -> add wallet -> sign-time key derive -> reload-from-disk
flow, plus PIN policy: validation, lockout counter behavior, threshold
wipe, and the file-shape invariants needed for the bonnet first-boot UX.

We use a much smaller scrypt cost in some tests via direct manipulation,
not via the public API, so the suite stays under 5s on a laptop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from piwallet.core import derivation as deriv
from piwallet.core import mnemonic as mnem
from piwallet.core import vault as vlt

CANONICAL_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon about"
)
EXPECTED_FP_HEX = "cf987d8c"
GOOD_PIN = "654321"


@pytest.fixture
def vault_path(tmp_path: Path) -> Path:
    return tmp_path / "vault.bin"


@pytest.fixture(autouse=True)
def _fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lower scrypt cost across the test suite for speed.

    Real wallet still uses N=2**15 in production (configured in vault.py).
    """
    monkeypatch.setattr(vlt, "SCRYPT_N", 2**12)


# ---- creation & PIN validation -----------------------------------------


def test_create_initializes_file(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    assert not v.exists
    v.create(pin=GOOD_PIN)
    assert v.exists
    assert v.is_initialized
    assert v.list_wallets() == []
    assert v.attempts_remaining == 10


def test_create_refuses_existing_file(vault_path: Path) -> None:
    vault_path.write_bytes(b"placeholder")
    v = vlt.Vault(vault_path)
    with pytest.raises(vlt.VaultError, match="already exists"):
        v.create(pin=GOOD_PIN)


@pytest.mark.parametrize("bad_pin", ["", "12345", "abcdef", "1234ab", "12 345"])
def test_create_rejects_bad_pins(vault_path: Path, bad_pin: str) -> None:
    v = vlt.Vault(vault_path)
    with pytest.raises(ValueError):
        v.create(pin=bad_pin)


# ---- add / list / sign roundtrip ---------------------------------------


def test_add_wallet_records_metadata(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    assert rec.label == "daily"
    assert rec.fingerprint.hex() == EXPECTED_FP_HEX
    assert rec.derivation_path == "m/44'/236'/0'"
    assert rec.word_count == 12
    listed = v.list_wallets()
    assert len(listed) == 1
    assert listed[0] == rec


def test_add_wallet_persists_across_reload(vault_path: Path) -> None:
    v1 = vlt.Vault(vault_path)
    v1.create(pin=GOOD_PIN)
    rec = v1.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")

    v2 = vlt.Vault(vault_path)
    listed = v2.list_wallets()
    assert len(listed) == 1
    assert listed[0].id == rec.id
    assert listed[0].fingerprint.hex() == EXPECTED_FP_HEX


def test_add_wallet_with_custom_coin_type_and_account(vault_path: Path) -> None:
    """Custom (coin_type, account_index) is reflected in WalletRecord.derivation_path."""
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(
        pin=GOOD_PIN,
        mnemonic_phrase=CANONICAL_MNEMONIC,
        label="alt",
        coin_type=0,
        account_index=2,
    )
    assert rec.derivation_path == "m/44'/0'/2'"
    # And it survives a vault reload.
    v2 = vlt.Vault(vault_path)
    assert v2.list_wallets()[0].derivation_path == "m/44'/0'/2'"


def test_add_wallet_rejects_negative_coin_type(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    with pytest.raises(vlt.VaultError):
        v.add_wallet(
            pin=GOOD_PIN,
            mnemonic_phrase=CANONICAL_MNEMONIC,
            label="bad",
            coin_type=-1,
        )


def test_add_wallet_rejects_negative_account_index(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    with pytest.raises(vlt.VaultError):
        v.add_wallet(
            pin=GOOD_PIN,
            mnemonic_phrase=CANONICAL_MNEMONIC,
            label="bad",
            account_index=-5,
        )


def test_add_wallet_distinct_accounts_produce_distinct_xprvs(vault_path: Path) -> None:
    """Two wallets at different account indices have different fingerprints."""
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    a = v.add_wallet(
        pin=GOOD_PIN,
        mnemonic_phrase=CANONICAL_MNEMONIC,
        label="a",
        account_index=0,
    )
    b = v.add_wallet(
        pin=GOOD_PIN,
        mnemonic_phrase=CANONICAL_MNEMONIC,
        label="b",
        account_index=1,
    )
    assert a.fingerprint != b.fingerprint
    assert a.derivation_path == "m/44'/236'/0'"
    assert b.derivation_path == "m/44'/236'/1'"


# ---------------------------------------------------------------------------
# Network field + v1 -> v2 schema migration
# ---------------------------------------------------------------------------


def test_add_wallet_defaults_to_mainnet(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="m")
    assert rec.network == "main"


def test_add_wallet_persists_testnet(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(
        pin=GOOD_PIN,
        mnemonic_phrase=CANONICAL_MNEMONIC,
        label="t",
        network="test",
    )
    assert rec.network == "test"
    # And it survives a reload from disk.
    v2 = vlt.Vault(vault_path)
    listed = v2.list_wallets()
    assert listed[0].network == "test"


def test_add_wallet_rejects_unknown_network(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    with pytest.raises(vlt.VaultError, match="network"):
        v.add_wallet(
            pin=GOOD_PIN,
            mnemonic_phrase=CANONICAL_MNEMONIC,
            label="bad",
            network="testnet",  # type: ignore[arg-type]
        )


def test_v1_vault_is_read_as_mainnet_and_rewritten_as_v2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vault file written under format v1 (no per-wallet network field)
    is forward-migrated: list_wallets yields network='main' and the next
    save rewrites the file as v2.
    """
    import cbor2

    vault_path = tmp_path / "vault.bin"

    # Build a v2 vault first so we have realistic encrypted blobs, then
    # rewrite the on-disk shape to v1 (no `network` keys, vaultVersion=1).
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="legacy")

    raw = cbor2.loads(vault_path.read_bytes())
    raw["vaultVersion"] = 1
    for w in raw["wallets"]:
        w.pop("network", None)
    vault_path.write_bytes(cbor2.dumps(raw))

    # Re-open: _load forward-migrates in memory.
    v_legacy = vlt.Vault(vault_path)
    listed = v_legacy.list_wallets()
    assert len(listed) == 1
    assert listed[0].network == "main"

    # First mutation rewrites the file as v2 with explicit "main".
    v_legacy.add_wallet(
        pin=GOOD_PIN,
        mnemonic_phrase=CANONICAL_MNEMONIC,
        label="modern",
    )
    rewritten = cbor2.loads(vault_path.read_bytes())
    assert rewritten["vaultVersion"] == 2
    networks = [w.get("network") for w in rewritten["wallets"]]
    assert networks == ["main", "main"]


def test_unsupported_future_version_is_rejected(
    tmp_path: Path,
) -> None:
    import cbor2

    vault_path = tmp_path / "vault.bin"
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    raw = cbor2.loads(vault_path.read_bytes())
    raw["vaultVersion"] = 99
    vault_path.write_bytes(cbor2.dumps(raw))
    with pytest.raises(vlt.VaultError, match="unsupported vault version"):
        vlt.Vault(vault_path)


def test_derive_signing_key_returns_correct_address(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    sk = v.derive_signing_key(GOOD_PIN, rec.id, change=0, index=0)
    # Same canonical address as our derivation tests.
    assert sk.address() == "1K6LZdwpKT5XkEZo2T2kW197aMXYbYMc4f"


def test_get_account_xpub(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    xpub_str = v.get_account_xpub(GOOD_PIN, rec.id)
    expected = (
        "xpub6CdMDgU2hzWyeZ852LWqp5AfDz3ty2cRfi4jEw9BT8aNYugMQvVykQsKLARZdb"
        "qKKp7yTviJdL1N9saYLmJNKD1rwVAwLTmU8r8qKeoyG4R"
    )
    assert xpub_str == expected


def test_two_wallets_have_different_fingerprints(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    a = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="A")
    other = mnem.generate(12)
    b = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=other, label="B")
    assert a.fingerprint != b.fingerprint
    assert {w.id for w in v.list_wallets()} == {a.id, b.id}


# ---- PIN policy --------------------------------------------------------


def test_wrong_pin_increments_counter(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")

    rec_id = v.list_wallets()[0].id
    with pytest.raises(vlt.WrongPinError) as exc:
        v.derive_signing_key("999999", rec_id, 0, 0)
    assert exc.value.attempts_remaining == 9
    assert v.attempts_remaining == 9


def test_correct_pin_resets_counter_after_a_miss(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")

    with pytest.raises(vlt.WrongPinError):
        v.derive_signing_key("999999", rec.id, 0, 0)
    assert v.attempts_remaining == 9

    # A correct attempt should bump back up to 10.
    v.derive_signing_key(GOOD_PIN, rec.id, 0, 0)
    assert v.attempts_remaining == 10


def test_threshold_breach_wipes_vault(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")

    for _ in range(9):
        with pytest.raises(vlt.WrongPinError):
            v.derive_signing_key("999999", rec.id, 0, 0)
    assert v.attempts_remaining == 1

    # 10th miss triggers wipe.
    with pytest.raises(vlt.VaultWipedError):
        v.derive_signing_key("999999", rec.id, 0, 0)
    assert not vault_path.exists()
    # Re-instantiating a Vault on the wiped path: file is gone.
    v2 = vlt.Vault(vault_path)
    assert not v2.exists
    assert not v2.is_initialized


def test_attempt_counter_persists_across_reload(vault_path: Path) -> None:
    v1 = vlt.Vault(vault_path)
    v1.create(pin=GOOD_PIN)
    v1.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    rec_id = v1.list_wallets()[0].id

    with pytest.raises(vlt.WrongPinError):
        v1.derive_signing_key("999999", rec_id, 0, 0)
    assert v1.attempts_remaining == 9

    v2 = vlt.Vault(vault_path)
    assert v2.attempts_remaining == 9


# ---- removal & rename --------------------------------------------------


def test_remove_wallet(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    v.remove_wallet(GOOD_PIN, rec.id)
    assert v.list_wallets() == []


def test_remove_wallet_wrong_pin(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    with pytest.raises(vlt.WrongPinError):
        v.remove_wallet("999999", rec.id)
    assert len(v.list_wallets()) == 1


def test_remove_unknown_wallet(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    with pytest.raises(vlt.WalletNotFoundError):
        v.remove_wallet(GOOD_PIN, "not-a-real-id")


def test_rename_wallet(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    v.rename_wallet(GOOD_PIN, rec.id, "savings")
    assert v.list_wallets()[0].label == "savings"


def test_rename_wallet_rejects_empty_label(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    with pytest.raises(vlt.VaultError, match="empty"):
        v.rename_wallet(GOOD_PIN, rec.id, "   ")
    assert v.list_wallets()[0].label == "daily"


# ---- change_pin --------------------------------------------------------


def test_change_pin_unlocks_with_new_and_rejects_old(vault_path: Path) -> None:
    """The new PIN unlocks every wallet; the old PIN no longer works."""
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    v.change_pin(GOOD_PIN, "111111")
    # New PIN works.
    xpub_str = v.get_account_xpub("111111", rec.id)
    assert xpub_str.startswith("xpub")
    # Old PIN fails (and bumps counter).
    with pytest.raises(vlt.WrongPinError):
        v.get_account_xpub(GOOD_PIN, rec.id)


def test_change_pin_rotates_scrypt_salt(vault_path: Path) -> None:
    """Salt rotation is essential — guarantees a snapshot of the old vault
    file isn't a brute-force oracle against the new PIN."""
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    salt_before = bytes(v._state.scrypt_salt)  # type: ignore[union-attr]
    v.change_pin(GOOD_PIN, "111111")
    salt_after = bytes(v._state.scrypt_salt)  # type: ignore[union-attr]
    assert salt_before != salt_after


def test_change_pin_persists_across_reload(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    v.change_pin(GOOD_PIN, "111111")
    # Re-open from disk and confirm the new PIN still unlocks.
    v2 = vlt.Vault(vault_path)
    xpub_str = v2.get_account_xpub("111111", rec.id)
    assert xpub_str.startswith("xpub")


def test_change_pin_rewraps_every_wallet(vault_path: Path) -> None:
    """Multi-wallet vaults must re-wrap *every* DEK, not just the first."""
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec_a = v.add_wallet(
        pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="a", account_index=0
    )
    rec_b = v.add_wallet(
        pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="b", account_index=1
    )
    v.change_pin(GOOD_PIN, "111111")
    # Both wallets unlock under the new PIN.
    assert v.get_account_xpub("111111", rec_a.id).startswith("xpub")
    assert v.get_account_xpub("111111", rec_b.id).startswith("xpub")


def test_change_pin_wrong_old_pin(vault_path: Path) -> None:
    """A wrong old PIN raises and leaves the vault on the original PIN."""
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    with pytest.raises(vlt.WrongPinError):
        v.change_pin("999999", "111111")
    # Old PIN still valid (and the new PIN should *not* work).
    assert v.get_account_xpub(GOOD_PIN, rec.id).startswith("xpub")
    with pytest.raises(vlt.WrongPinError):
        v.get_account_xpub("111111", rec.id)


def test_change_pin_validates_new_pin(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    with pytest.raises(ValueError, match="PIN"):
        v.change_pin(GOOD_PIN, "12345")  # too short


def test_change_pin_no_op_when_old_equals_new(vault_path: Path) -> None:
    """Same-PIN change must not rotate the salt or touch disk semantics."""
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    rec = v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    salt_before = bytes(v._state.scrypt_salt)  # type: ignore[union-attr]
    v.change_pin(GOOD_PIN, GOOD_PIN)
    salt_after = bytes(v._state.scrypt_salt)  # type: ignore[union-attr]
    assert salt_before == salt_after
    # And the PIN still works after the no-op.
    assert v.get_account_xpub(GOOD_PIN, rec.id).startswith("xpub")


def test_change_pin_on_empty_vault_rotates_salt(vault_path: Path) -> None:
    """Empty vault has no ciphertext to verify against — should still
    rotate the salt so the next add_wallet uses the new KEK."""
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    salt_before = bytes(v._state.scrypt_salt)  # type: ignore[union-attr]
    v.change_pin(GOOD_PIN, "111111")
    salt_after = bytes(v._state.scrypt_salt)  # type: ignore[union-attr]
    assert salt_before != salt_after
    # And a new wallet added under the new PIN unlocks with the new PIN.
    rec = v.add_wallet(pin="111111", mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    assert v.get_account_xpub("111111", rec.id).startswith("xpub")


def test_change_pin_uninitialized_raises(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    with pytest.raises(vlt.VaultError, match="not initialized"):
        v.change_pin(GOOD_PIN, "111111")


# ---- terms acknowledgment for first-boot UX ----------------------------


def test_terms_default_unaccepted(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    accepted_at, version = v.terms_acknowledged_for
    assert accepted_at is None
    assert version == 1


def test_accept_terms_persists(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    v.accept_terms(version=2)
    accepted_at, version = v.terms_acknowledged_for
    assert accepted_at is not None
    assert version == 2

    v2 = vlt.Vault(vault_path)
    accepted_at2, version2 = v2.terms_acknowledged_for
    assert accepted_at2 == accepted_at
    assert version2 == 2


# ---- file invariants ---------------------------------------------------


def test_vault_file_does_not_contain_xprv_plaintext(vault_path: Path) -> None:
    """Belt-and-suspenders: the encoded vault file MUST NOT contain the xprv
    string verbatim. If it does, encryption is broken or bypassed."""
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")

    # Compute the canonical account xprv string the vault would have stored.
    seed = mnem.seed_from_mnemonic(CANONICAL_MNEMONIC)
    master = deriv.master_xprv_from_seed(seed)
    account = deriv.derive_account(master)
    xprv_str = str(account.xprv)

    blob = vault_path.read_bytes()
    assert xprv_str.encode("ascii") not in blob
    # And the mnemonic itself must not appear.
    assert CANONICAL_MNEMONIC.encode("utf-8") not in blob


def test_explicit_wipe_clears_file(vault_path: Path) -> None:
    v = vlt.Vault(vault_path)
    v.create(pin=GOOD_PIN)
    v.add_wallet(pin=GOOD_PIN, mnemonic_phrase=CANONICAL_MNEMONIC, label="daily")
    v.wipe()
    assert not vault_path.exists()
    assert not v.is_initialized
