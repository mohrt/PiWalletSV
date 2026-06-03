"""Encrypted multi-wallet vault with PIN-based unlock and lockout-and-wipe.

Two-tier wrapping (per the locked plan):

    PIN ── scrypt ──> KEK ── wraps ──> per-wallet DEK ── encrypts ──> xprv||cc

This keeps add/remove/rename of wallets cheap (only the small DEK is re-wrapped),
and a future hardware secure element could absorb just the DEK wrap.

Security properties:

- xprv is encrypted with AES-GCM-256; nonce randomized per write.
- KEK derived with `scrypt(N=2**15, r=8, p=1)` (~200 ms per try on Zero 2 W).
- PIN attempt counter is incremented BEFORE the decrypt attempt and
  decremented only on success, closing the "yank power between counter
  write and decrypt" loophole.
- On the 10th failure, `wipe()` is invoked (unrecoverable from on-device
  state; user must restore from mnemonic).
- Mnemonic is never persisted; only `xprv || chain_code` ciphertext lives
  on disk. The plan calls this out explicitly.

Vault file format (CBOR-encoded, on disk):

    {
        "vaultVersion": 1,
        "createdAt": "ISO8601",
        "scryptSalt": <16 bytes>,
        "pinAttemptCounter": <int>,
        "pinAttemptThreshold": 10,
        "lockedUntil": <None or float>,
        "termsAcceptedAt": <None or "ISO8601">,
        "termsVersion": 1,
        "wallets": [
            {
                "id": "uuid",
                "label": "daily",
                "fingerprint": <4 bytes>,
                "derivationPath": "m/44'/236'/0'",
                "wordCount": 12 or 24,
                "createdAt": "ISO8601",
                "wrappedDek": <bytes: KEK-wrapped 32-byte DEK + GCM tag>,
                "xprvCiphertext": <bytes: DEK-encrypted xprv||chaincode>,
            }, ...
        ],
    }
"""

from __future__ import annotations

import os
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cbor2
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from piwallet.core import derivation as deriv
from piwallet.core import mnemonic as mnem

VAULT_FORMAT_VERSION: int = 2
"""On-disk format version. v2 introduced per-wallet ``network`` field
(``"main"`` / ``"test"``); v1 vaults are forward-migrated on load by
treating absent ``network`` keys as ``"main"`` and rewritten as v2 on
the next ``_save``."""

#: Range of vault format versions this build is willing to *read*. Each
#: must have a forward-migration path inside :meth:`Vault._load` that
#: produces an in-memory :class:`_VaultState` matching the latest
#: schema (and therefore safe to rewrite as the latest version on
#: next save).
SUPPORTED_VAULT_VERSIONS: frozenset[int] = frozenset({1, 2})
SCRYPT_N: int = 2**15  # ~32 MB memory; ~200 ms on Zero 2 W
SCRYPT_R: int = 8
SCRYPT_P: int = 1
KEK_LEN: int = 32  # AES-256
DEK_LEN: int = 32  # AES-256
SALT_LEN: int = 16
NONCE_LEN: int = 12  # 96-bit IV per AES-GCM standard

DEFAULT_PIN_THRESHOLD: int = 10
"""Per the locked plan: 10 wrong PINs triggers permanent vault wipe."""

# Per-attempt cooldown ladder (seconds). After threshold reached, wipe is invoked.
LOCKOUT_LADDER_SECONDS: tuple[int, ...] = (0, 0, 0, 1, 2, 5, 10, 30, 60, 300)


class VaultError(Exception):
    """Base for vault-related errors."""


class VaultLockedError(VaultError):
    """Raised when an operation is attempted before unlock."""


class WrongPinError(VaultError):
    """Raised when PIN-based decrypt fails. Counter has already been bumped."""

    def __init__(self, attempts_remaining: int, lockout_until: float | None) -> None:
        self.attempts_remaining = attempts_remaining
        self.lockout_until = lockout_until
        super().__init__(
            f"wrong PIN; {attempts_remaining} attempt(s) remaining before wipe"
        )


class VaultWipedError(VaultError):
    """Raised when a wipe has occurred (either by limit or explicit user action).

    The vault file has been overwritten with random bytes and recreated
    empty. Recovery requires re-entering the mnemonic.
    """


class WalletNotFoundError(VaultError):
    """Raised when a wallet id or fingerprint isn't in the vault."""


# ---------------------------------------------------------------------------
# Internal helpers (PIN policy, KDF, primitive AEAD).
# ---------------------------------------------------------------------------


def _validate_pin(pin: str) -> None:
    if not isinstance(pin, str):
        raise ValueError("PIN must be a string")
    if not pin.isdigit():
        raise ValueError("PIN must contain only digits")
    if len(pin) < 6:
        raise ValueError("PIN must be at least 6 digits")


def _derive_kek(pin: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=KEK_LEN, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(pin.encode("utf-8"))


def _aesgcm_encrypt(key: bytes, plaintext: bytes, associated_data: bytes = b"") -> bytes:
    nonce = secrets.token_bytes(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, associated_data)
    return nonce + ct


def _aesgcm_decrypt(key: bytes, blob: bytes, associated_data: bytes = b"") -> bytes:
    if len(blob) < NONCE_LEN + 16:
        raise VaultError("ciphertext blob too short")
    nonce, ct = blob[:NONCE_LEN], blob[NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ct, associated_data)


def _zero_bytearray(buf: bytearray) -> None:
    """Best-effort overwrite of a bytearray with zeros.

    CPython doesn't guarantee this isn't optimized away, but in practice this
    does overwrite the underlying buffer. For real defense in depth, sensitive
    keys should pass through `ctypes.memset` on the buffer pointer; we keep
    that as a v2 hardening item.
    """
    for i in range(len(buf)):
        buf[i] = 0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalletRecord:
    """User-facing wallet description (no secrets).

    ``network`` is ``"main"`` for BSV mainnet and ``"test"`` for BSV
    testnet (TBSV). Every operation that renders an address — receive
    QR, xpub fingerprint encode, change re-derivation in verify — must
    consult this field. Defaults to ``"main"`` so legacy v1 vaults (no
    explicit network) read back as mainnet wallets, matching their
    pre-testnet behaviour byte-for-byte.
    """

    id: str
    label: str
    fingerprint: bytes
    derivation_path: str
    word_count: int
    created_at: str
    network: deriv.Network = deriv.NETWORK_MAIN


@dataclass
class _VaultState:
    """In-memory vault state. The xprv ciphertext payloads stay encrypted
    until the caller asks for a specific signing operation."""

    version: int = VAULT_FORMAT_VERSION
    created_at: str = field(default_factory=_now_iso)
    scrypt_salt: bytes = field(default_factory=lambda: secrets.token_bytes(SALT_LEN))
    pin_attempt_counter: int = 0
    pin_attempt_threshold: int = DEFAULT_PIN_THRESHOLD
    locked_until: float | None = None
    terms_accepted_at: str | None = None
    terms_version: int = 1
    wallets: list[dict[str, Any]] = field(default_factory=list)


class Vault:
    """File-backed encrypted vault.

    Typical lifecycle:

        v = Vault(path)
        v.create(pin="123456")            # only if file does not yet exist
        v.add_wallet(pin, mnemonic, label="daily")
        signing_key = v.derive_signing_key(pin, wallet_id, change=0, index=0)
        # ... use signing_key, then drop it ...
        v.close()
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._state: _VaultState | None = None
        if self.path.exists():
            self._load()

    # ---- existence & creation -----------------------------------------

    @property
    def exists(self) -> bool:
        """True if the vault file is present."""
        return self.path.exists()

    @property
    def is_initialized(self) -> bool:
        """True if a vault has been created (has metadata)."""
        return self._state is not None

    def create(self, pin: str) -> None:
        """Create a new empty vault and persist it.

        :raises VaultError: if a vault already exists at this path.
        """
        if self.exists:
            raise VaultError(f"vault already exists at {self.path}")
        _validate_pin(pin)
        self._state = _VaultState()
        self._save()

    def accept_terms(self, version: int) -> None:
        """Record disclaimer acknowledgment for the bonnet first-boot flow."""
        if self._state is None:
            raise VaultError("vault not initialized")
        self._state.terms_accepted_at = _now_iso()
        self._state.terms_version = version
        self._save()

    @property
    def terms_acknowledged_for(self) -> tuple[str | None, int]:
        if self._state is None:
            return None, 0
        return self._state.terms_accepted_at, self._state.terms_version

    # ---- PIN-protected operations -------------------------------------

    def list_wallets(self) -> list[WalletRecord]:
        """Public metadata only (no PIN required)."""
        if self._state is None:
            raise VaultError("vault not initialized")
        return [
            WalletRecord(
                id=w["id"],
                label=w["label"],
                fingerprint=bytes(w["fingerprint"]),
                derivation_path=w["derivationPath"],
                word_count=w["wordCount"],
                created_at=w["createdAt"],
                # v1 vault records lack `network`; treat them as
                # mainnet (which is what they were before the testnet
                # support shipped). _load() seeds this field on
                # forward migration, but we tolerate it being missing
                # in case a future v1 read path bypasses _load.
                network=w.get("network", deriv.NETWORK_MAIN),
            )
            for w in self._state.wallets
        ]

    @property
    def attempts_remaining(self) -> int:
        if self._state is None:
            return 0
        return max(0, self._state.pin_attempt_threshold - self._state.pin_attempt_counter)

    def add_wallet(
        self,
        pin: str,
        mnemonic_phrase: str,
        label: str,
        *,
        coin_type: int = deriv.BSV_COIN_TYPE,
        account_index: int = deriv.DEFAULT_ACCOUNT_INDEX,
        network: deriv.Network = deriv.DEFAULT_NETWORK,
    ) -> WalletRecord:
        """Encrypt a new wallet under the PIN-derived KEK.

        Mnemonic is converted to seed → xprv → encrypted, then immediately
        zeroed from the buffer. The mnemonic itself is NOT persisted.

        ``coin_type`` and ``account_index`` select the BIP44 account the
        wallet derives at (``m/44'/coin_type'/account_index'``).
        ``network`` selects the address-encoding network (``"main"`` or
        ``"test"``); defaults match BSV mainnet at SLIP-44 coin type
        236 / account 0. The chosen path *and* network are persisted
        in the wallet record and surfaced through
        :class:`WalletRecord` so every later operation (receive,
        verify, broadcast) knows which network it's targeting.
        """
        if self._state is None:
            raise VaultError("vault not initialized")
        _validate_pin(pin)
        mnem.validate(mnemonic_phrase)
        if coin_type < 0 or account_index < 0:
            raise VaultError(
                f"coin_type and account_index must be non-negative; got "
                f"coin_type={coin_type}, account_index={account_index}"
            )
        if network not in deriv.NETWORK_VALUES:
            raise VaultError(
                f"network must be one of {deriv.NETWORK_VALUES!r}, "
                f"got {network!r}"
            )

        # Compute keys; treat the mnemonic and seed as sensitive.
        seed_bytes = bytearray(mnem.seed_from_mnemonic(mnemonic_phrase))
        try:
            master = deriv.master_xprv_from_seed(bytes(seed_bytes))
            account = deriv.derive_account(
                master,
                coin_type=coin_type,
                account=account_index,
            )
            # Persist the full Base58Check xprv string. Slightly larger than
            # raw 64 bytes (key + chain_code), but means we don't need to
            # reassemble the BIP32 metadata on unlock.
            xprv_payload = bytearray(str(account.xprv).encode("ascii"))
            try:
                kek = _derive_kek(pin, self._state.scrypt_salt)
                dek = secrets.token_bytes(DEK_LEN)
                wrapped_dek = _aesgcm_encrypt(kek, dek)
                xprv_ciphertext = _aesgcm_encrypt(dek, bytes(xprv_payload))
                word_count = len(mnemonic_phrase.split())
                rec = {
                    "id": str(uuid.uuid4()),
                    "label": label,
                    "fingerprint": account.fingerprint,
                    "derivationPath": account.path,
                    "wordCount": word_count,
                    "createdAt": _now_iso(),
                    "network": network,
                    "wrappedDek": wrapped_dek,
                    "xprvCiphertext": xprv_ciphertext,
                }
                self._state.wallets.append(rec)
                self._save()
                return WalletRecord(
                    id=rec["id"],
                    label=label,
                    fingerprint=account.fingerprint,
                    derivation_path=account.path,
                    word_count=word_count,
                    created_at=rec["createdAt"],
                    network=network,
                )
            finally:
                _zero_bytearray(xprv_payload)
        finally:
            _zero_bytearray(seed_bytes)

    def remove_wallet(self, pin: str, wallet_id: str) -> None:
        """Delete a wallet record. PIN required to deter casual misuse."""
        if self._state is None:
            raise VaultError("vault not initialized")
        # Verify PIN by attempting to unwrap any wallet's DEK; if no wallets,
        # we still gate on the PIN having the right form (we have no way to
        # cryptographically check a PIN against an empty vault).
        _validate_pin(pin)
        if self._state.wallets:
            self._unwrap_dek(pin, self._state.wallets[0])
        before = len(self._state.wallets)
        self._state.wallets = [w for w in self._state.wallets if w["id"] != wallet_id]
        if len(self._state.wallets) == before:
            raise WalletNotFoundError(wallet_id)
        self._save()

    def rename_wallet(self, pin: str, wallet_id: str, new_label: str) -> None:
        if self._state is None:
            raise VaultError("vault not initialized")
        trimmed = new_label.strip()
        if not trimmed:
            raise VaultError("wallet label cannot be empty")
        _validate_pin(pin)
        if self._state.wallets:
            self._unwrap_dek(pin, self._state.wallets[0])
        for w in self._state.wallets:
            if w["id"] == wallet_id:
                w["label"] = trimmed
                self._save()
                return
        raise WalletNotFoundError(wallet_id)

    def change_pin(self, old_pin: str, new_pin: str) -> None:
        """Re-encrypt every wallet's DEK under a new PIN.

        Verifies ``old_pin`` by unwrapping the first wallet's DEK (the
        attempt-counter / wipe-on-N-failures contract is exactly the
        same as a normal unlock). On success a *fresh* scrypt salt is
        generated and every wallet's wrapped DEK is re-encrypted under
        ``scrypt(new_pin, new_salt)``. Salt rotation matters because
        the ciphertext binds the *combination* of (salt, PIN) — if an
        attacker has an old snapshot of ``vault.bin`` they can't reuse
        the old ciphertext as a brute-force oracle against the new
        PIN.

        The rewrap loop is staged: every new wrapped-DEK blob is
        computed in memory first, then committed in one ``_save()``.
        A mid-loop crash leaves the on-disk vault untouched, so the
        operator can retry with the still-valid old PIN.

        :raises VaultError: vault not initialized / PIN format invalid.
        :raises WrongPinError: ``old_pin`` did not decrypt the first
            wallet's DEK; attempt counter has already been bumped.
        :raises VaultWipedError: too many failed attempts; vault wiped.
        """
        if self._state is None:
            raise VaultError("vault not initialized")
        _validate_pin(old_pin)
        _validate_pin(new_pin)
        if old_pin == new_pin:
            # Pure no-op. The UI normally guards against this, but if
            # it slips through we want a stable success without
            # touching the salt — rotating the salt for an unchanged
            # PIN is wasted work and adds nothing to the threat model.
            return

        if not self._state.wallets:
            # No ciphertext exists to verify ``old_pin`` against — same
            # limitation as :meth:`remove_wallet` / :meth:`rename_wallet`
            # on an empty vault. Rotate the salt anyway so the next
            # wallet added will be wrapped under the new PIN's KEK.
            self._state.scrypt_salt = secrets.token_bytes(SALT_LEN)
            self._save()
            return

        # Verify old PIN. Raises WrongPinError / VaultWipedError on the
        # usual conditions and bumps the attempt counter exactly once.
        first_dek = self._unwrap_dek(old_pin, self._state.wallets[0])

        old_kek = _derive_kek(old_pin, self._state.scrypt_salt)
        new_salt = secrets.token_bytes(SALT_LEN)
        new_kek = _derive_kek(new_pin, new_salt)

        # Re-wrap every DEK *before* mutating any state, so a failure
        # in the middle of the loop leaves the vault file intact.
        re_wrapped: list[bytes] = []
        for i, w in enumerate(self._state.wallets):
            dek = first_dek if i == 0 else _aesgcm_decrypt(old_kek, w["wrappedDek"])
            re_wrapped.append(_aesgcm_encrypt(new_kek, dek))

        # All wrappings succeeded — commit.
        self._state.scrypt_salt = new_salt
        for w, blob in zip(self._state.wallets, re_wrapped, strict=True):
            w["wrappedDek"] = blob
        self._save()

    def derive_signing_key(self, pin: str, wallet_id: str, change: int, index: int):
        """Decrypt the wallet's xprv and derive a leaf signing key.

        The decrypted xprv is **not** retained on `Vault`; the caller is
        responsible for using and dropping the returned key promptly.
        """
        if self._state is None:
            raise VaultError("vault not initialized")
        _validate_pin(pin)
        wallet = self._find_wallet(wallet_id)
        dek = self._unwrap_dek(pin, wallet)
        xprv_payload = bytearray(_aesgcm_decrypt(dek, wallet["xprvCiphertext"]))
        try:
            xprv_str = self._reconstruct_xprv_str(xprv_payload, wallet)
            xprv = deriv.parse_xprv(xprv_str)
            return deriv.derive_signing_key(xprv, change, index)
        finally:
            _zero_bytearray(xprv_payload)

    def get_account_xpub(self, pin: str, wallet_id: str) -> str:
        """Return the account xpub (string) for the given wallet."""
        if self._state is None:
            raise VaultError("vault not initialized")
        _validate_pin(pin)
        wallet = self._find_wallet(wallet_id)
        dek = self._unwrap_dek(pin, wallet)
        xprv_payload = bytearray(_aesgcm_decrypt(dek, wallet["xprvCiphertext"]))
        try:
            xprv_str = self._reconstruct_xprv_str(xprv_payload, wallet)
            xprv = deriv.parse_xprv(xprv_str)
            return str(xprv.xpub())
        finally:
            _zero_bytearray(xprv_payload)

    # ---- file ops -----------------------------------------------------

    def wipe(self) -> None:
        """Permanently destroy vault state. Overwrites file with random bytes."""
        if self.path.exists():
            length = self.path.stat().st_size or 4096
            with self.path.open("r+b", buffering=0) as f:
                f.write(secrets.token_bytes(length))
                f.flush()
                os.fsync(f.fileno())
            self.path.unlink()
        self._state = None

    def close(self) -> None:
        """No-op for now; provided for symmetry and future resource cleanup."""
        self._state = None

    # ---- internals ----------------------------------------------------

    def _find_wallet(self, wallet_id: str) -> dict[str, Any]:
        assert self._state is not None
        for w in self._state.wallets:
            if w["id"] == wallet_id:
                return w
        raise WalletNotFoundError(wallet_id)

    def _unwrap_dek(self, pin: str, wallet: dict[str, Any]) -> bytes:
        """Verify PIN by attempting to unwrap the wallet's DEK.

        Bumps the attempt counter pre-decrypt, decrements on success. On
        threshold breach, wipes the vault and raises `VaultWipedError`.
        """
        assert self._state is not None
        # Pre-bump counter and persist; only decrement on success.
        self._state.pin_attempt_counter += 1
        self._save()
        if self._state.pin_attempt_counter > self._state.pin_attempt_threshold:
            # Should not reach here normally; below we wipe on the threshold.
            self.wipe()
            raise VaultWipedError("vault wiped: too many failed PIN attempts")

        kek = _derive_kek(pin, self._state.scrypt_salt)
        try:
            dek = _aesgcm_decrypt(kek, wallet["wrappedDek"])
        except Exception as exc:
            remaining = max(0, self._state.pin_attempt_threshold - self._state.pin_attempt_counter)
            if remaining == 0:
                self.wipe()
                raise VaultWipedError("vault wiped: too many failed PIN attempts") from exc
            raise WrongPinError(attempts_remaining=remaining, lockout_until=None) from exc

        # Success -> fully reset the attempt counter.
        self._state.pin_attempt_counter = 0
        self._save()
        return dek

    def _reconstruct_xprv_str(self, payload: bytearray, wallet: dict[str, Any]) -> str:
        """Decode the decrypted ASCII payload back into a Base58Check xprv string."""
        return bytes(payload).decode("ascii")

    def _load(self) -> None:
        try:
            raw = self.path.read_bytes()
            data = cbor2.loads(raw)
        except (cbor2.CBORDecodeError, OSError, EOFError):
            # Corrupt or non-CBOR file. Leave `_state = None` so the rest of
            # the API treats this as "not initialized"; create() will refuse
            # to overwrite, and a future maintenance command will be needed
            # to clear it. Avoids a CBOR exception leaking out of __init__.
            return
        if not isinstance(data, dict):
            raise VaultError("corrupted vault: top-level not a map")
        on_disk_version = data.get("vaultVersion")
        if on_disk_version not in SUPPORTED_VAULT_VERSIONS:
            raise VaultError(
                f"unsupported vault version: {on_disk_version!r}; "
                f"this build supports {sorted(SUPPORTED_VAULT_VERSIONS)!r}"
            )
        wallets = list(data.get("wallets", []))
        if on_disk_version < 2:
            # v1 -> v2: every existing wallet was BSV mainnet. Inject
            # the explicit network discriminator so list_wallets and
            # add_wallet can rely on the field being present. The
            # rewrite happens on the next _save (always at the latest
            # version), so a v1 file becomes v2 the first time it's
            # mutated.
            for w in wallets:
                w.setdefault("network", deriv.NETWORK_MAIN)
        # Whatever we read, the in-memory state reports the latest
        # version so the next save writes the canonical schema.
        self._state = _VaultState(
            version=VAULT_FORMAT_VERSION,
            created_at=data["createdAt"],
            scrypt_salt=bytes(data["scryptSalt"]),
            pin_attempt_counter=data.get("pinAttemptCounter", 0),
            pin_attempt_threshold=data.get("pinAttemptThreshold", DEFAULT_PIN_THRESHOLD),
            locked_until=data.get("lockedUntil"),
            terms_accepted_at=data.get("termsAcceptedAt"),
            terms_version=data.get("termsVersion", 1),
            wallets=wallets,
        )

    def _save(self) -> None:
        if self._state is None:
            raise VaultError("nothing to save: vault not initialized")
        body = {
            "vaultVersion": self._state.version,
            "createdAt": self._state.created_at,
            "scryptSalt": self._state.scrypt_salt,
            "pinAttemptCounter": self._state.pin_attempt_counter,
            "pinAttemptThreshold": self._state.pin_attempt_threshold,
            "lockedUntil": self._state.locked_until,
            "termsAcceptedAt": self._state.terms_accepted_at,
            "termsVersion": self._state.terms_version,
            "wallets": self._state.wallets,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("wb") as f:
            f.write(cbor2.dumps(body))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
