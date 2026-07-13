# Purchase

PiWalletSV is designed as a **DIY cold-wallet stack**: download signed
firmware, flash a microSD, and assemble the Pi + bonnet + camera yourself.
That is the **default path** — especially while Raspberry Pi boards are
hard to buy.

!!! warning "Beta hardware"
    Round-one kits are **beta** pre-release hardware and software. There is
    **no warranty**. Change-of-mind returns incur a **restocking fee** (20% full kit,
    15% case). See [Returns & refunds](purchase/returns.md) and
    [Shipping](purchase/shipping.md) before ordering.

## Batch status

**Round-one beta** — limited quantity. If checkout buttons are disabled or return
an error, the batch is sold out or not yet open. Follow [@PiWalletSV on X](https://x.com/PiWalletSV)
for announcements.

## Raspberry Pi supply

Raspberry Pi boards (especially **Pi Zero / Zero W**) are in **very low
supply** right now. Memory and fab capacity are heavily pulled toward
AI and datacenter demand, so distributors often show long lead times or
empty shelves.

We do **not** currently sell **Raspberry Pi Zero 2** kits — those boards
are unobtainable at a reasonable price. Round-one kits use **Pi Zero W**.

**What that means for you:**

- **Full pre-assembled kits** are offered only in **small batches** when
  boards are available at a sane price — not as always-in-stock inventory.
- **Most buyers** should plan to **source their own Pi, bonnet, and camera**
  and flash from [Download](download.md).
- Ask [@PiWalletSV on X](https://x.com/PiWalletSV) for current kit or
  case availability before ordering.

## Three ways to get hardware

### 1. DIY (default)

Bring your own parts, flash the official image, print or buy a case.

**You need:**

| Part | Notes |
|------|--------|
| **Raspberry Pi Zero W** (or WH) | 32-bit armv6; solder header if not WH |
| **Adafruit 4506** bonnet | 240×240 TFT, joystick, A/B buttons |
| **ArduCam OV5647** + cable | Kit camera; not Camera Module 3 |
| **microSD** 8 GB+ | Blank; you flash firmware |
| **5 V power** + micro-USB cable | **Right** port = power only |
| **micro-USB OTG adapter + USB stick** | **Optional** — left port only; export/import vault during upgrades (see [User manual](user-manual.md#usb-backup)) |
| **Case** | [Print yourself](https://github.com/mohrt/PiWalletSV/blob/main/hardware/case/README.md) or buy case-only (below) |

**Steps:**

1. [Download](download.md) the signed firmware image from GitHub
2. GPG + SHA-256 verify ([Security § Release key](security.md#release-key))
3. Flash with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) —
   see [Flash and first run](build-image.md)
4. Assemble and complete first boot ([User manual](user-manual.md))

Or build from source: [Getting started](getting-started.md) /
[Build & deploy](build.md).

### 2. Full kit (limited batches)

<div id="piwalletsv-store-config"
     data-api-url="{{ store_api_url }}"
     data-dev-banner="{{ store_dev_banner }}"
     hidden></div>

When offered, a complete kit includes:

- Raspberry Pi Zero W (header soldered), heat sink, bonnet, OV5647 camera
- **Factory-flashed microSD** + **SD adapter** (full-size)
- 5 V adapter, power cable, **printed case**, kit insert

**You still need:** a **USB microSD reader/writer on your PC or Mac** to
[re-flash before you fund](user-manual.md#verify-sd-card-on-arrival) (strongly
recommended).

**Optional (not in the box):** a **micro-USB OTG adapter** and **USB flash drive**
for the **left** micro-USB port. These are only for **exporting or importing
your encrypted vault** when you upgrade firmware or replace the SD card — see
[USB backup](user-manual.md#usb-backup). You do **not** need them for normal
daily use. Optionally, you can **restore each wallet from your written seed
phrase(s)** on the bonnet.

The included card is flashed at the factory for convenience. For a cold
wallet, **re-flashing the signed download yourself** is the only practical
way to rule out tampering in transit — Pi hardware has no secure boot.

Printable insert for full-kit boxes:
[Open kit insert (print)](print/index.md) ·
[`kit-insert.html`](print/kit-insert.html) (full page, no site chrome).

<p class="piwalletsv-store-stock" data-store-stock="full-kit" hidden></p>

<div class="piwalletsv-store-actions">
  <button type="button" class="md-button md-button--primary" data-store-checkout="stripe" data-sku="full-kit">
    Buy with card
  </button>
  <button type="button" class="md-button" data-store-checkout="bsv" data-sku="full-kit">
    Buy with BSV
  </button>
</div>

<p class="piwalletsv-store-follow" data-store-follow="full-kit" hidden>
  Follow <a href="https://x.com/PiWalletSV">@PiWalletSV on X</a> for updates.
</p>

### 3. Case only

Already have the Pi stack? You can **buy a printed case** from the project
instead of printing from
[`hardware/case/`](https://github.com/mohrt/PiWalletSV/tree/main/hardware/case).

- Self-print: STLs and SCAD in the repo (PETG recommended)
- **Case-only orders:**

<div class="piwalletsv-store-actions">
  <button type="button" class="md-button md-button--primary" data-store-checkout="stripe" data-sku="case-only">
    Buy with card
  </button>
  <button type="button" class="md-button" data-store-checkout="bsv" data-sku="case-only">
    Buy with BSV
  </button>
</div>

<p class="piwalletsv-store-follow" data-store-follow="case-only" hidden>
  Follow <a href="https://x.com/PiWalletSV">@PiWalletSV on X</a> for updates.
</p>

## Questions

Message [@PiWalletSV on X](https://x.com/PiWalletSV) for kit, case, or
hardware compatibility questions.

**Policies:** [Shipping](purchase/shipping.md) · [Returns & refunds](purchase/returns.md) · [Order status](store/order-status.md) · [Disclaimer](disclaimer.md)
