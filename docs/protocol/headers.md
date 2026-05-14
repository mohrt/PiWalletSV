# Block headers and SPV anchoring — v2

This document specifies the block-header chain that travels in every
`unsigned_proposal` envelope, the proof-of-work checks the signer
applies to it, and the firmware checkpoint values it is anchored
against. It is the v2 replacement for the legacy `headerAnchors` map
described in earlier revisions of [`envelopes.md`](envelopes.md).

The rules here are mandatory for v2 conformance. They implement the
parts of [BRC-67](https://bsv.brc.dev/transactions/0067) (Simplified
Payment Verification) the air-gapped signer needs to *trust* a chain
state without its own network access.

## 1. Why the schema changed

v1 carried `headerAnchors`: a `height → 32-byte Merkle root` map the
companion supplied directly. The signer trusted those roots verbatim
and used them to verify each input's Merkle path. The trust gap is
obvious in retrospect — a malicious companion (or compromised
infrastructure between the companion and a block-explorer endpoint)
could fabricate (`height`, `root`) pairs the signer would happily
accept.

v2 closes that gap by replacing the trusted map with a raw
**header chain** the signer independently validates with proof-of-
work. The companion no longer asserts roots; it forwards the raw
80-byte block headers, and the signer derives the per-height roots
from headers it has independently checked.

```
v1 (trusted):    Companion ----headerAnchors[height -> root]----> Signer
                                                                  └── trusts
v2 (verified):   Companion ----checkpointHeight + headers[]------> Signer
                                                                  └── PoW + linkage
                                                                  └── derives roots locally
```

## 2. Wire format

The `unsigned_proposal` envelope carries two new fields in v2 (see
[`envelopes.md`](envelopes.md) §4 for the full schema):

| Field              | CBOR type    | Value                                                        |
| ------------------ | ------------ | ------------------------------------------------------------ |
| `checkpointHeight` | uint         | Height of the firmware checkpoint the chain links back to.  |
| `headers`          | array of `bytes` | Each entry is exactly 80 bytes; the standard Bitcoin / BSV block-header serialization. |

The first entry in `headers` is at height `checkpointHeight + 1`,
the last is at height `checkpointHeight + headers.length`. Heights
are dense: the signer rejects any gap.

### 2.1 80-byte header layout

Each entry in `headers` MUST be the exact 80-byte serialization
that goes on the wire between full nodes. Field offsets:

| Offset | Length | Field         | Encoding                                          |
| ------ | ------ | ------------- | ------------------------------------------------- |
| 0      | 4      | `version`     | uint32 little-endian                              |
| 4      | 32     | `prev_hash`   | double-SHA256 of predecessor's 80 bytes, **raw byte order** (not the displayed-hex byte-reverse) |
| 36     | 32     | `merkle_root` | block Merkle root, **raw byte order**             |
| 68     | 4      | `time`        | uint32 little-endian                              |
| 72     | 4      | `bits`        | uint32 little-endian compact target               |
| 76     | 4      | `nonce`       | uint32 little-endian                              |

A header in any other shape (e.g. JSON, displayed-hex byte order)
is non-conformant. The signer MUST refuse to decode any entry whose
length is not exactly 80 bytes.

## 3. Per-header validation

For each entry `h[i]` (0-indexed inside `headers`) at height
`checkpointHeight + 1 + i`, the signer MUST enforce:

1. **Structure.** `len(h[i]) == 80` and the field decodes as
   described in §2.1.
2. **Linkage.** `h[i].prev_hash == double_sha256(h[i-1])` for `i > 0`,
   and `h[0].prev_hash == checkpoint.hash` for the first entry.
3. **Self-consistent PoW.** `double_sha256(h[i])` interpreted as a
   little-endian uint256 is `<=` the difficulty target encoded by
   `h[i].bits`. The signer MUST refuse a header whose bits field has
   the sign bit (`0x00800000`) set.

The signer DOES NOT check that `bits` is the *correct* difficulty
for height `checkpointHeight + 1 + i`. Implementing the BSV
difficulty-adjustment algorithm on the device would require
tracking a much wider window of consensus state, and offers little
extra security against the only attacker we model here (a
malicious companion). What we do enforce per header is sufficient
for SPV-from-checkpoint: a chain of self-consistent low-difficulty
headers cannot forge real proofs of inclusion for a real on-chain
transaction, because the BUMP it would need to anchor would have
to root in a real block's Merkle tree, which would not be present
in a forged chain.

## 4. Confirmation-depth requirement

The signer MUST refuse to anchor any input whose proof targets a
block at height `H` if `H + MIN_CONFIRMATION_DEPTH - 1` is past the
chain tip the proposal ships. The reference implementation defines:

```
MIN_CONFIRMATION_DEPTH = 6
```

Equivalently: every input's funding tx MUST be at least 6 blocks
deep in the chain the proposal carries. A 5-confirmation reorg has
historically been the cap of practical concern on BSV (and Bitcoin
before the split); 6 is the conventional buffer.

The companion-side proposal builder MUST therefore extend the
chain it ships at least `MIN_CONFIRMATION_DEPTH - 1` blocks past
the deepest input height, or the signer will reject the proposal.

This requirement is not negotiable in v2; a future revision MAY make
the depth user-configurable, but at present it is hard-coded.

## 5. Firmware checkpoints

A **firmware checkpoint** is the absolute trust anchor for the
verification machinery: the signer trusts that the checkpoint's
hash, height, and 80-byte raw header bytes correspond to a real,
canonical block on the active chain. Every header in `headers`
must descend from this anchor.

The reference implementation ships two anchors per network in
[`piwallet/core/checkpoints.py`](../../piwallet/core/checkpoints.py)
and the companion mirrors them in
[`companion/src/lib/headers.ts`](../../companion/src/lib/headers.ts):

| Constant            | Network | Height | Notes                                                         |
| ------------------- | ------- | ------ | ------------------------------------------------------------- |
| `MAINNET_GENESIS`   | main    | 0      | Bitcoin / BSV genesis. Public-domain since 2009.              |
| `MAINNET_RECENT`    | main    | varies | Production builds rotate this to a recent block (~4 weeks deep). |
| `TESTNET_GENESIS`   | test    | 0      | Bitcoin / BSV testnet3 genesis. Public-domain since 2011.     |
| `TESTNET_RECENT`    | test    | varies | Production builds rotate this to a recent testnet block.      |

`*_RECENT` defaults to the genesis duplicate when this repository's
`HEAD` ships unrotated; production firmware builds MUST rotate to
a real recent height before deploying, otherwise the per-proposal
header payload becomes intractable (mainnet at ~870 000 blocks ≈
70 MB of headers to ship every time).

### 5.1 Checkpoint update procedure

Rotating `*_RECENT` requires both a Pi firmware change *and* a
matching companion change in the same release; if they drift, the
companion will ship chains that don't link to the Pi's anchor and
every proposal will fail. The procedure:

1. Pick a block at least 4 weeks deep on the target network. Any
   BSV explorer with a full archive is fine; the WoC endpoint
   `GET /block/{hashOrHeight}/header` returns the JSON form a
   developer can hand-check.
2. Sanity-check the height + hash against at least two independent
   sources. The point of baking these values in is that we never
   need to trust a single block-explorer mirror; a rotation that
   happens to take place when a mirror is compromised would
   propagate the compromise into firmware.
3. Update the matching constant in
   `piwallet/core/checkpoints.py` (Pi) **and**
   `companion/src/lib/headers.ts` (companion) with the new
   `(height, hash, raw_header_hex)` triple plus a short `source:`
   annotation noting which sources you cross-checked against.
4. Run `pytest tests/test_checkpoints.py` (Pi) and
   `vitest tests/headers.test.ts` (companion). Both suites
   recompute the hash from the raw header bytes and refuse to run
   if the values disagree, so an accidental copy-paste error is
   caught locally.
5. Bump the firmware version and note the rotation in the release
   notes. Operators upgrading from a stale build will see the
   per-proposal chain length drop back to its usual size; that
   visible change is the user-facing tell that the trust anchor
   has moved.

## 6. Threat model

The header chain check is designed to defeat the following attacks
that the v1 `headerAnchors` model could not:

| Attack                                                           | Defeated by                              |
| ---------------------------------------------------------------- | ---------------------------------------- |
| Companion forges `(height, root)` anchors for non-existent blocks. | PoW + linkage check against checkpoint.  |
| Companion replays an old (unfunded-now) header to inflate UTXO age. | Linkage from checkpoint forces a single, contiguous tip. |
| Companion injects a low-difficulty fork that descends from genesis. | Per-header PoW + checkpoint-pinned start. |
| Companion ships a testnet chain to a mainnet wallet (or vice versa). | Checkpoint is network-pinned; testnet headers do not link to the mainnet anchor. |
| Companion ships a chain that only reaches block `H-3` for an input at height `H`. | `MIN_CONFIRMATION_DEPTH = 6` enforced per input. |

The chain check does **not** defeat:

- A user who confirms a transaction without reading the bonnet
  screen. The chain check protects the *amount* and *destination*
  fields the user reviews; if those are deliberately ignored,
  cryptographic checks are powerless.
- A multi-week chain reorg deeper than `MIN_CONFIRMATION_DEPTH`.
  No SPV implementation can. BSV reorgs of that depth would be a
  network-wide consensus event, not a wallet concern.
- An attacker who has been able to rotate `*_RECENT` to a chain
  they control. Defending against that requires the user (or a
  second reviewer) to cross-check the baked-in checkpoint values
  against at least two independent sources before flashing the
  firmware. The rotation procedure in §5.1 enforces the discipline
  on the maintainer side; an operator who installs an unsigned or
  unverified firmware build is on their own.

## 7. Companion-side validation

The companion runs the same per-header PoW + linkage checks
client-side before shipping the proposal. This is purely defensive
— the Pi will run them again — but it serves two practical goals:

1. **Earlier failure surface.** A misbehaving WoC mirror that hands
   the companion a junk header is caught before the proposal ever
   reaches the Pi, so the operator sees a meaningful error in the
   companion UI rather than a generic "Pi rejected the proposal"
   message after the QR roundtrip.
2. **Receive-side SPV.** The same machinery validates Merkle proofs
   for every UTXO in the wallet's confirmed-balance figure. An
   unverified UTXO is excluded from the trusted total and surfaced
   with an "SPV ✗" badge in the UI.

The companion caches validated headers in IndexedDB
(`piwallet-companion-headers`) so a warm cache amortizes the
per-proposal cost across refreshes. The cache is keyed by
`(network, height)`; its trust depends on the firmware checkpoint
that was active when each row was inserted, so the cache is
unconditionally cleared whenever the operator upgrades to a build
with a different checkpoint hash.

## 8. Worked example

The fixture at
[`tests/fixtures/proposal_01.cbor`](../../tests/fixtures/proposal_01.cbor)
is a canonical v2 `unsigned_proposal` envelope. After CBOR + gzip
decoding, its `headers` array carries a synthetic PoW-valid chain
starting at `checkpointHeight + 1`. The matching
`tests/fixtures/proposal_01_decoded.json` shows every header's
`bytes` length (80) plus its position in the chain.

The fixture is not anchored to a real BSV block — it is generated
by `tests/fixtures/generate_fixtures.py` with the easy-target
`bits = 0x207fffff` so the chain self-consistently passes PoW.
This keeps the test suite hermetic. Production proposals are
anchored to the active firmware checkpoint and ship real BSV
mainnet (or testnet) headers.
