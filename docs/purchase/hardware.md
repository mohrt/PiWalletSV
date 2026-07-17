# Ways to get hardware

PiWalletSV is designed as a **DIY cold-wallet stack**: download signed firmware,
flash a microSD, and assemble the Pi + bonnet + camera yourself. That is the
**default path** — especially while Raspberry Pi boards are hard to buy.

Ready to buy a limited batch instead? See the [shop](shop.md).

## Batch status

**Round-one beta** — limited quantity when kits are offered. Follow
[@PiWalletSV on X](https://x.com/PiWalletSV) for announcements.

## Raspberry Pi supply

Raspberry Pi boards (especially **Pi Zero / Zero W**) are in **very low supply**
right now. Memory and fab capacity are heavily pulled toward AI and datacenter
demand, so distributors often show long lead times or empty shelves.

We do **not** currently sell **Raspberry Pi Zero 2** kits — those boards are
unobtainable at a reasonable price. Round-one kits use **Pi Zero W**.

**What that means for you:**

- **Full pre-assembled kits** are offered only in **small batches** when boards
  are available at a sane price — not as always-in-stock inventory.
- **Most builders** should plan to **source their own Pi, bonnet, and camera**
  and flash from [GitHub Releases](https://github.com/mohrt/PiWalletSV/releases)
  ([Download](../download.md) links there).
- Ask [@PiWalletSV on X](https://x.com/PiWalletSV) for current kit or case
  availability before ordering.

## Three paths

### 1. DIY (default)

Bring your own parts, flash the official image, print or buy a case.

**You need:**

| Part | Notes |
|------|--------|
| **Raspberry Pi Zero / Zero W / Zero WH** | 32-bit armv6 image; solder header if needed |
| **Adafruit 4506** bonnet | 240×240 TFT, joystick, A/B buttons |
| **ArduCam OV5647** + cable | Kit camera; not Camera Module 3 |
| **microSD** 8 GB+ | Blank; you flash firmware |
| **5 V power** + micro-USB cable | **Right** port = power only |
| **micro-USB OTG adapter + USB stick** | **Optional** — left port only; export/import vault during upgrades (see [User manual](../user-manual.md#usb-backup)) |
| **Case** | [Print yourself](https://github.com/mohrt/PiWalletSV/blob/main/hardware/case/README.md) or [buy case-only](shop.md) |

**Steps:**

1. Open [Download](../download.md) → get the signed image from
   [GitHub Releases](https://github.com/mohrt/PiWalletSV/releases)
2. GPG + SHA-256 verify ([Security § Release key](../security.md#release-key))
3. Flash with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) —
   see [Flash and first run](../build-image.md)
4. Assemble and complete first boot ([User manual](../user-manual.md))

Or build from source: [Getting started](../getting-started.md) /
[Build & deploy](../build.md).

### 2. Full kit (limited batches)

When offered, a complete kit includes:

- Raspberry Pi Zero W (header soldered), heat sink, bonnet, OV5647 camera
- **Factory-flashed microSD** + **SD adapter** (full-size)
- 5 V adapter, power cable, **printed case**, kit insert

**You still need:** a **USB microSD reader/writer on your PC or Mac** to
[re-flash before you fund](../user-manual.md#verify-sd-card-on-arrival) (strongly
recommended).

**Optional (not in the box):** a **micro-USB OTG adapter** and **USB flash drive**
for the **left** micro-USB port — only for [USB backup](../user-manual.md#usb-backup)
during upgrades. You do **not** need them for normal daily use.

The included card is flashed and **boot-tested at the factory**. We run
diagnostics on the assembled kit and test the display, camera, joystick,
buttons, and software checks before shipment. Because that process writes
logs and other state, the shipped card no longer byte-matches the pristine
release image and cannot be validated with a whole-image checksum.

You may accept the tested card as shipped, but that relies on the factory
and delivery chain. For proper cold-wallet assurance, **verify the signed
download and re-flash the card yourself before funding**. The checksum
still verifies the downloaded `.img.xz`; re-flashing writes that verified
release to your card. Pi hardware has no secure boot.

Printable insert for full-kit boxes:
[Open kit insert (print)](../print/printables.md) ·
[`kit-insert.html`](../print/kit-insert.html) (full page, no site chrome).

[Buy full kit in the shop →](shop.md)

### 3. Case only

Already have the Pi stack? Buy a **printed case** from the project instead of
printing from
[`hardware/case/`](https://github.com/mohrt/PiWalletSV/tree/main/hardware/case)
(PETG recommended for self-print).

[Buy case-only in the shop →](shop.md)

## Questions

[@PiWalletSV on X](https://x.com/PiWalletSV) ·
[Shipping](shipping.md) ·
[Returns](returns.md) ·
[Shop](shop.md)
