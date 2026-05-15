---
hide:
  - navigation
  - toc
---

<div class="pwsv-hero" markdown>

![PiWalletSV](assets/logo.png){ .pwsv-hero-logo }

<div class="pwsv-hero-copy" markdown>

# An air-gapped wallet for Bitcoin SV

Built on a Raspberry Pi, a TFT bonnet, and a Pi Camera. Your **seed
phrase never touches a network**. A small web app on your phone or
laptop talks to the chain; the Pi just signs.

[Launch wallet ↗]({{ companion_url }}/){ .pwsv-cta }
[Read the docs](getting-started.md){ .pwsv-cta-secondary }

</div>
</div>

!!! warning "Alpha software"
    PiWalletSV is in active development. There is no warranty and no
    custodial backup. Read the [Disclaimer](disclaimer.md) and
    [Security briefing](security.md) before storing real funds on a
    device you built from this code.

## Why do I need this?

<div class="grid cards" markdown>

-   :material-shield-check-outline: __Stay safe when your other devices don't__

    The keys live on a Pi with **no Wi-Fi, no Bluetooth, no Ethernet**.
    Even if your laptop gets phished or your phone gets owned, the
    attacker has no path to your funds.

-   :material-account-check-outline: __Nobody can lock you out__

    No signed firmware, no proprietary hardware, no update server
    that can drop BSV, brick your device, or push a backdoor next
    quarter. You write the SD card, you read the source, you keep
    the parts.

-   :material-qrcode-scan: __Cold storage you can actually use__

    Scan a QR with the camera, confirm the recipient on the Pi's
    screen, and press a button. Your seed phrase only comes out for
    first setup or recovery — never to send a transaction.

</div>

## How it works

The system is intentionally split into two pieces that never share a
trust boundary:

```mermaid
flowchart LR
  subgraph air["Air-gapped signer (Pi)"]
    seed["BIP39 seed<br/>encrypted vault"]
    verify["verify_proposal<br/>(BEEF + Merkle + anchors)"]
    sign["sign_transaction"]
    seed --> verify --> sign
  end

  subgraph online["Online companion (web app)"]
    woc["WhatsOnChain<br/>or other backend"]
    select["UTXO + coin selection"]
    proposal["unsigned_proposal<br/>builder"]
    broadcast["broadcast"]
    woc --> select --> proposal
    broadcast --> woc
  end

  proposal -- "QR (PW1 multipart)" --> verify
  sign -- "QR (PW1 multipart)" --> broadcast
```

The Pi has no Wi-Fi, no Bluetooth, no Ethernet — nothing reaches the
network from the device that holds the keys. The companion runs in
your existing browser at
[the companion]({{ companion_url }}/) and ferries
transactions to the Pi over animated QR codes. Every input the
companion proposes is **cryptographically re-verified on the Pi**
(BEEF proofs anchored to user-displayed block headers) before the
device signs anything.

## Three reasons it's different

<div class="grid cards" markdown>

-   :material-shield-key: __Public key only on the network__

    The companion sees only your public xpub and pre-signed
    transactions. The seed phrase, the encrypted vault, and every
    signing key live exclusively on the Pi.

-   :material-source-branch: __Open spec, not a black box__

    The wire format, QR transport, derivation rules, and SPV
    requirements are documented as an open
    [protocol spec](protocol/README.md). Anyone can build a
    compatible signer or companion.

-   :material-shopping-outline: __Off-the-shelf parts__

    Raspberry Pi, TFT bonnet, Pi Camera. No proprietary hardware,
    no soldering, no signed firmware to trust.

</div>

## Want to use it?

<div class="grid cards" markdown>

-   :material-rocket-launch: __[Get started](getting-started.md)__

    Bring up the bonnet, install the signer, run the companion in a
    browser. Start here if you've just got the hardware.

-   :material-cellphone-information: __[Companion (live)]({{ companion_url }}/)__

    Open the web app in your browser. Pair a wallet, scan an unsigned
    proposal, broadcast a signed transaction. Works on any phone,
    tablet, or laptop with a camera and a modern browser.

-   :material-account-tie: __[User manual](user-manual.md)__

    Pairing, receiving, sending, broadcasting, restoring — the same
    journey a normal user takes.

-   :material-shield-key: __[Security briefing](security.md)__

    Plain-language operator-facing trust model: what's on the network,
    what isn't, and why the PIN-encrypted vault is not magic.

</div>

## Want to understand it?

<div class="grid cards" markdown>

-   :material-shape: __[Architecture](architecture.md)__

    The two-host design, the trust boundary, the data flow, and why
    everything that crosses the air gap is gzipped CBOR over animated
    QR.

-   :material-package-down: __[Build & deploy](build.md)__

    Take a blank Pi from a freshly-flashed SD card to an autostarting
    bonnet kiosk under systemd, with bounded journald logs.

-   :material-cog: __[Operate](operate.md)__

    Day-to-day ops: logs, exit codes, vault stewardship, factory
    reset, updates, and troubleshooting the deployment itself.

-   :material-console: __[CLI reference](cli.md)__

    Every `piwallet` subcommand with options, exit codes, and
    pipe-friendly examples.

-   :material-code-tags: __[Develop](develop.md)__

    Repo layout, dev setup, testing matrix, fixture regeneration,
    release checklist.

-   :material-file-document-multiple: __[Protocol spec](protocol/README.md)__

    The wire formats, QR transport, derivation rules, and SPV
    requirements that any compatible companion (or signer) must
    follow.

-   :material-history: __[Prior art](prior-art.md)__

    How PiWalletSV's design choices compare to existing air-gapped
    BSV setups, and what that comparison tells us about future scope.

-   :material-link-variant: __[BRC alignment](brc-alignment.md)__

    What of BRC-100 / BRC-95 / BRC-74 PiWalletSV implements, and what
    it deliberately doesn't.

</div>

## Project status

| Phase | Scope | Status |
| ----- | ----- | ------ |
| 1 | Offline core (mnemonic, derivation, envelope, vault, verify, sign, CLI) | done |
| 2 | Pi-side bonnet UX (display, joystick word entry, first-boot disclaimer) | in progress |
| 3 | Python + TypeScript PW1 multipart transport | done |
| 4 | Companion web app (pairing, receive, UTXO scan, proposal, broadcast, terms) | done |
| 7 | Documentation site + protocol spec + v0.1 release | this site |
| 8 | Enclosure, tamper-evidence, first-boot hardening, signed SD image | planned |
