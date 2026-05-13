"""HD wallet derivation: BIP32 + BIP44 + optional testnet support.

PiWalletSV v1 design: each on-device wallet uses a SINGLE BIP44 account
(default ``m/44'/236'/0'`` for BSV mainnet). Coin type and account
index are configurable per wallet (since the v0 wallet-create
chooser shipped); the v1.1 addition here is per-wallet **network**
selection so a wallet's seed can drive either BSV mainnet
(`"main"`) or testnet (`"test"`) addresses without re-derivation.

Two-tier API:

- `master_xprv_from_seed(seed)` -> bsv.hd.Xprv at depth 0.
- `account_xprv(master)` -> Xprv at `m/44'/236'/0'` (depth 3, hardened).
- `account_xpub(account_xprv)` -> Xpub at the same path. This is what gets
  exported to the companion PWA over QR for watch-only address discovery.
- `derive_address(xpub, change, index, *, network="main")` -> str.
  Derives a P2PKH address from the account xpub, taking the
  non-hardened `change/index` path. The address prefix byte is
  selected by ``network``: mainnet uses ``0x00`` (legacy
  Bitcoin / BSV mainnet) and testnet uses ``0x6F``. The PWA does
  this; the Pi does this for the change re-derivation safety check
  in sign.py / verify.py.
- `derive_signing_key(xprv, change, index)` -> bsv.PrivateKey. Used on
  the Pi during signing. Signing is network-independent (same curve
  + same sighash math); only the *address* derived from the public
  key changes.

The plan's "verify, then sign" rule depends on ``derive_address``
being a pure function of (xpub, change, index, network): the Pi
re-derives the proposal's claimed change ``scriptPubKey`` and rejects
mismatches. Network is therefore part of the verification contract,
not a UI hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from bsv import PrivateKey, hash160
from bsv.constants import Network as _BsvNetwork
from bsv.hd import Xprv, Xpub
from bsv.hd import master_xprv_from_seed as _master_xprv_from_seed

#: Network discriminator. ``"main"`` selects BSV mainnet (P2PKH prefix
#: ``0x00``); ``"test"`` selects BSV testnet (P2PKH prefix ``0x6F``).
#: Stored in :class:`AccountKeys`, persisted on each :class:`WalletRecord`,
#: and carried in the xpub_export envelope to the companion.
Network = Literal["main", "test"]

NETWORK_MAIN: Network = "main"
NETWORK_TEST: Network = "test"
NETWORK_VALUES: tuple[Network, ...] = (NETWORK_MAIN, NETWORK_TEST)
DEFAULT_NETWORK: Network = NETWORK_MAIN

# Internal mapping to bsv-sdk's Network enum used by PublicKey.address.
_BSV_NETWORK_FOR: dict[Network, _BsvNetwork] = {
    NETWORK_MAIN: _BsvNetwork.MAINNET,
    NETWORK_TEST: _BsvNetwork.TESTNET,
}


def _bsv_network(network: Network) -> _BsvNetwork:
    try:
        return _BSV_NETWORK_FOR[network]
    except KeyError:
        raise ValueError(
            f"network must be one of {NETWORK_VALUES!r}, got {network!r}"
        ) from None

BSV_COIN_TYPE: int = 236
"""SLIP-44 coin type for Bitcoin SV."""

BIP32_HARDENED: int = 0x80000000
"""Offset added to indices that should be derived using hardened CKD."""

ACCOUNT_DERIVATION_PATH_FMT: str = "m/44'/{coin}'/{account}'"
"""Format of the derivation path for the account-level xprv/xpub."""

DEFAULT_ACCOUNT_INDEX: int = 0
"""v1 ships with one account per wallet; this is its index."""

CHANGE_RECEIVE: int = 0
"""BIP44 receive branch (external chain)."""

CHANGE_INTERNAL: int = 1
"""BIP44 change branch (internal chain)."""


@dataclass(frozen=True)
class AccountKeys:
    """The set of keys we hand to the rest of the wallet for one account.

    `xprv` stays on the Pi (encrypted in the vault between sessions);
    `xpub` is the safe-to-share watch-only export.
    """

    xprv: Xprv
    xpub: Xpub
    path: str
    fingerprint: bytes  # 4-byte fingerprint of `xpub`, used for routing envelopes
    coin_type: int
    account: int


def master_xprv_from_seed(seed: bytes) -> Xprv:
    """Compute the BIP32 master xprv from a 64-byte BIP39 seed.

    :raises ValueError: if `seed` is not 64 bytes (BIP32 spec for HMAC-SHA512).
    """
    if not isinstance(seed, (bytes, bytearray)):
        raise TypeError(f"seed must be bytes, got {type(seed).__name__}")
    if len(seed) != 64:
        raise ValueError(f"seed must be 64 bytes, got {len(seed)}")
    return _master_xprv_from_seed(bytes(seed))


def account_path(coin_type: int = BSV_COIN_TYPE, account: int = DEFAULT_ACCOUNT_INDEX) -> str:
    """Return the canonical BIP44 account path string."""
    return ACCOUNT_DERIVATION_PATH_FMT.format(coin=coin_type, account=account)


def derive_account(
    master_xprv: Xprv,
    *,
    coin_type: int = BSV_COIN_TYPE,
    account: int = DEFAULT_ACCOUNT_INDEX,
) -> AccountKeys:
    """Derive `m/44'/coin_type'/account'` from a master xprv.

    Returns the account xprv/xpub bundle plus a routing fingerprint and the
    canonical path string.
    """
    if master_xprv.depth != 0:
        raise ValueError(f"expected master xprv (depth 0), got depth {master_xprv.depth}")

    xprv = (
        master_xprv.ckd(44 + BIP32_HARDENED)
        .ckd(coin_type + BIP32_HARDENED)
        .ckd(account + BIP32_HARDENED)
    )
    xpub = xprv.xpub()
    return AccountKeys(
        xprv=xprv,
        xpub=xpub,
        path=account_path(coin_type, account),
        fingerprint=key_fingerprint(xpub),
        coin_type=coin_type,
        account=account,
    )


def key_fingerprint(key: Xpub | Xprv) -> bytes:
    """Compute this key's own 4-byte fingerprint per BIP32 (RIPEMD160(SHA256(pubkey))[:4]).

    Note: the `.fingerprint` attribute on bsv-sdk Xprv/Xpub is the *parent's*
    fingerprint (the field that gets serialized in the extended key). Routing
    proposals between paired wallets needs the *self* fingerprint, which is
    what this function returns.
    """
    if isinstance(key, Xprv):
        pub = key.public_key()
    else:
        pub = key.public_key()
    return hash160(pub.serialize())[:4]


def _validate_branch_index(change: int, index: int) -> None:
    if change not in (CHANGE_RECEIVE, CHANGE_INTERNAL):
        raise ValueError(f"change must be 0 (receive) or 1 (internal), got {change}")
    if index < 0 or index >= BIP32_HARDENED:
        raise ValueError(f"index out of non-hardened range: {index}")


def derive_address(
    xpub: Xpub,
    change: int,
    index: int,
    *,
    network: Network = DEFAULT_NETWORK,
) -> str:
    """Derive a P2PKH address at `<xpub>/change/index` from the account xpub.

    Pure function (no I/O). Used by:

    - the companion PWA to enumerate addresses for UTXO discovery,
    - the Pi during sign-time change re-derivation,
    - the receive flow on the PWA.

    ``network`` selects the base58check version byte (``0x00`` for
    mainnet, ``0x6F`` for testnet). The xpub bytes themselves are the
    same regardless of network — same secp256k1 public key and chain
    code — but the rendered string differs. Defaults to ``"main"`` so
    the existing single-arg callsites stay byte-for-byte identical to
    the pre-testnet codebase.
    """
    _validate_branch_index(change, index)
    leaf = xpub.ckd(change).ckd(index)
    return leaf.key.address(network=_bsv_network(network))


def derive_signing_key(account_xprv: Xprv, change: int, index: int) -> PrivateKey:
    """Derive the leaf private key at `<account_xprv>/change/index`.

    Returns a `bsv.PrivateKey`. The caller is responsible for memory hygiene
    around the returned key per the plan's signing-path zeroing pattern.
    """
    _validate_branch_index(change, index)
    leaf = account_xprv.ckd(change).ckd(index)
    return leaf.private_key()


def parse_xpub(xpub_str: str) -> Xpub:
    """Parse a Base58Check-serialized xpub string back into an `Xpub` object."""
    return Xpub(xpub_str)


def parse_xprv(xprv_str: str) -> Xprv:
    """Parse a Base58Check-serialized xprv string back into an `Xprv` object."""
    return Xprv(xprv_str)
