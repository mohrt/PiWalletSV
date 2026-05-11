# Envelope encoding — v1

This document specifies the on-the-wire payloads that travel between
the signer and a companion. There are three message kinds in v1;
each is a CBOR map, gzip-compressed, and then carried across the
air gap via the multipart QR transport described in
[`qr-transport.md`](qr-transport.md).

## 1. Outer framing

Every envelope, regardless of `kind`, has the same outer framing:

```
envelope_bytes = gzip(cbor(body))
```

Where:

- **`cbor`** is RFC 8949 Concise Binary Object Representation.
- **`gzip`** is RFC 1952 gzip with deflate compression. The reference
  implementations use `compresslevel=9, mtime=0`, but a decoder MUST
  NOT require any specific compression level or mtime.
- **`body`** is a CBOR map (major type 5) with the schema defined
  below.

A decoder MUST:

1. Validate the gzip header before attempting CBOR.
2. Reject any payload whose decompressed CBOR is not a top-level map.
3. Reject any payload whose `v` integer is not `1` (the current
   version constant).
4. Reject any payload whose `kind` string is not one of the values
   in [§2](#2-message-kinds).

A decoder SHOULD limit the maximum decompressed size it is willing
to accept (the reference implementation parses up to a few hundred
KB without complaint; envelopes carrying multi-input BEEF blobs are
typically 1–10 KB).

### 1.1 CBOR encoding rules

The envelope body is encoded as a CBOR map. The encoder rules below
keep the output byte-identical across the reference implementations,
which is useful when comparing fixtures, but a strict-bytes compare
is **not** required for interop:

- **Map values are typed primitives**, not CBOR tagged values. We
  never emit major type 6 tags. Decoders MAY treat any tagged value
  as malformed; the reference decoders ignore tags and use the
  underlying primitive, but the reference encoders never produce
  them.
- **Map keys are short text strings.** All keys are ASCII; none start
  with `_` or contain whitespace.
- **`bytes` fields are major type 2**, not major-type-3 hex strings.
  The single exception is `rawHex` and `txid` in `signed_tx`, where
  the value is the hex-string form of an already-public on-chain tx
  (those fields are text strings for human-readable QR debugging).
- **Integers fit in 64 bits.** A v1 implementation MAY normalize
  numeric fields to safe-integer range; CBOR's bignum (major type 6
  tag 2/3) is not used. Satoshi amounts (`sats`, `feeRate`) fit
  comfortably in 53 bits.

Decoders MUST accept both CBOR-canonical and non-canonical map key
orderings; the reference Python implementation does not enforce
ordering on encode but the JavaScript implementation produces a
stable order via `Map`-based input. Two implementations producing
the same *logical* envelope MAY produce different bytes.

The reference test suite cross-decodes: the Python encoder emits
`proposal_01.cbor`, and the TypeScript decoder asserts every field
parses to the same logical values. This validates inter-op at the
*decoder* level; third-party encoders are not required to produce
byte-identical output to be conformant.

## 2. Message kinds

The `kind` field is one of three short strings:

| `kind`     | Direction                  | Purpose                                           |
| ---------- | -------------------------- | ------------------------------------------------- |
| `"xpub"`   | signer ⟶ companion         | Pairing: hand the account xpub to the companion.  |
| `"tx"`     | companion ⟶ signer         | Spend request the signer must verify before sign. |
| `"signed"` | signer ⟶ companion         | Resulting raw signed transaction + txid.          |

Every envelope's outer map has two universally-required keys:

| Key    | CBOR type   | Value                       |
| ------ | ----------- | --------------------------- |
| `v`    | uint        | `1` (current version).      |
| `kind` | text string | one of `"xpub"`, `"tx"`, `"signed"`. |

The remaining keys are kind-specific.

## 3. `xpub_export` (`kind = "xpub"`)

Direction: **signer → companion**. The signer emits this once during
pairing so the companion can stand up a watch-only view of the
wallet's addresses and start querying balances.

```
{
    "v":     1,
    "kind":  "xpub",
    "xpub":  <text string>,    // Base58Check serialized BIP32 xpub at m/44'/236'/0'
    "path":  <text string>,    // canonical path, MUST be "m/44'/236'/0'"
    "label": <text string>,    // human-readable label the signer reports
    "fp":    <bytes, length 4> // self-fingerprint of `xpub` (see derivation.md §4)
}
```

Constraints:

- `xpub` SHOULD parse as a Base58Check BIP32 extended public key at
  depth 3, with the correct version bytes for mainnet (`0488B21E`).
- `path` MUST be `m/44'/236'/0'` in v1.
- `label` is informational. The companion MAY rename a wallet locally
  before persisting it; the signer's label is treated as a default,
  not authoritative metadata.
- `fp` MUST equal the self-fingerprint computed from `xpub`. The
  companion MUST verify this equality.

A companion seeing two distinct `xpub_export` envelopes with the same
`fp` and `path` MUST treat them as the same wallet (e.g., re-pairing
after a vault wipe) and surface that to the user.

## 4. `unsigned_proposal` (`kind = "tx"`)

Direction: **companion → signer**. Contains everything the signer
needs to verify the spend without any network access of its own,
then sign it.

```
{
    "v":               1,
    "kind":            "tx",
    "walletFp":        <bytes, length 4>,    // routes to the wallet that must sign
    "inputs":          [ <ProposalInput>, ... ],   // non-empty
    "outputs":         [ <ProposalOutput>, ... ],  // non-empty
    "changeIndex":     <uint>,               // index into outputs[] of the change output
    "changeDerivation":[ <uint>, <uint> ],   // [branch, index] for change re-derivation
    "feeRate":         <uint>,               // sats per 1000 bytes (advisory)
    "locktime":        <uint>,               // optional; default 0
    "headerAnchors":   { <uint>: <bytes, length 32>, ... }   // optional; height → root
}
```

### 4.1 `ProposalInput`

```
{
    "txid":       <text string, 64 lowercase hex chars>,
    "vout":       <uint>,
    "sats":       <uint>,           // the claimed satoshi value at vout
    "beef":       <bytes>,           // BSV BEEF carrying the prior tx + Merkle path
    "merklePath": <bytes>,           // standalone binary Merkle path
    "derivation": [ <uint>, <uint> ] // [branch, index] for the input's signing key
}
```

`beef` and `merklePath` byte serializations are defined in
[`spv.md`](spv.md). The two fields are **partly redundant** in v1
because `beef` already carries the Merkle path attached to the prior
tx; we keep both because some signers will only re-implement one
parser (and because the Pi-side reference implementation cross-checks
them as a sanity test).

The `sats` value is a claim by the companion; the signer MUST
re-derive the real value from the prior tx in `beef` and reject any
mismatch.

### 4.2 `ProposalOutput`

```
{
    "script": <text string, lowercase hex>,    // locking script bytes as hex
    "sats":   <uint>
}
```

In v1, every `script` MUST be a P2PKH locking script (see
[`derivation.md`](derivation.md) §3.1). Signers MAY refuse to sign
proposals containing non-P2PKH outputs and surface the reason to the
user.

### 4.3 Change output

The output at index `changeIndex` is the one the signer will
**re-derive** from `walletFp`'s xpub using `changeDerivation` as
`[branch, index]`. If the re-derived P2PKH script doesn't equal the
output's `script` byte-for-byte, the signer MUST abort. This is the
core "you cannot trick me into paying my change to the wrong place"
check.

A v1 proposal MUST contain at least one change output. The reference
companion folds change below the 546-sat dust threshold into the
miner fee, but as long as the proposal carries an explicit change
output the signer will accept it. A future protocol revision may
introduce an explicit no-change marker; until then, build with
change.

### 4.4 `headerAnchors`

A CBOR map from **block height** (uint) to **block Merkle root**
(`bytes`, exactly 32 bytes, big-endian display form — the same byte
order that block explorers print). Each anchor declares "this is
the Merkle root the user has accepted as canonical for this height".

Every input's Merkle path MUST resolve to a root that's present in
`headerAnchors` at the path's `block_height`. The signer SHOULD
display each `(height, root)` pair to the user before signing,
because a colluding companion + WhatsOnChain endpoint cannot lie to
the signer about a root the user has just read on the bonnet screen.

`headerAnchors` MAY be empty only when the proposal has zero inputs,
which is itself prohibited in v1; a v1 signer therefore SHOULD
require at least one anchor.

## 5. `signed_tx` (`kind = "signed"`)

Direction: **signer → companion**. Returned after a successful sign.

```
{
    "v":        1,
    "kind":     "signed",
    "walletFp": <bytes, length 4>,    // MUST equal the proposal's walletFp
    "rawHex":   <text string>,        // raw signed tx as hex
    "txid":     <text string, 64 lowercase hex chars>
}
```

A companion broadcasting this transaction SHOULD verify, before
calling its broadcast endpoint:

1. `walletFp` equals the wallet it expected to sign.
2. `txid` re-computes correctly from `rawHex` (double-SHA256, byte
   reverse). If the broadcaster echoes back a different txid than
   the signer claimed, treat that as a malleability red flag and
   warn the user — the reference companion does this.

## 6. Worked example

`tests/fixtures/proposal_01.cbor` is a canonical
`unsigned_proposal` envelope for the BIP39 mnemonic in
[`derivation.md`](derivation.md) §6. The companion metadata file
`tests/fixtures/proposal_01.json` reports the addresses, amounts,
block height, and Merkle root involved.

`tests/fixtures/proposal_01_decoded.json` (generated by
`scripts/dump_decoded_envelope.py`) lists every CBOR field, its
type, length, and either its scalar value or a hex-encoded sample of
the first/last bytes of binary fields. Use it as a structural
reference when implementing a decoder. See
[`conformance.md`](conformance.md) for details.
