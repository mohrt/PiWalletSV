<!--
  PiWalletSV — Kit insert (print source)

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
| **Downloads & verify** | https://piwalletsv.com/download |
| **Full manual (online)** | https://piwalletsv.com/user-manual/ |
| **Firmware version** | _________________________ |
| **Image ID (batch)** | _________________________ |

---

## ⚠ Beta software — read this first

PiWalletSV is **pre-release (beta) software**. There is **no warranty**
and **no recovery service** if you lose your seed phrase or PIN.

- Use **testnet** and **small amounts** until you are confident.
- **Your funds are always recoverable** from any BIP39-compatible wallet
  using your seed phrase. PiWalletSV is not required to access your funds.
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
7. **Micro-USB cable** (USB-A → micro-USB) — from the power adapter to
   the **right** micro-USB port (**power only**)
8. **Micro-USB OTG adapter** (micro-USB → USB-A socket) — plug into the
   **left** micro-USB port with a **USB flash drive** to back up your
   vault (**Settings → Maintenance → USB backup**) before you re-flash the SD card.
   **Not** for power and **not** for connecting the Pi to a computer.
9. **Case** (may include a tamper-evident seal)
10. **This insert**

Keep the seed phrase backup **separate** from the device and SD card.

---

<div style="page-break-after: always;"></div>

## Step 0 — Verify the microSD (do this before funding)

Your kit includes a **factory-flashed** microSD for convenience. For a
**cold wallet**, treat that as a starting point only — **re-flash from the
signed GitHub download** before you create a wallet or receive BSV.

**Why:** The card could have been swapped or modified in transit. Raspberry
Pi has **no secure boot**. Re-flashing a GPG-verified image you download
yourself is the only practical way to eliminate that doubt.

**Do not boot the Pi to verify.** The device cannot show a trustworthy
checksum of the whole card, and the first power-on already changes the
microSD.

### Option B — Re-flash (recommended — easiest)

**This is what we recommend.** Download the official image, verify it
yourself, and write it to the card. On a new kit that is simpler and
stronger than trying to prove the factory flash byte-for-byte.

1. **Download** from https://piwalletsv.com/download (links to GitHub Releases):
   - `piwalletsv-<version>.img.xz`
   - `piwalletsv-<version>.img.xz.asc` (signature)

2. **Verify OpenPGP signature** (one-time setup; fingerprint on the
   security page at piwalletsv.com):

   ```
   gpg --keyserver hkps://keys.openpgp.org --recv-keys <RELEASE_KEY_FINGERPRINT>
   gpg --verify piwalletsv-<version>.img.xz.asc piwalletsv-<version>.img.xz
   ```

   You must see **Good signature**. If not, **stop** — do not flash.

3. **Verify SHA-256** of the `.img.xz` against the hash on the download
   page (see Option A below).

4. **Re-flash the microSD** (Pi still off):
   - Remove the microSD card.
   - Insert into your computer (USB card reader).
   - Use **Raspberry Pi Imager** (free): **Use custom** → select the
     verified `.img.xz` → write to the SD card.
   - Do **not** enable SSH, Wi-Fi, or hostname customisation.
   - Eject, put the card back in the Pi.

5. Power on and continue with **First boot** below.

**Note:** Re-flashing **erases** the card. That is OK on a new kit.
If you already have a wallet, **back up the vault to a USB flash drive
first** (included OTG adapter + stick → **Settings → Maintenance → USB backup**).
After re-flash, restore from that backup or your seed phrase.

**Tamper seal:** If your case has a security sticker, inspect it before
first use. A broken seal is a reason to prefer **Option B**.

### Option A — Light checks (optional, weaker)

Use only if you skip re-flash for now.

**Paperwork (no boot):**

1. Compare **Image ID** and **Firmware version** printed at the top
   of this card to **https://piwalletsv.com/download**.
2. **Match** → paperwork matches that batch. **Mismatch** → do not
   use; re-flash (Option B).

This does **not** prove the microSD was flashed correctly.

**Hash the card on your computer (advanced):**

1. **Do not boot the Pi.** Remove the microSD and insert it in a USB
   card reader on your computer.
2. Hash the entire card (example; use the correct device name):

   ```
   sudo dd if=/dev/sdX bs=4M status=progress | shasum -a 256
   ```

3. Compare to the **published card hash** for your Image ID on
   piwalletsv.com (when listed). If none is published, use Option B.
   Re-flashing is usually **easier** than this.

**Verify the download file (required before Option B anyway):**

1. At **https://piwalletsv.com/download**, note the **SHA-256** for
   your `piwalletsv-<version>.img.xz` file.
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

1. **Pi off.** Peel and press the **heat sink** onto the Pi Zero SoC
   (main chip). Let adhesive set if the kit uses a stick-on pad.
2. Seat the **bonnet** on the 40-pin GPIO header (straight, fully
   seated).
3. Connect the **camera ribbon** to the Pi CSI port (under/near the SD
   slot — latch open, insert, latch closed).
4. Insert the **microSD** (label side as printed on the Pi).
5. **Two micro-USB ports** (display facing you):
   - **Right port — POWER ONLY.** Plug the included **micro-USB cable**
     (from the 5 V adapter) here. Labeled **PWR IN** on the bonnet.
     **Never** plug a flash drive or OTG adapter into this port.
   - **Left port — USB flash drive only.** Plug the included **OTG
     adapter** here, then a FAT/exFAT stick for **Settings → Maintenance → USB
     backup**. **Not** for power and **not** for connecting to a
     computer.

   ```
   Bonnet display facing you:
        LEFT                    RIGHT
     flash drive               POWER
     (OTG + stick)         (5 V adapter cable)
   ```

First boot: the display may stay dark **15–30 seconds**, then the
disclaimer appears.

---

## First boot (bonnet)

### 1. Disclaimer

- Read all pages (joystick **LEFT/RIGHT** to change page).
- Hold **A** on the final page to accept.

### 2. Vault PIN

- Choose **New vault** and set a **PIN** (4–12 digits).
- Use a **long PIN (12+ digits)** for cold storage.
- **Wrong PIN six times in a row wipes the vault** on the device.
- The PIN protects the encrypted file on the SD card — **not** your seed.

### 3. Create or restore a wallet

From the **Wallets** list:

- **+ New wallet** — device generates a new seed. **Write every word on
  paper or steel.** This is your **only** recovery path.
- **+ Restore wallet** — enter an existing 12- or 24-word BIP39 phrase.

**Never** type your seed into a phone, laptop, or website.

### 4. Air-gap check (important)

Before mainnet funds:

1. From **Wallets**, press **B** → **Settings** → **Maintenance** → **Airgap status**.
2. Confirm **Air-gapped** (green) and **Wi-Fi / Bluetooth / Network**
   show **OK**.

If anything shows **BREACH** or **!!**, do **not** sign until resolved
(see online manual).

### 5. Pair the companion app

On a **phone or laptop** (online device):

1. Open **https://app.piwalletsv.com**
2. Follow prompts to scan the **pairing QR** shown on the Pi.
3. The companion holds **public** data only (xpub, addresses). It never
   receives your seed or PIN.

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
| **USB backup** | OTG + flash drive → Settings → Maintenance → USB backup |

**Lost PIN + no seed** → funds not recoverable.  
**Lost SD + have seed** → restore wallet on a new setup or re-flash.

---

## Do / Don't

| ✓ Do | ✗ Don't |
|------|---------|
| Re-flash SD from signed download before funding (Step 0) | Boot Pi to "verify" or trust pre-flashed card blindly |
| Write seed offline; store securely | Type seed into any networked device |
| Use long PIN; test on testnet first | Share PIN or seed with anyone |
| Check **Airgap status** periodically | Connect Pi to Wi-Fi / Ethernet |
| Re-flash from signed download when upgrading | Skip signature verify on updates |

---

## Upgrading firmware

PiWalletSV has **no over-the-air updates** and **no USB update from a
computer** (by design). To upgrade:

1. **Back up the vault** to a USB flash drive (OTG adapter + stick →
   **Settings → Maintenance → USB backup**), or confirm you have your seed phrase.
2. Download and **verify** the new image on your **computer** at
   piwalletsv.com/download.
3. **Remove the microSD**, re-flash it on your computer, then put it
   back in the Pi.
4. **Restore** the vault from USB backup (or restore wallet from seed).
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
│  Verify SD:  piwalletsv.com/download                      │
│  Manual:     piwalletsv.com/user-manual                     │
│                                                             │
│  BEFORE FUNDING:  re-flash verified image (recommended)     │
│  RECOVERY = 12/24 words ONLY  (not PIN, not support)        │
│  AIRGAP: Settings → Maintenance → Airgap status → all OK    │
│  USB (display facing you): RIGHT=power  LEFT=flash drive  │
└─────────────────────────────────────────────────────────────┘
```

---

*Document: kit-insert · Rev. 1 · For PiWalletSV round-one kits*
