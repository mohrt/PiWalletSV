# BRC alignment

PiWalletSV is an **air-gapped, cold-storage BSV signer**. It is
deliberately *not* a hot wallet, and it is *not* a BRC-100 wallet —
the BRC-100 surface assumes a single online process that mediates
DApp ↔ wallet RPC over JSON, signs in real time, and manages
permissions per origin. Cold-storage signers fit that model badly.

That said, BRC-100 itself is built on a stack of lower-level BSV
specifications, several of which are exactly the right primitives
for an offline signer to commit to. Adopting those keeps PiWalletSV
interoperable with the broader BSV ecosystem (BEEF tooling, ARC
brokers, Atomic-BEEF-aware indexers, future BRC-100 hot wallets that
might want to delegate cold signing to a paired Pi) without dragging
in the parts of BRC-100 that don't fit the hardware.

This document records which BRCs PiWalletSV explicitly aligns with,
which ones it explicitly does not, and why.

## At a glance

| BRC | Title | Status in PiWalletSV |
|-----|-------|----------------------|
| [BRC-1](https://bsv.brc.dev/transactions/0001) | Transaction creation | Used implicitly via `bsv-sdk` |
| [BRC-2](https://bsv.brc.dev/key-derivation/0002) | Encryption / decryption | Vault uses scrypt + AES-256-GCM (similar primitives, different scope; see [`security.md`](security.md)) |
| [BRC-42 (BKDS)](https://bsv.brc.dev/key-derivation/0042) | BSV Key Derivation Scheme (per-counterparty ECDH keys) | **Not used.** PiWalletSV is a cold-storage savings wallet, not a counterparty-driven payment surface. We use BIP32 / BIP39 / BIP44 with `m/44'/236'/0'` so the seed is portable to any BSV restoration tool. See [`protocol/derivation.md`](protocol/derivation.md). |
| [BRC-43](https://bsv.brc.dev/key-derivation/0043) | Standardized BKDS protocol IDs | **Not used** for the same reason as BRC-42. |
| [BRC-58](https://bsv.brc.dev/transactions/0058) | Merkle-path standalone binary form | Implicitly used inside BEEF. The previously-redundant per-input `merklePath` field on `unsigned_proposal` was dropped in envelope v2; the BEEF (BRC-62) carries the same bytes once. |
| [BRC-62](https://bsv.brc.dev/transactions/0062) | **BEEF (Background Evaluation Extended Format)** | **Required.** Every input in an `unsigned_proposal` carries a BRC-62 BEEF blob; the Pi parses it via `bsv-sdk`'s `Transaction.from_beef`. |
| [BRC-67](https://bsv.brc.dev/transactions/0067) | **Simplified Payment Verification rules** | **Required.** The Pi enforces BRC-67 SPV on every input before signing: BEEF parse → ancestor TXID match → BUMP-derived Merkle root must match a header that the Pi has independently PoW-validated from a baked-in checkpoint. See [`protocol/spv.md`](protocol/spv.md). |
| [BRC-74](https://bsv.brc.dev/transactions/0074) | **BUMP — Merkle paths in BEEF** | **Required** transitively via BRC-62. |
| [BRC-95](https://bsv.brc.dev/transactions/0095) | **Atomic BEEF (single-tx BEEF)** | **Required** as the wire form of `signed_tx` envelopes. The Pi emits BRC-95 (4-byte magic `0x01010101` + 32-byte subject TXID + regular BRC-62 BEEF body); the companion decodes via `Transaction.fromAtomicBEEF` from `@bsv/sdk` (or the equivalent helpers in `companion/src/lib/envelope.ts` / `piwallet/core/atomic_beef.py`). |
| [BRC-100](https://bsv.brc.dev/wallet/0100) | Unified wallet-to-application interface | **Not implemented.** See "Why not BRC-100?" below. |

## Why not BRC-100?

BRC-100 is the right answer for **online wallets that DApps talk to in
real time**. Its API surface (`createAction`, `signAction`,
`getPublicKey`, `encrypt`, `decrypt`, `getNetwork`, …) assumes:

1. A single long-lived process that DApps can RPC into per request.
2. Per-origin permission gating with a UI that prompts the user
   per-DApp-per-action.
3. Live access to the BSV network for fee estimation, broadcasting,
   header lookups, and identity certificate issuance.
4. **BKDS (BRC-42) key derivation** — explicitly forbids BIP32 — so
   that every counterparty gets a unique key path derived from a
   shared ECDH secret.

A cold-storage signer doesn't have any of those. The Pi is offline,
talks only to a paired companion over a QR transport with seconds-of-
latency, derives keys from a backed-up BIP39 seed (which the user
presumably also has on paper), and does not maintain any per-origin
permission state because it has no concept of an origin.

Trying to retrofit BRC-100 on top would require either (a) running
the full BRC-100 RPC surface inside the companion and reducing the Pi
to a privileged-mode signer for it, or (b) inventing a delayed,
batched, queued analogue of BRC-100 over multipart QR. Neither is
useful enough to justify the spec compliance cost: the hot-wallet
ecosystem already has good BRC-100 implementations, and PiWalletSV
solves a different problem (cold-storage of a savings stack).

## What "alignment" means in practice

PiWalletSV's wire formats and verification rules are designed so that:

1. **A BRC-100 hot wallet can pair with PiWalletSV as its offline
   privileged-mode signer** without bridging code, by speaking BEEF
   (BRC-62), Atomic BEEF (BRC-95), and BUMP (BRC-74) across the QR
   gap. The Pi will verify the proposal's SPV claims (BRC-67) and
   return a BRC-95 Atomic BEEF the hot wallet can broadcast as-is.
2. **Any BEEF-aware indexer or broadcaster (ARC, ProvenChain,
   WhatsOnChain) accepts the Pi's `signed_tx` output verbatim**
   because it is a vanilla BRC-62 BEEF wrapped in a BRC-95 atomic
   header.
3. **The companion implements BRC-67 SPV on the receive side too**
   so the wallet's *displayed balance* is also a chain of headers a
   user has accepted, not just a chain of headers WhatsOnChain has
   asserted. Receive-side SPV ships in Phase 3 of the SPV alignment
   plan.

## Out-of-scope BRCs

The following BRCs are intentionally not pursued today because they
either presume an online context (the hot-wallet half of BRC-100) or
gate behaviour PiWalletSV doesn't need:

- BRC-42 / BRC-43 (BKDS counterparty derivation).
- BRC-46 / BRC-50 / BRC-52 / BRC-53 (DPP, output baskets, certificates,
  privileged mode UX) — these are part of BRC-100's interactive
  surface; without that surface they have nothing to attach to here.
- BRC-87 (BSV-RPC over WebSocket) — irrelevant for an air-gapped
  device with no IP networking.

If your project needs PiWalletSV to participate in any of those, the
right architecture today is to keep BRC-100 in the companion and let
the Pi handle the SPV-verified signing step over QR; the companion
already has all the data it needs to broker the BRC-100 RPC surface
itself.

## Versioning of this commitment

This document tracks the *current* alignment of PiWalletSV. As we
move through the SPV-alignment plan and add receive-side SPV, the
table above will tighten (the BRC-67 row in particular goes from
"send-side only" to "send + receive"), but no row will ever loosen
without a corresponding envelope-version bump and a deprecation
window.

When we say "Required" above, it is required at the **current** wire
version (envelope `v=2`, QR magic `PW1`). Earlier on-disk envelopes
(v=1, pre-Atomic-BEEF) are intentionally not accepted by the
reference implementations; this is documented in
[`protocol/envelopes.md`](protocol/envelopes.md).

## References

- [BSV BRCs index](https://bsv.brc.dev/) — canonical hub.
- [`protocol/spv.md`](protocol/spv.md) — what the Pi checks before
  signing, in concrete terms.
- [`protocol/envelopes.md`](protocol/envelopes.md) — wire schemas
  including the BRC-95 `signed_tx` payload.
- [`protocol/derivation.md`](protocol/derivation.md) — why we use
  BIP44 instead of BKDS.
