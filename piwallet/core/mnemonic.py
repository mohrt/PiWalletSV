"""BIP39 mnemonic generation, validation, and seed derivation.

Thin wrapper around bsv-sdk's `hd` module. The wrapper exists so the rest of
PiWalletSV imports a single, stable surface and so we can swap implementations
later without ripping changes through the codebase.

Important security notes:

- Mnemonics are returned as plain `str`. The caller is responsible for zeroing
  the underlying memory after `seed_from_mnemonic()` is called and the xprv
  has been encrypted into the vault. Python strings are immutable, so for
  defense in depth the caller should pass mnemonics around as `bytearray`
  where practical and overwrite them with zeros on disposal.
- Word count must be 12 or 24 (per locked plan decision); 15/18/21 are valid
  BIP39 but not exposed in the v1 UI.
"""

from __future__ import annotations

import hashlib
import secrets

from bsv.hd import mnemonic_from_entropy
from bsv.hd import seed_from_mnemonic as _seed_from_mnemonic
from bsv.hd import validate_mnemonic as _validate_mnemonic
from bsv.hd.bip39 import WordList

SUPPORTED_WORD_COUNTS: tuple[int, ...] = (12, 24)
"""Mnemonic word counts the v1 PiWalletSV UI exposes."""

WORDS_TO_ENTROPY_BYTES: dict[int, int] = {12: 16, 24: 32}
"""Mapping from BIP39 word count to entropy size in bytes."""

MIN_DICE_ROLLS: dict[int, int] = {12: 48, 24: 96}
"""Minimum die faces required before ``mnemonic_from_dice_rolls`` (≈2.58 bits each)."""


def _load_english_wordlist() -> tuple[str, ...]:
    WordList.load()
    # bsv-sdk 2.x stores loaded lists in ``wordlists``; 1.x exposes ``wordlist``.
    if hasattr(WordList, "wordlists"):
        words = WordList.wordlists.get("en")
        if words:
            return tuple(words)
    wl = WordList.wordlist
    if isinstance(wl, dict) and wl.get("en"):
        return tuple(wl["en"])
    raise RuntimeError("English BIP39 wordlist unavailable from bsv-sdk")


BIP39_WORDLIST: tuple[str, ...] = _load_english_wordlist()
"""Canonical English BIP39 wordlist (2048 words). Used for joystick autocomplete."""


class MnemonicError(ValueError):
    """Raised on invalid mnemonic input."""


def generate(word_count: int = 12) -> str:
    """Generate a new BIP39 mnemonic with the given word count.

    Uses `secrets.token_bytes` (CSPRNG, OS-backed). On the Pi this routes
    through `getrandom(2)` which mixes the hardware RNG when available.

    :param word_count: 12 or 24 (per v1 UI).
    :returns: space-separated mnemonic string.
    :raises MnemonicError: if `word_count` is not supported.
    """
    if word_count not in WORDS_TO_ENTROPY_BYTES:
        raise MnemonicError(
            f"unsupported word_count {word_count}; must be one of {SUPPORTED_WORD_COUNTS}"
        )
    entropy = secrets.token_bytes(WORDS_TO_ENTROPY_BYTES[word_count])
    return mnemonic_from_entropy(entropy)


def mnemonic_from_material(material: bytes, word_count: int, *, domain: bytes) -> str:
    """Build a BIP39 phrase from OS random mixed with user-supplied material.

    Draws ``nbytes`` from ``secrets.token_bytes`` and hashes
    ``SHA-256(domain ‖ os_bytes ‖ material)``, truncated to the BIP39 entropy
    length (16 bytes for 12 words, 32 for 24). Physical input (photo, dice)
    augments OS random — it never replaces it — so collision resistance stays
    at least as strong as the CSPRNG-only path even when ``material`` is weak.

    :param material: raw bytes to mix (e.g. JPEG file bytes, packed dice rolls).
    :param domain: short stable tag separating dice vs camera inputs.
    """
    if word_count not in WORDS_TO_ENTROPY_BYTES:
        raise MnemonicError(
            f"unsupported word_count {word_count}; must be one of {SUPPORTED_WORD_COUNTS}"
        )
    nbytes = WORDS_TO_ENTROPY_BYTES[word_count]
    os_part = secrets.token_bytes(nbytes)
    digest = hashlib.sha256(domain + os_part + material).digest()
    entropy = digest[:nbytes]
    return mnemonic_from_entropy(entropy)


_DICE_DOMAIN = b"piwalletsv-dice-v1\x00"
_CAMERA_DOMAIN = b"piwalletsv-camera-v1\x00"


def mnemonic_from_dice_rolls(rolls: list[int], word_count: int) -> str:
    """Derive a mnemonic from base-6 die faces (1..6) mixed with OS random."""
    if word_count not in MIN_DICE_ROLLS:
        raise MnemonicError(
            f"unsupported word_count {word_count}; must be one of {SUPPORTED_WORD_COUNTS}"
        )
    minimum = MIN_DICE_ROLLS[word_count]
    if not rolls:
        raise MnemonicError("no dice rolls recorded")
    if len(rolls) < minimum:
        raise MnemonicError(
            f"need at least {minimum} dice rolls for {word_count}-word phrase; got {len(rolls)}"
        )
    for r in rolls:
        if not isinstance(r, int) or not (1 <= r <= 6):
            raise MnemonicError(f"invalid die face: {r!r} (expect 1..6)")
    return mnemonic_from_material(bytes(rolls), word_count, domain=_DICE_DOMAIN)


def mnemonic_from_camera_jpeg(jpeg_bytes: bytes, word_count: int) -> str:
    """Derive a mnemonic from one camera still (JPEG bytes)."""
    if not jpeg_bytes:
        raise MnemonicError("empty camera capture")
    return mnemonic_from_material(jpeg_bytes, word_count, domain=_CAMERA_DOMAIN)


def validate(mnemonic: str) -> None:
    """Validate that `mnemonic` is a well-formed BIP39 phrase.

    :raises MnemonicError: with a human-readable reason on failure.
    """
    if not isinstance(mnemonic, str):
        raise MnemonicError("mnemonic must be a string")

    words = mnemonic.split()
    if not words:
        raise MnemonicError("mnemonic is empty")

    if len(words) not in SUPPORTED_WORD_COUNTS:
        raise MnemonicError(
            f"mnemonic has {len(words)} words; v1 supports {SUPPORTED_WORD_COUNTS}"
        )

    unknown = [w for w in words if w not in BIP39_WORDLIST]
    if unknown:
        raise MnemonicError(
            f"unknown BIP39 word(s): {unknown[:3]}{' ...' if len(unknown) > 3 else ''}"
        )

    try:
        _validate_mnemonic(mnemonic)
    except Exception as exc:
        raise MnemonicError(f"BIP39 checksum verification failed: {exc}") from exc


def seed_from_mnemonic(mnemonic: str, passphrase: str = "") -> bytes:
    """Derive the 64-byte BIP39 seed from a mnemonic.

    :param mnemonic: BIP39 phrase. Must already be validated; this function
        re-validates as a defensive measure.
    :param passphrase: Optional BIP39 passphrase (the "25th word"). Empty
        string for v1 (passphrase support deferred to v2 per the plan).
    :returns: 64-byte seed suitable for `master_xprv_from_seed`.
    """
    validate(mnemonic)
    seed = _seed_from_mnemonic(mnemonic, passphrase=passphrase)
    if len(seed) != 64:
        # Defensive: bsv-sdk shouldn't return anything else, but check.
        raise MnemonicError(f"unexpected seed length: {len(seed)}")
    return seed


def words_starting_with(prefix: str) -> list[str]:
    """All BIP39 English words whose spelling starts with ``prefix``.

    Alphabetical order (same as :data:`BIP39_WORDLIST`). Used by the bonnet
    word picker for correct unique-match detection; previews may show only a
    head/tail subset when the stem matches many entries (e.g. ``ma…`` lists
    33 words until you narrow).

    Empty ``prefix`` returns an empty list.
    """
    if not prefix:
        return []
    p = prefix.lower()
    return [w for w in BIP39_WORDLIST if w.startswith(p)]


def autocomplete(prefix: str, limit: int = 8) -> list[str]:
    """Return the first ``limit`` BIP39 words starting with ``prefix``.

    For the full list prefer :func:`words_starting_with` (cheap: at most 2048
    string checks per call).

    :param prefix: lowercase letters typed so far. Empty string returns [].
    :param limit: cap on suggestions returned.
    """
    return words_starting_with(prefix)[:limit]
