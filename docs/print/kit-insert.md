<!--
  PiWalletSV — Kit insert (extended text source)

  For the branded 2-page welcome insert, use kit-insert.html instead
  (see README.md). This file is the long-form checklist + cut-out card.

  Print: US Letter or A4, black & white, double-sided recommended.
  Generate PDF: see README.md in this folder.

  Factory: fill in FIRMWARE_VERSION and IMAGE_ID before print if known.
-->

<div style="page-break-after: always;"></div>

# PiWalletSV — Quick Start & Security Checklist

**Air-gapped Bitcoin SV (BSV) cold wallet**

| | |
|---|---|
| **Website** | https://piwalletsv.com |
| **Companion app** | https://app.piwalletsv.com |
| **Downloads & verify** | https://github.com/mohrt/PiWalletSV/releases |
| **Full manual (online)** | https://piwalletsv.com/user-manual/ |
| **Firmware version** | _(fill before print)_ |
| **Image ID (batch)** | _(fill before print)_ |

---

## ⚠ Beta software — read this first

PiWalletSV software is **beta**. It is fully functional with **no currently
known issues**. Bugs that turn up will be fixed and released; all notices are
posted on [@PiWalletSV](https://x.com/PiWalletSV).

There is **no warranty** and **no recovery service** if you lose your seed
phrase or PIN.

- **Your funds are always recoverable** from any BIP44-compatible BSV
  wallet using your seed phrase (path `m/44'/236'/0'`). PiWalletSV is
  not required — tools such as iancoleman.io/bip39 or satofinder.com
  work. See https://piwalletsv.com/recover-without-device/
- **You** are the custodian. Write down your **12- or 24-word seed phrase**
  on paper or steel and store it safely.
- Read the full disclaimer on first boot (bonnet screen) and at
  https://piwalletsv.com/disclaimer/

---

## What is in your kit

Typical PiWalletSV kit contents:

1. **Raspberry Pi Zero** (with GPIO header for the bonnet)
2. **Heat sink** for the Pi Zero (attach before seating the bonnet)
3. **Adafruit 1.3″ TFT bonnet** (240×240 display, joystick, A/B buttons)
4. **ArduCam OV5647 camera** + ribbon cable
5. **microSD card** (factory-flashed with PiWalletSV firmware) + **SD adapter**
   (full-size). Use **your own USB microSD reader** on a PC/Mac to re-flash
   from GitHub before funding (strongly recommended — see Step 0).
6. **5 V USB power adapter** (wall charger)
7. **Micro-USB cable** (USB-A → micro-USB) — from the power adapter to the
   **right-most** micro-USB port (**power only**)
8. **Case** (may include a tamper-evident seal)
9. **This insert**

**Optional (not included):** a **micro-USB OTG adapter** and **USB flash
drive** for the **left** micro-USB port. Use them only to **export or import
your encrypted vault** when upgrading firmware or replacing the SD card —
**Settings → Maintenance → USB backup**. You do **not** need them for everyday
use. Optionally, you can **restore each wallet from your written seed phrase(s)**
on the bonnet. Never connect the Pi to a computer through either port.

Keep the seed phrase backup **separate** from the device and SD card.

---

<div style="page-break-after: always;"></div>

## Step 0 — Verify the microSD (do this before funding)

Your kit includes a **factory-flashed and tested** microSD. Before
shipment, the assembled device is booted into diagnostics and its display,
camera, joystick, buttons, and software checks are exercised. That test
boot writes to the card, so the shipped card no longer byte-matches the
pristine release image and cannot be validated against a whole-image
checksum.

You may accept the tested card as shipped, but that relies on the factory
and delivery chain. For proper **cold-wallet** assurance, treat it as a
starting point only — **re-flash from the signed GitHub download** before
you create a wallet or receive BSV. The checksum verifies the downloaded
`.img.xz`; re-flashing writes that verified release to your card.

**Why:** The card could have been swapped or modified in transit. Raspberry
Pi has **no secure boot**. Re-flashing a GPG-verified image you download
yourself is the only practical way to eliminate that doubt.

**Do not boot the Pi to verify.** The device cannot show a trustworthy
checksum of the whole card, and factory diagnostics have already changed
the shipped microSD.

### Option A — Re-flash (recommended — easiest)

**This is what we recommend.** Download the official image, verify it
yourself, and write it to the card. On a new kit that is simpler and
stronger than trying to prove the factory flash byte-for-byte.

1. **Download** from https://github.com/mohrt/PiWalletSV/releases:
   - `piwalletsv-<version>.img.xz`
   - `piwalletsv-<version>.img.xz.asc` (signature)

2. **Verify OpenPGP signature** (one-time setup; fingerprint on the
   security page at piwalletsv.com):

   ```
   gpg --keyserver hkps://keys.openpgp.org --recv-keys 9E048B6E7F54C49DE2D5AEB5DA261F4F2B0CA281
   gpg --verify piwalletsv-<version>.img.xz.asc piwalletsv-<version>.img.xz
   ```

   You must see **Good signature**. If not, **stop** — do not flash.

3. **Verify SHA-256** of the `.img.xz` against `SHA256SUMS` on the same
   GitHub release (see Option B below).

4. **Re-flash the microSD** (Pi still off):
   - Power off. Remove the microSD card — on an assembled unit you can
     pull it with a **thin pair of tweezers** without opening the case.
   - Insert into your computer (USB card reader).
   - Use **Raspberry Pi Imager** (free): **Use custom** → select the
     verified `.img.xz` → write to the SD card.
   - Do **not** enable SSH, Wi-Fi, or hostname customisation.
   - Eject, put the card back in the Pi.

5. Power on and continue with **First boot** below.

**Note:** Re-flashing **erases** the card. That is OK on a new kit.
If you already have a wallet, either **export the vault to USB** (optional
OTG adapter + stick in the **left** port → **Settings → Maintenance → USB backup**)
**or** be ready to **restore from your seed phrase(s)** after re-flash.

**Tamper seal:** If your case has a security sticker, inspect it before
first use. A broken seal is a reason to prefer **Option A**.

### Option B — Light checks (optional, weaker)

Use only if you skip re-flash for now.

**Paperwork (no boot):**

1. Compare **Image ID** and **Firmware version** printed at the top
   of this card to the matching release at
   **https://github.com/mohrt/PiWalletSV/releases**.
2. **Match** → paperwork matches that batch. **Mismatch** → do not
   use; re-flash (Option A).

This does **not** prove the microSD was flashed correctly.

**Hash the card on your computer (forensic record only):**

1. Power off. Remove the microSD and insert it in a USB card reader on
   your computer.
2. Hash the entire card (example; use the correct device name):

   ```
   sudo dd if=/dev/sdX bs=4M status=progress | shasum -a 256
   ```

This records what arrived; it does **not** authenticate the firmware.
Factory diagnostics have already changed the shipped card, so its hash
is not expected to match the pristine release image. Use Option A to
establish firmware trust.

**Verify the download file (required before Option A anyway):**

1. At **https://github.com/mohrt/PiWalletSV/releases**, open the release
   for your kit and note the **SHA-256** in `SHA256SUMS` for your
   `piwalletsv-<version>.img.xz` file.
2. Download that file and run (Mac/Linux terminal):

   ```
   shasum -a 256 piwalletsv-<version>.img.xz
   ```

3. Compare to the published hash. They must match exactly.

This confirms the **official release file** — not that your shipped
microSD matches it.

---

<div style="page-break-after: always;"></div>

## Assembly & power

1. **Pi off.** Connect the **camera ribbon** to the Pi CSI port (latch open →
   insert → latch closed); **exposed ribbon pins facing the board**.
2. Install the **camera** in the case; fasten with screws.
3. Insert the **microSD** in the Pi (label side as printed on the Pi).
4. Install the **Pi** in the case; **two screws**, one on each side of the header.
5. Seat the **bonnet** on the 40-pin GPIO header (straight, fully seated);
   **two screws** on the front side.
6. Seat the **button caps** and **lid**; fasten the lid screws.
7. **Two micro-USB ports** (bonnet display facing you):
   - **Right-most port — POWER ONLY.** Plug the included **micro-USB cable**
     (from the 5 V adapter) here. Labeled **PWR IN** on the bonnet.
     **Never** plug a flash drive or OTG adapter into this port.
   - **Other port (left) — optional USB vault export/import.** For upgrades,
     plug **your own** **OTG adapter** and **USB flash drive** here, then use
     **Settings → Maintenance → USB backup**. **Not included in the kit.**
     Or restore from seed after re-flash — no OTG required.
     **Not** for power and **not** for connecting the Pi to a computer.

   ```
   Bonnet display facing you:
        LEFT                    RIGHT-MOST
     USB backup              POWER (included)
     (your OTG + stick)      (5 V adapter cable)
     not included in kit
   ```

First boot: the display may stay dark **15–30 seconds**, then the
disclaimer appears.

---

## First boot (bonnet)

### 1. Disclaimer

- Read all pages (joystick **LEFT/RIGHT** to change page).
- Hold **A** on the final page to accept.

### 2. Vault PIN

- Choose **New vault** and set a **PIN** (6 digits).
- **Wrong PIN ten times in a row wipes the vault** on the device.
- The PIN protects the encrypted file on the SD card — **not** your seed.

### 3. Your first wallet (on the device)

Create the wallet **on the Pi first** — before opening the companion.
From the **Wallets** list:

- **+ New wallet** — device generates a new seed. **Write every word on
  paper or steel.** This is your **only** recovery path.
- **+ Restore wallet** — enter an existing 12- or 24-word BIP39 phrase.

Keys stay on the device. **Never** type your seed into a phone, laptop,
or website.

### 4. Air-gap check (important)

Before mainnet funds:

1. From **Wallets**, press **B** → **Settings** → **Maintenance** → **Airgap status**.
2. Confirm **Air-gapped** (green) and **Wi-Fi / Bluetooth / Network**
   show **OK**.

If anything shows **BREACH** or **!!**, do **not** sign until resolved
(see online manual).

### 5. Pair the companion (transfer the xpub)

After the wallet exists on the Pi, open the companion on a **phone or
laptop** (online device) and copy the **public** account xpub across:

1. Open **https://app.piwalletsv.com**
2. On the Pi, show the **pairing QR**; scan it with the companion.
3. The companion saves a **watch-only** wallet (xpub / addresses only).
   It never receives your seed or PIN.

**Verify receive addresses:** before sharing a deposit address for
large amounts, display the address on the **Pi bonnet** and confirm it
matches the companion (see online manual § Address verification).

---

<div style="page-break-after: always;"></div>

## Controls (bonnet)

| Control | Action |
|---------|--------|
| **Joystick UP/DOWN/LEFT/RIGHT** | Move selection / change digit |
| **Joystick press (center)** | Select / confirm (same as **A** in many screens) |
| **A** | Confirm / enter |
| **B** (short) | Back / cancel |
| **B** (hold ~5 s on boot splash) | Factory diagnostics (support) |

From **Wallets**: **B** short → **Settings** (Preferences or Maintenance).

---

## Daily use (summary)

1. **Receive:** companion shows address; optionally confirm on Pi screen.
2. **Send:** companion builds transaction → shows **QR code(s)** → Pi
   **camera scans** → you review on bonnet → hold **A** to sign →
   companion **broadcasts** (Pi stays offline).

Start with **testnet** until you trust the full flow.

---

## Backup & recovery

| What | Where |
|------|--------|
| **Seed phrase (12/24 words)** | **You** write on paper/steel — **required** |
| **Encrypted vault** | On SD card; needs **PIN** |
| **USB backup** | **Optional** OTG + flash drive (left port) → export/import vault on upgrade; or use seed restore |

**Lost PIN + no seed** → funds not recoverable.  
**Lost SD + have seed** → restore wallet on a new setup or re-flash.

---

## Do / Don't

| ✓ Do | ✗ Don't |
|------|---------|
| Re-flash SD from signed download before funding (Step 0) | Boot Pi to "verify" or trust pre-flashed card blindly |
| Write seed offline; store securely | Type seed into any networked device |
| Protect your 6-digit PIN; test on testnet first | Share PIN or seed with anyone |
| Check **Airgap status** periodically | Connect Pi to Wi-Fi / Ethernet |
| Re-flash from signed download when upgrading | Skip signature verify on updates |

---

## Upgrading firmware

PiWalletSV has **no over-the-air updates** and **no USB update from a
computer** (by design). To upgrade:

1. **Export the vault to USB** (optional OTG + stick → **Settings → Maintenance → USB backup**),
   **or** confirm you have your seed phrase(s).
2. Download and **verify** the new image on your **computer** from
   GitHub Releases (`github.com/mohrt/PiWalletSV/releases`).
3. **Remove the microSD** (power off; a **thin pair of tweezers** through
   the case slot — no disassembly), re-flash on your computer, then
   reinsert the same way.
4. **Restore** from USB backup **or** **Restore wallet** from seed on the bonnet.
5. Re-check **Airgap status**.

Full steps: https://piwalletsv.com/user-manual/#upgrade-your-device

---

## Support

| Need | Contact |
|------|---------|
| Usage questions | @PiWalletSV on X |
| Bugs & features | https://github.com/mohrt/PiWalletSV/issues |
| **Security issues** | Private report — see https://piwalletsv.com/security/ (not public GitHub) |

This insert is a summary. The authoritative manual lives at  
**https://piwalletsv.com/user-manual/**

---

**PiWalletSV** — Non-custodial. Beta software. MIT licensed.  
© PiWalletSV contributors. Save this card with your seed backup records.

<div style="page-break-after: always;"></div>

## Quick reference card (cut along dashed line)

```
┌─────────────────────────────────────────────────────────────┐
│  PiWalletSV                    app.piwalletsv.com           │
│  Verify SD:  github.com/mohrt/PiWalletSV/releases           │
│  Manual:     piwalletsv.com/user-manual                     │
│                                                             │
│  BEFORE FUNDING:  re-flash verified image (recommended)     │
│  RECOVERY = 12/24 words ONLY  (not PIN, not support)        │
│  AIRGAP: Settings → Maintenance → Airgap status → all OK    │
│  USB (display facing you): RIGHT-MOST=power  LEFT=optional backup (BYO OTG) │
└─────────────────────────────────────────────────────────────┘
```

---

*Document: kit-insert · Rev. 13 · For PiWalletSV round-one kits*
