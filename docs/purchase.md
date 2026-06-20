# Purchase

PiWalletSV is designed as a **DIY cold-wallet stack**: download signed
firmware, flash a microSD, and assemble the Pi + bonnet + camera yourself.
That is the **default path** — especially while Raspberry Pi boards are
hard to buy.

## Raspberry Pi supply

Raspberry Pi boards (especially **Pi Zero / Zero W**) are in **very low
supply** right now. Memory and fab capacity are heavily pulled toward
AI and datacenter demand, so distributors often show long lead times or
empty shelves.

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
| **micro-USB OTG adapter** | **Left** port + USB stick for vault backup |
| **Case** | [Print yourself](https://github.com/mohrt/PiWalletSV/blob/main/hardware/case/README.md) or buy case-only (below) |

**Steps:**

1. [Download](download.md) the signed `{{ firmware_image_file }}` from GitHub
2. GPG + SHA-256 verify ([Security § Release key](security.md#release-key))
3. Flash with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) —
   see [Flash and first run](build-image.md)
4. Assemble and complete first boot ([User manual](user-manual.md))

Or build from source: [Getting started](getting-started.md) /
[Build & deploy](build.md).

### 2. Full kit (limited batches)

When offered, a complete kit includes:

- Raspberry Pi Zero W (header soldered), heat sink, bonnet, OV5647 camera
- **Factory-flashed microSD** + **SD adapter** (full-size)
- 5 V adapter, power cable, OTG adapter, **printed case**, kit insert

**You still need:** a **USB microSD reader/writer on your PC or Mac** to
[re-flash before you fund](user-manual.md#verify-sd-card-on-arrival) (strongly
recommended).

The included card is flashed at the factory for convenience. For a cold
wallet, **re-flashing the signed download yourself** is the only practical
way to rule out tampering in transit — Pi hardware has no secure boot.

Printable insert for full-kit boxes:
[`docs/print/kit-insert.md`](print/kit-insert.md).

Contact [@PiWalletSV on X](https://x.com/PiWalletSV) for batch availability
and pricing (limited runs; not guaranteed in stock).

### 3. Case only

Already have the Pi stack? You can **buy a printed case** from the project
instead of printing from
[`hardware/case/`](https://github.com/mohrt/PiWalletSV/tree/main/hardware/case).

- Self-print: STLs and SCAD in the repo (PETG recommended)
- **Case-only orders:** message [@PiWalletSV on X](https://x.com/PiWalletSV)

Unauthorized resale of printed case goods requires prior written permission
([Disclaimer §12](disclaimer.md#12-kits-and-case-no-unauthorized-resale)).

## Questions

Message [@PiWalletSV on X](https://x.com/PiWalletSV) for kit, case, or
hardware compatibility questions.
