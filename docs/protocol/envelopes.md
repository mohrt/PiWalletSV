# Envelope encoding — v2

This document specifies the on-the-wire payloads that travel between
the signer and a companion. There are three message kinds in v2;
each is a CBOR map, gzip-compressed, and then carried across the
air gap via the multipart QR transport described in
[`qr-transport.md`](qr-transport.md).

> **v2 schema highlights** (changes from v1):
>
> - Per-input `merklePath` field removed — the BRC-62 BEEF blob
>   already carries the BRC-74 BUMP path attached to the prior tx,
>   so the standalone field was redundant.
> - `signed_tx.rawHex` + `signed_tx.txid` replaced with a single
>   `atomicBeef` field carrying BRC-95 Atomic BEEF. The TXID is
>   declared inside the Atomic BEEF wrapper itself.
> - `v` bumped from `1` to `2`. v1 envelopes are intentionally
>   rejected by v2 implementations so out-of-sync producers fail
>   loudly.
> - `headerAnchors` (the v1 `height → merkle_root` map the
>   signer trusts) is **retained** in v2. PiWalletSV deliberately
>   does not require strong on-device SPV; see
>   [`spv.md`](spv.md) §1 for the trust-model discussion.

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
3. Reject any payload whose `v` integer is not `2` (the current
   version constant). v1 producers must be upgraded; the v2
   reference implementations do not silently accept stale envelopes.
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
  The hex-string variants v1 used in `signed_tx.rawHex` /
  `signed_tx.txid` were dropped in v2; the entire signed-tx payload
  is a single binary `atomicBeef` field now (see §5).
- **Integers fit in 64 bits.** A v2 implementation MAY normalize
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
| `v`    | uint        | `2` (current version).      |
| `kind` | text string | one of `"xpub"`, `"tx"`, `"signed"`. |

The remaining keys are kind-specific.

## 3. `xpub_export` (`kind = "xpub"`)

Direction: **signer → companion**. The signer emits this once during
pairing so the companion can stand up a watch-only view of the
wallet's addresses and start querying balances.

```
{
    "v":     2,
    "kind":  "xpub",
    "xpub":  <text string>,    // Base58Check serialized BIP32 xpub at the path below
    "path":  <text string>,    // BIP44 account path, e.g. "m/44'/236'/0'"
    "label": <text string>,    // human-readable label the signer reports
    "fp":    <bytes, length 4>,// self-fingerprint of `xpub` (see derivation.md §4)
    "net":   <text string>     // OPTIONAL: "main" (default) or "test"; absence = "main"
}
```

Constraints:

- `xpub` SHOULD parse as a Base58Check BIP32 extended public key at
  depth 3. Mainnet xpubs use version bytes `0488B21E`; testnet xpubs
  use `043587CF`. The companion MUST tolerate both for `net="test"`
  envelopes.
- `path` is a BIP44 account path of the form `m/44'/<coin>'/<account>'`.
  The signer surfaces this so the companion can render path metadata;
  in v2 the signer rejects paths outside this shape.
- `label` is informational. The companion MAY rename a wallet locally
  before persisting it; the signer's label is treated as a default,
  not authoritative metadata.
- `fp` MUST equal the self-fingerprint computed from `xpub`. The
  companion MUST verify this equality.
- `net` is OPTIONAL and defaults to `"main"`. Allowed values are
  `"main"` (BSV mainnet) and `"test"` (BSV testnet). The companion
  MUST honour this field when:
  - rendering P2PKH addresses (mainnet uses base58check prefix
    `0x00`, testnet uses `0x6F`),
  - selecting its WhatsOnChain (or equivalent) endpoint
    (mainnet: `…/v1/bsv/main`, testnet: `…/v1/bsv/test`).
  Older envelopes (pre-multinetwork) lack this field; the companion
  MUST treat its absence as `"main"` to avoid breaking existing
  pairings.

A companion seeing two distinct `xpub_export` envelopes with the same
`fp` and `path` MUST treat them as the same wallet (e.g., re-pairing
after a vault wipe) and surface that to the user. Re-pairing across
networks (same `fp` + `path` but different `net`) is treated as a
distinct wallet entry; the companion warns the user before discarding
prior watch-only state.

## 4. `unsigned_proposal` (`kind = "tx"`)

Direction: **companion → signer**. Contains everything the signer
needs to verify the spend without any network access of its own,
then sign it.

```
{
    "v":                2,
    "kind":             "tx",
    "walletFp":         <bytes, length 4>,    // routes to the wallet that must sign
    "inputs":           [ <ProposalInput>, ... ],   // non-empty
    "outputs":          [ <ProposalOutput>, ... ],  // non-empty
    "changeIndex":      <uint>,               // index into outputs[] of the change output
    "changeDerivation": [ <uint>, <uint> ],   // [branch, index] for change re-derivation
    "feeRate":          <uint>,               // sats per 1000 bytes (advisory)
    "locktime":         <uint>,               // optional; default 0
    "headerAnchors":    { <uint-as-string>: <bytes, length 32>, ... }  // height → merkle root (raw byte order)
}
```

### 4.1 `ProposalInput`

```
{
    "txid":       <text string, 64 lowercase hex chars>,
    "vout":       <uint>,
    "sats":       <uint>,           // the claimed satoshi value at vout
    "beef":       <bytes>,           // BRC-62 BEEF carrying the prior tx + BRC-74 BUMP path
    "derivation": [ <uint>, <uint> ] // [branch, index] for the input's signing key
}
```

`beef` byte serialization is defined in [`spv.md`](spv.md). The
embedded BRC-74 BUMP path is the only Merkle proof carried in v2 —
the v1 standalone `merklePath` field was redundant and was removed.

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

In v2, every `script` MUST be a P2PKH locking script (see
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

A v2 proposal MUST contain at least one change output. The reference
companion folds change below the 546-sat dust threshold into the
miner fee, but as long as the proposal carries an explicit change
output the signer will accept it. A future protocol revision may
introduce an explicit no-change marker; until then, build with
change.

### 4.4 `headerAnchors`

`headerAnchors` is a CBOR map of `block_height` (encoded as a
decimal-string key) → 32-byte raw-byte-order Merkle root. The map
MUST contain exactly one entry per **unique** block height
referenced by an input's BUMP path inside `beef`. The signer
verifies that for every input:

`merklePath.computeRoot(input.txid)` == displayed-hex form of
`headerAnchors[merklePath.blockHeight]`

The signer takes the entries on faith from the companion (and, by
extension, the block-explorer source the companion talked to). See
[`spv.md`](spv.md) §1 for the trust-model rationale and what kind
of attacks this verification does and does not defend against.

A v2 signer MUST reject a proposal whose `headerAnchors` map is
empty, omits a height referenced by any input's BUMP, or contains
a value that is not exactly 32 bytes long.

The signer's user-facing summary SHOULD render each input's
confirmation height and a short prefix of the anchored Merkle root
before prompting to sign, so the human operator can sanity-check
the path the companion took to obtain it.

## 5. `signed_tx` (`kind = "signed"`)

Direction: **signer → companion**. Returned after a successful sign.

```
{
    "v":          2,
    "kind":       "signed",
    "walletFp":   <bytes, length 4>,    // MUST equal the proposal's walletFp
    "atomicBeef": <bytes>               // BRC-95 Atomic BEEF for the new tx
}
```

The `atomicBeef` payload follows BRC-95 (Atomic BEEF):

- a 4-byte magic `01 01 01 01` identifying Atomic BEEF,
- a 32-byte little-endian *subject* TXID,
- a regular BRC-62 BEEF blob whose final transaction is the subject
  TX itself, with input proofs/parents resolved per BRC-62.

The signer constructs the Atomic BEEF from the just-signed tx plus
the BEEF blobs it already verified for each input, so the resulting
envelope is fully self-describing for any downstream broadcaster or
recipient.

A companion broadcasting this transaction SHOULD verify, before
calling its broadcast endpoint:

1. `walletFp` equals the wallet it expected to sign.
2. The Atomic BEEF magic + TXID parse cleanly, and the embedded
   subject TX matches the headline TXID. If the broadcaster echoes
   back a different txid than the Atomic BEEF declares, treat that
   as a malleability red flag and warn the user — the reference
   companion does this.

## 6. Worked example

`tests/fixtures/proposal_01.cbor` is a canonical v2
`unsigned_proposal` envelope for the BIP39 mnemonic in
[`derivation.md`](derivation.md) §6. The companion metadata file
`tests/fixtures/proposal_01.json` reports the addresses, amounts,
and anchored block height involved; the embedded BUMP inside each
input's `beef` is what the verifier actually checks against the
anchored merkle root.

`tests/fixtures/proposal_01_decoded.json` (generated by
`scripts/dump_decoded_envelope.py`) lists every CBOR field, its
type, length, and either its scalar value or a hex-encoded sample
of the first/last bytes of binary fields, including the
`headerAnchors` map. Use it as a structural reference when
implementing a decoder. See [`conformance.md`](conformance.md) for
details.
