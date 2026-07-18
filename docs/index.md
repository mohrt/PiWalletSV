---
hide:
  - navigation
  - toc
---

<div class="pwsv-hero" markdown>

![PiWalletSV](assets/logo.png){ .pwsv-hero-logo }

<div class="pwsv-hero-copy" markdown>

# An air-gapped wallet for Bitcoin SV

Built on a Raspberry Pi with a screen and camera. Your **keys never leave
the device** — no Wi-Fi, no Bluetooth, no Ethernet. A small web app on your
phone or laptop talks to the chain; the Pi just signs.

[Launch wallet ↗]({{ companion_url }}/){ .pwsv-cta }
[Purchase](purchase/shop.md){ .pwsv-cta-secondary }
[Read the docs](getting-started.md){ .pwsv-cta-secondary }

</div>
</div>

<div class="pwsv-photo-strip" markdown="0">
  <img src="assets/home/device-home.png" alt="PiWalletSV device showing the home screen" width="360" height="270" loading="lazy">
  <img src="assets/home/device-maintenance.png" alt="PiWalletSV maintenance menu on the device" width="360" height="270" loading="lazy">
  <img src="assets/home/device-qr.png" alt="PiWalletSV displaying a QR code for air-gap transfer" width="360" height="270" loading="lazy">
  <img src="assets/home/companion-wallets.png" alt="PiWalletSV companion app wallet list" width="336" height="680" loading="lazy">
</div>

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

-   :material-usb: __USB vault backup__

    Export and restore the encrypted vault to a FAT32/exFAT stick from
    **Settings → Maintenance → USB backup** — included on images built with
    `deploy/provision-pi.sh`. See
    [User manual § USB backup](user-manual.md#usb-backup).

-   :material-shopping-outline: __Off-the-shelf parts__

    Raspberry Pi, display, camera — no proprietary hardware, no soldering,
    no signed firmware to trust.

</div>

## Get started

<div class="grid cards" markdown>

-   :material-sd: __[Build from image](download.md)__

    The fastest path. Download the signed firmware image, flash it to
    a microSD, and boot. Follow the [flash and first-run guide](build-image.md).

-   :material-source-branch: __[Build from scratch](getting-started.md)__

    Clone the repo, provision a Pi, and run the companion in a browser.
    Start here if you want to inspect, modify, or contribute to the code.

-   :material-shopping-outline: __[Shop](purchase/shop.md)__ ·
    [Ways to get hardware](purchase/hardware.md)

    Full kit or case-only — pay with card or BSV. Limited batches.

-   :material-play-circle-outline: __[Tutorials](tutorials.md)__

    Video walkthroughs: assembly, setup, wallet, send/receive.

</div>

## Help & support

--8<-- "docs/includes/support-contact.md"