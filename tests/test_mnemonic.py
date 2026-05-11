"""Tests for piwallet.core.mnemonic.

Cross-checks against canonical BIP39 vectors:
    https://github.com/trezor/python-mnemonic/blob/master/vectors.json
"""

from __future__ import annotations

import pytest

from piwallet.core import mnemonic as m

# Canonical BIP39 test vectors with passphrase "TREZOR" from
# https://github.com/trezor/python-mnemonic/blob/master/vectors.json
# Tuple format: (entropy_hex, mnemonic, seed_hex_with_TREZOR_passphrase)
BIP39_TREZOR_VECTORS = [
    (
        "00000000000000000000000000000000",
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
        "c55257c360c07c72029aebc1b53c05ed0362ada38ead3e3e9efa3708e5349553"
        "1f09a6987599d18264c1e1c92f2cf141630c7a3c4ab7c81b2f001698e7463b04",
    ),
    (
        "0000000000000000000000000000000000000000000000000000000000000000",
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon "
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon "
        "abandon art",
        "bda85446c68413707090a52022edd26a1c9462295029f2e60cd7c4f2bbd30971"
        "70af7a4d73245cafa9c3cca8d561a7c3de6f5d4a10be8ed2a5e608d68f92fcc8",
    ),
    (
        "9e885d952ad362caeb4efe34a8e91bd2",
        "ozone drill grab fiber curtain grace pudding thank cruise elder eight picnic",
        "274ddc525802f7c828d8ef7ddbcdc5304e87ac3535913611fbbfa986d0c9e547"
        "6c91689f9c8a54fd55bd38606aa6a8595ad213d4c9c9f9aca3fb217069a41028",
    ),
]

# Empty-passphrase reference for the 12-word zero-entropy case.
# Easily reproducible: any standalone BIP39 implementation with empty passphrase.
BIP39_EMPTY_PASSPHRASE_VECTOR = (
    "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
    "5eb00bbddcf069084889a8ab9155568165f5c453ccb85e70811aaed6f6da5fc1"
    "9a5ac40b389cd370d086206dec8aa6c43daea6690f20ad3d8d48b2d2ce9e38e4",
)


@pytest.mark.parametrize("count", [12, 24])
def test_generate_returns_valid_mnemonic(count: int) -> None:
    phrase = m.generate(count)
    assert len(phrase.split()) == count
    m.validate(phrase)  # raises if bad


def test_generate_unique() -> None:
    """Two consecutive generations should not produce the same phrase."""
    a = m.generate(12)
    b = m.generate(12)
    assert a != b


@pytest.mark.parametrize("bad", [10, 13, 15, 18, 21, 25, 0, -1])
def test_generate_rejects_bad_word_count(bad: int) -> None:
    with pytest.raises(m.MnemonicError):
        m.generate(bad)


@pytest.mark.parametrize(("entropy_hex", "mnemonic", "seed_hex"), BIP39_TREZOR_VECTORS)
def test_seed_matches_trezor_vectors(entropy_hex: str, mnemonic: str, seed_hex: str) -> None:
    """Seed derivation with passphrase 'TREZOR' must match the canonical Trezor vectors."""
    m.validate(mnemonic)
    seed = m.seed_from_mnemonic(mnemonic, passphrase="TREZOR")
    assert seed.hex() == seed_hex


def test_seed_empty_passphrase_zero_entropy() -> None:
    """Empty-passphrase seed for the canonical 12-word zero-entropy mnemonic."""
    mnemonic, expected = BIP39_EMPTY_PASSPHRASE_VECTOR
    seed = m.seed_from_mnemonic(mnemonic, passphrase="")
    assert seed.hex() == expected


def test_validate_empty() -> None:
    with pytest.raises(m.MnemonicError, match="empty"):
        m.validate("")


def test_validate_wrong_word_count() -> None:
    # 11 words: not in SUPPORTED_WORD_COUNTS
    phrase = "abandon " * 10 + "about"
    with pytest.raises(m.MnemonicError, match="11 words"):
        m.validate(phrase.strip())


def test_validate_unknown_word() -> None:
    phrase = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon NOTAWORD"
    with pytest.raises(m.MnemonicError, match="unknown BIP39 word"):
        m.validate(phrase)


def test_validate_bad_checksum() -> None:
    # Same prefix as the canonical vector but last word swapped to one with bad checksum.
    bad = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon"
    with pytest.raises(m.MnemonicError, match="checksum"):
        m.validate(bad)


def test_seed_with_passphrase_differs() -> None:
    phrase = BIP39_TREZOR_VECTORS[0][1]
    s_no = m.seed_from_mnemonic(phrase, passphrase="")
    s_yes = m.seed_from_mnemonic(phrase, passphrase="trezor")
    assert s_no != s_yes


def test_wordlist_size_and_uniqueness() -> None:
    assert len(m.BIP39_WORDLIST) == 2048
    assert len(set(m.BIP39_WORDLIST)) == 2048
    # BIP39 spec: words are unique by their first 4 letters (used for our autocomplete).
    prefixes = {w[:4] for w in m.BIP39_WORDLIST}
    assert len(prefixes) == 2048


def test_autocomplete_basic() -> None:
    suggestions = m.autocomplete("abs")
    assert "absent" in suggestions
    assert "absorb" in suggestions
    assert "abstract" in suggestions
    assert "absurd" in suggestions
    # all returned words start with prefix
    assert all(s.startswith("abs") for s in suggestions)


def test_autocomplete_empty_prefix() -> None:
    assert m.autocomplete("") == []


def test_autocomplete_no_match() -> None:
    assert m.autocomplete("xyzzy") == []


def test_autocomplete_limit() -> None:
    suggestions = m.autocomplete("a", limit=3)
    assert len(suggestions) == 3


def test_autocomplete_case_insensitive() -> None:
    assert m.autocomplete("Abs") == m.autocomplete("abs")
