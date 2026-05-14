# Prior art

PiWalletSV is not the first project to implement an air-gapped
Bitcoin SV signing flow, and a lot of the design choices here only
make sense in contrast to what came before. This chapter collects
*comparative* notes against existing approaches: where the trust
model is identical, where PiWalletSV trades complexity for stricter
verification, and what the prior art usefully prompts us to add to
the backlog.

This is not a competitive landscape document. It's design context.

## ElectrumSV-based air-gapped wallet

In May 2026 Craig Wright published
[Cold Authority: Constructing an Air-Gapped Bitcoin SV Wallet Using
ElectrumSV][cold-authority], a clean, principled walkthrough of an
air-gapped setup that uses two laptops, USB transfer, and ElectrumSV
in offline mode. The framing is striking because it is almost a
textbook description of the *same* threat model PiWalletSV is built
around — but stops where PiWalletSV starts.

### Where PiWalletSV and the article fully agree

The article's core thesis maps onto our architecture without a
single change:

| "Cold Authority"                                                                                                     | PiWalletSV equivalent                                                                                              |
| -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| "Two-System Model: offline never connects, online never holds keys."                                                 | Pi (signer) ↔ companion (PWA). See [Architecture §1](architecture.md#1-two-hosts-one-wallet).                      |
| "Unidirectional trust boundary; only signed data crosses."                                                           | Three envelope kinds — `xpub_export`, `unsigned_proposal`, `signed_tx` — and nothing else.                         |
| "Online machine creates unsigned tx, offline signs, online broadcasts."                                              | The exact data flow in [Architecture §3](architecture.md#3-the-data-flow-walked-through).                          |
| "Watch-only via xpub on the online side."                                                                            | `xpub_export` envelope; companion stores xpub + fingerprint only.                                                  |
| "Defends against remote compromise / supply-chain / network surveillance; does NOT defend against physical compromise or user error." | Verbatim the threat model in [Security](security.md) and [SPV §8](protocol/spv.md#8-threat-model-summary).         |
| "Verify before signing — never blindly."                                                                             | Our entire `verify_proposal()` flow + on-bonnet hold-A confirmation.                                               |

So the *philosophy* is identical. We're not inventing a new model;
we're implementing a well-understood one.

### Where PiWalletSV materially improves on the article's approach

The article is honest about its weak points, and they happen to be
exactly the things this project hardens.

#### 1. USB → camera-only QR transport

The article: "USB devices are the only bridge between systems… This
is the weak point in most setups." A commenter explicitly suggests
QR codes to mitigate this.

PiWalletSV: there is no USB port in the trust path. The Pi receives
proposals via Camera Module 3 + PW1 multipart QR
([QR transport](protocol/qr-transport.md)) and emits signed
envelopes the same way. This eliminates the entire BadUSB / autorun
/ executable-on-removable-media class of attacks the article ducks
rather than solves.

#### 2. "Verify manually before signing" → cryptographic verification

The article relies on the user reading inputs/outputs/amounts off
ElectrumSV's screen. That is necessary but not sufficient — a
compromised online host can show one tx to the screen and submit a
different one (the classic "what you see is not what you sign"
problem ElectrumSV's offline mode does not fully solve, because PSBT
rounds don't include independent SPV proofs).

PiWalletSV: the signer doesn't trust the companion's claims about
anything.

- BRC-62 BEEF carries the prior funding tx; the Pi re-extracts the
  value at `vout`.
- BRC-74 BUMP path inside that BEEF is recomputed against a Merkle
  root the Pi pulls from a header chain it just **PoW-validated
  on-device** from a firmware-pinned checkpoint
  ([Header chains](protocol/headers.md)).
- 6-confirmation depth is enforced in `piwallet/core/verify.py`.
- The change output's script is **re-derived** from the wallet's own
  xpub on the Pi; if the bytes don't match, it aborts.

The user still has to read the bonnet, but the human is the *last*
check, not the only check. ElectrumSV's air-gapped flow makes the
human the *first and only* check.

#### 3. Purpose-built device → smaller TCB

The article allows "a freshly installed machine" — a laptop with
disabled radios. That's still a Linux/Windows/macOS install with
USB stack, video subsystem, audio, Bluetooth firmware, etc. —
millions of lines of attack surface, all latent.

PiWalletSV runs on a Pi with a minimal image, no Wi-Fi or Bluetooth
activated in the offline build, and a single Click CLI as the
surface area. The disclaimer-gated bonnet UI
([Architecture §7](architecture.md#7-first-load-disclaimer)) is the
only program a normal user ever sees. The TCB is dramatically
smaller and reproducible.

#### 4. ElectrumSV PSBT round → BRC-aligned envelopes

ElectrumSV's offline workflow is, in practice, "export a partially-
signed transaction, sign it, import it." It works, but the wire
format is informal and there is no SPV in the loop. PiWalletSV's v2
envelope is explicitly aligned with BRC-62, BRC-67, BRC-74, and
BRC-95 ([BRC alignment](brc-alignment.md)) — the standardised SPV
stack.

#### 5. Receive-side SPV

The article does not discuss it because ElectrumSV trusts the
ElectrumX server it connects to. PiWalletSV ships
`companion/src/lib/spv.ts` so that even the companion (the
"untrusted" half) re-validates every UTXO's Merkle proof against a
PoW-checked chain before it shows the user a balance. The
watch-only side is no longer "trust the explorer" either — it is
SPV-verified.

### Items from the comments worth taking seriously

The discussion thread under the article surfaces two items that
deserve a slot in our backlog:

!!! tip "Backlog candidates"

    - **Watch-host privacy.** A commenter notes that ElectrumSV →
      ElectrumX leaks every address to the server operator.
      PiWalletSV has the same leak: companion → WhatsOnChain.
      Mitigations would be (a) a self-host story for the companion's
      `WocClient` against a user-run node + indexer, (b) optional
      address-set obfuscation (random gap-fills, batched lookups),
      or (c) an HTTP proxy / Tor mode. Right now this is mentioned
      only in passing in [Security](security.md); it could deserve
      its own doc.
    - **Multisig + decoy / duress wallet.** Multisig is a substantial
      scope expansion (envelope kinds, PSBT-style rounds,
      key-fragment ceremonies) but matches our architecture well —
      the signer set just becomes "N Pi devices, each does the same
      `verify_proposal` then partial-sign." A "duress wallet"
      (separate xprv, low balance, distinct PIN) is a much smaller
      change: the vault already supports multiple wallets; we'd just
      need a "duress mode" PIN that unlocks a designated wallet
      only.

### Bottom line

The article is essentially a manifesto for the same trust model
PiWalletSV embodies, written for a tool (ElectrumSV) that implements
only the *minimum viable* version of that model. We are building the
*strict, hardware-pinned, BRC-aligned* version of the same idea. If
a reader walks away from the article convinced of the architecture,
the PiWalletSV pitch is roughly:

> Yes, exactly that — but with a Pi instead of a laptop, QR instead
> of USB, and on-device SPV instead of trust-the-screen.

The article's weakest section ("Verification Before Signing → verify
manually") is precisely the gap [SPV requirements §1](protocol/spv.md#1-the-verify-then-sign-rule)
closes.

[cold-authority]: https://singulargrit.substack.com/p/cold-authority-constructing-an-air
