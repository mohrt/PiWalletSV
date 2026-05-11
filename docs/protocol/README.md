# PiWalletSV companion-interop protocol — v1

This directory is the **canonical specification** for the wire formats,
QR transport, key derivation, and SPV requirements that connect a
PiWalletSV signer to a companion application.

Anyone is free to build a companion (mobile app, desktop wallet,
browser extension, terminal tool — anything) that pairs with a
PiWalletSV signer by following the rules in this directory. The
reference implementation lives in this repository (`piwallet/` on the
Pi side, `companion/` on the browser PWA side) and serves as the
correctness oracle when this text is ambiguous.

The opposite direction (third-party signer paired with the PiWalletSV
companion) is also covered, although the PiWalletSV companion is
opinionated about defaults — see [`spv.md`](spv.md) §5 for what it
expects from a signer.

## Audience

You are reading this if you want to:

- Decode the QR codes the PiWalletSV signer or companion paints on
  screen.
- Encode QR codes that the PiWalletSV signer will accept.
- Re-implement the PiWalletSV signer in different hardware or
  software.
- Verify that a paired companion isn't trying to talk to the signer
  in an unsupported way.

You are **not** reading this if you only want to use PiWalletSV — that
audience belongs in [`../user-manual.md`](../user-manual.md) (coming).

## Scope of v1

Everything in this directory is **protocol version 1**. The current
envelope `v` field is `1` and the multipart QR magic is `PW1`. When a
breaking change is needed:

- The CBOR envelope's `v` integer is incremented and old versions are
  rejected on receive.
- The QR magic becomes `PW2`, etc., and assemblers refuse mixed
  streams.

A signer SHOULD refuse any envelope or QR stream whose version it does
not implement, and surface a clear error to the user.

## Files

1. [`envelopes.md`](envelopes.md) — CBOR + gzip payload shapes for the
   three message kinds: `xpub_export`, `unsigned_proposal`,
   `signed_tx`. Includes byte-order rules, canonical encoding
   requirements, and field-by-field types.
2. [`qr-transport.md`](qr-transport.md) — the `PW1` multipart QR
   framing: line grammar, base64url alphabet, chunk sizing, assembler
   rules.
3. [`derivation.md`](derivation.md) — BIP39 mnemonics, BIP32 + BIP44
   account derivation at `m/44'/236'/0'`, P2PKH address encoding
   (BSV mainnet), receive / change branches, the 4-byte **self**
   fingerprint used to route envelopes.
4. [`spv.md`](spv.md) — what the signer verifies before producing
   signatures: BEEF parse, MerklePath ↔ header-anchor cross-check,
   prevout script ↔ derivation match, change re-derivation,
   conservation of value, fee-rate cap.
5. [`conformance.md`](conformance.md) — canonical test vectors:
   `addresses_canonical.json`, `proposal_01.cbor`,
   `proposal_01.json`, and a field-by-field decoded form
   (`proposal_01_decoded.json`) that an implementation can diff
   against.

## Design tenets

These are the rules the reference implementation follows; they explain
the "why" behind decisions that the per-file specs only state.

1. **The signer is the trust anchor.** The companion is online but
   semi-trusted. Every claim the companion makes (which UTXOs you
   have, how much each is worth, which address is change) is
   cryptographically re-verified on the signer using `BEEF` proofs
   anchored to user-displayed block headers. A malicious companion
   cannot exfiltrate keys or trick the signer into producing a
   signature on a transaction that pays the wrong place.
2. **No private material ever crosses the QR boundary.** Only public
   xpubs, unsigned proposals, and signed (already-public) transactions
   travel between the two halves.
3. **Plain bytes, not opaque envelopes.** Every wire field is a
   primitive (int, string, bytes, array, map). No tagging, no custom
   CBOR tags, no proprietary serialization. Anyone with a CBOR
   library and a gzip implementation can decode our payloads.
4. **Short keys, gzipped CBOR.** PW1 multipart QR has bounded
   per-frame capacity, so envelope key names are short and the
   payload is compressed before framing.
5. **No mutable shared state.** Each envelope is self-contained;
   nothing is implicit or carried over between QR sessions.

## Stability promise

Protocol version 1 is **stable** in the sense that:

- The bytes a v1 signer emits today MUST still parse identically on
  every v1 implementation forever.
- Optional fields that may be added in v1 (such as a `meta` map for
  future extensions) MUST be additive — a v1 decoder that ignores
  unknown keys SHOULD still succeed if the required v1 keys are
  present and well-typed.

If we ever need a breaking change, we'll cut v2 in a clearly-named
sibling directory (`docs/protocol/v2/`) and run the two protocols
side-by-side for a deprecation window.

## Where to start

If you're new to the protocol, read in order:

1. [`derivation.md`](derivation.md) (shortest, sets the wallet model).
2. [`envelopes.md`](envelopes.md) (the actual wire payloads).
3. [`qr-transport.md`](qr-transport.md) (how to push envelope bytes
   across the air gap).
4. [`spv.md`](spv.md) (what a signer must verify; informs what your
   companion must include).
5. [`conformance.md`](conformance.md) (run your decoder against the
   golden fixtures before shipping).
