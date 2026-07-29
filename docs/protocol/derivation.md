# Derivation and wallet identity — v1

This document defines how a PiWalletSV wallet derives its keys and
addresses from a BIP39 mnemonic, and how the resulting wallet is
identified on the wire.

## 1. Seed

A wallet is created from a BIP39 mnemonic. Both 12-word and 24-word
mnemonics are supported. The seed is computed per BIP39:

```
seed = PBKDF2-HMAC-SHA512(
    password   = NFKD(mnemonic),
    salt       = "mnemonic" || NFKD(passphrase),     # passphrase is "" for v1
    iterations = 2048,
    dkLen      = 64,
)
```

`passphrase` is the empty string in v1. We may expose an optional
user-supplied passphrase in v2.

The resulting 64-byte seed is the input to BIP32 master derivation.

## 2. Master and account keys

BIP32 master derivation is unchanged from the spec:

```
I            = HMAC-SHA512(key = "Bitcoin seed", data = seed)
master_xprv  = I[0..32]   # 32-byte private key
master_chain = I[32..64]  # 32-byte chain code
```

The signer keeps the master xprv encrypted at rest (see the security
chapter for details). The account-level xprv is derived once and is
the key that's actually exposed through the public API.

The account-level path is fixed at:

```
m / 44' / 236' / 0'
```

That is:

- `44'`  — BIP44 purpose (hardened).
- `236'` — BSV's SLIP-44 coin type (hardened).
- `0'`   — account index, hardened. v1 ships with a single account
  per wallet; multi-account is deferred to v2.

A wallet's exported `xpub_export.path` field MUST be the literal
string `"m/44'/236'/0'"`. Any other value SHOULD cause a companion to
reject the envelope.

## 3. Address derivation

Receive and change addresses are derived non-hardened from the
account xpub:

```
receive_i = account_xpub / 0 / i     # external chain, i ∈ [0, 2^31)
change_i  = account_xpub / 1 / i     # internal chain, i ∈ [0, 2^31)
```

The on-the-wire `derivation` arrays in `unsigned_proposal` are
`[branch, index]` two-tuples; `branch` is `0` (receive) or `1` (change)
and `index` is a non-hardened 31-bit unsigned integer.

The signer MUST reject:

- `branch` not in `{0, 1}`;
- `index < 0`;
- `index >= 2^31` (= `0x80000000`, which would be a hardened index
  the signer cannot derive from an xpub anyway).

### 3.1 Address format

PiWalletSV v1 supports **P2PKH** addresses only on **BSV mainnet**.

```
pubkey       = secp256k1 point at <xpub>/<branch>/<index>
hash160      = RIPEMD160(SHA256(serialized_compressed_pubkey))
payload      = 0x00 || hash160         # 0x00 = BSV mainnet P2PKH version
checksum     = SHA256(SHA256(payload))[0..4]
address      = base58(payload || checksum)
```

The compressed public key is 33 bytes (`0x02|0x03 || X`). Other
encodings (uncompressed `0x04 || X || Y`, hybrid, etc.) MUST NOT be
used.

The corresponding P2PKH locking script for an address is the standard
Bitcoin script:

```
OP_DUP OP_HASH160 <20-byte hash160> OP_EQUALVERIFY OP_CHECKSIG
```

In hex this is `76a914 <hash160> 88ac` (25 bytes total).

`unsigned_proposal.outputs[*].script` MUST contain this hex form,
lowercase. Companions building proposals SHOULD construct the script
from the recipient's base58 address with the inverse decode; they
SHOULD NOT inline an address string into the envelope.

Future protocol revisions may add P2PK, multisig, or token scripts;
v1 deliberately constrains the script set so the signer's parse can
be small and total.

## 4. Wallet fingerprint

The companion identifies a paired wallet (and routes proposals back
to it) by a 4-byte **self fingerprint** of the account xpub:

```
fp = RIPEMD160(SHA256(serialized_compressed_pubkey_at_account_xpub))[0..4]
```

This is the BIP32 "fingerprint" of the account-level xpub itself.
Note that this is **not** the `parent_fingerprint` field that BIP32
serializes inside an extended key, which references the parent's
public key. We use the self-fingerprint because two unrelated wallets
will always have different self-fingerprints, whereas they could
share a parent-fingerprint if they derive from the same intermediate
node.

A companion MUST:

1. Compute the expected self-fingerprint locally when it receives an
   `xpub_export` and compare it to the envelope's `fp` field. If they
   don't match, the companion MUST refuse to save the wallet.
2. Include the same 4-byte value as `walletFp` in every
   `unsigned_proposal` it sends back, so the signer can route the
   proposal to the right vault entry when more than one wallet is
   stored.
3. Surface the fingerprint to the user in hex (8 lowercase hex chars,
   no separator) — this is how PiWalletSV's bonnet UI and companion
   UI both display it.

A signer MUST:

1. Refuse to sign any proposal whose `walletFp` doesn't match a
   stored wallet's self-fingerprint.
2. Refuse to emit a `signed_tx` whose `walletFp` value differs from
   the proposal it just signed.

## 5. Recovery gap-limit and counters

Normal operation does not discover coins by walking addresses. Explicit
disaster recovery follows BIP44's gap-limit rule and defaults to **20 unused
addresses in a row before abandoning a branch**. Implementations MAY use a
larger gap, but SHOULD NOT go lower; older wallets paired against the same xpub
may have created sparse usage patterns. A recovery walker MUST query address
history as well as current UTXOs so a fully-spent address counts as used.

The Pi's encrypted wallet state is authoritative for receive and change
counters. The companion mirrors those counters after a state receipt and MAY
temporarily advance its public receive pointer as addresses are issued; that
new high-water mark is committed in the next `stateSync` transition.

## 6. Sample / canonical wallet

The canonical test vectors in `tests/fixtures/addresses_canonical.json`
use the BIP39 mnemonic:

```
abandon abandon abandon abandon abandon abandon abandon abandon
abandon abandon abandon about
```

with an empty passphrase. The fixture records the account xpub, its
4-byte fingerprint, and the first few receive/change addresses. Any
v1-conformant implementation MUST reproduce them exactly.

See [`conformance.md`](conformance.md) for the file's exact format
and how to use it as a regression check.
