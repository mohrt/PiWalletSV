### Why verify?

PiWalletSV is a **cold wallet**. You should trust the microSD firmware
only if it matches an **official PiWalletSV release** — not a card
substituted in transit or at fulfillment.

If your kit shipped with a **pre-flashed card**, verify it **before**
you create a wallet or receive funds.

| | Option | Best for |
|---|--------|----------|
| **B** | **Re-flash from a verified image** | **Recommended — easiest real assurance** (~15–30 min) |
| **A** | **Light checks** | Paperwork sanity check, or advanced SD dump (~5–60 min) |

!!! tip "Re-flash is the easiest path"
    **Option B** is what we recommend for cold storage. You download the
    signed release yourself, verify it, and write it to the card. That
    is simpler and stronger than trying to prove the factory-flashed
    card byte-for-byte without rewriting it.

!!! warning "Do not boot the Pi to verify"
    The device **cannot** show a trustworthy checksum of the whole
    microSD. The first power-on already changes the card (system logs,
    disclaimer file, and more). There is no on-screen Image ID check
    that proves the card matches the official image.

!!! note "Honest limits"
    Raspberry Pi hardware has **no secure boot**. Option B removes
    supply-chain doubt because **you** supply the image from
    [Download](download.md) (GitHub Releases) after GPG verification.

### Before you start

- Do this **before funding** the device. **Option B erases the card**;
  if you already created a wallet, back up first
  ([Upgrade your device § Step 1](#step-1-back-up-before-you-flash)).
- Check **tamper-evident packaging** on the case if included.
- For Option B you need a computer (internet once), **GPG**, a **card
  reader**, and [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
  (or balenaEtcher / `dd`).

---

## Option B — Re-flash from a verified image (recommended)

Replace the included microSD contents with firmware **you** downloaded
and verified. On a new kit this is the **simplest** way to know the
card is correct.

#### 1. Download

From [Download](download.md):

- `piwalletsv-<VERSION>.img.xz`
- `piwalletsv-<VERSION>.img.xz.asc`
- `SHA256SUMS` (+ `.asc` if provided)

Your kit paperwork states which `<VERSION>` applies (e.g. round-one
`0.1.0-r1`).

#### 2. Verify signature and checksum

Import the release key once (fingerprint in
[Security § Release key](security.md#release-key)):

```bash
gpg --keyserver hkps://keys.openpgp.org --recv-keys <RELEASE_KEY_FINGERPRINT>
gpg --verify piwalletsv-<VERSION>.img.xz.asc piwalletsv-<VERSION>.img.xz
shasum -a 256 piwalletsv-<VERSION>.img.xz   # match SHA256SUMS
```

**Stop if anything fails.** Do not flash.

Step-by-step:
[Flash and first run § Verify the download](build-image.md#step-1-verify-the-download).

#### 3. Re-flash the microSD

1. **Do not power on the Pi yet** (or power off if you already did).
2. **Remove** the microSD and insert it into your computer (USB reader).
3. Flash the verified `.img.xz` with Raspberry Pi Imager
   (**Use custom** → select file). Do **not** enable OS customisation
   (no SSH/Wi‑Fi setup).
4. Eject, reinsert in the Pi, power on.

Details:
[Flash and first run § Flash the image](build-image.md#step-2-flash-the-image).

#### 4. First-time setup

Continue from [Flash and first run § Assemble](build-image.md#step-3-assemble-the-hardware):
disclaimer → vault PIN → wallet →
[air-gap check](build-image.md#step-7-verify-the-air-gap).

---

## Option A — Light checks (optional)

Use these only if you are **not** re-flashing yet. They are **weaker**
than Option B.

#### A1. Image ID on the kit insert (paperwork only)

1. Compare **Image ID** and firmware version printed on your **kit
   insert** (or packaging) to the verify list on **piwalletsv.com**
   (linked from [Download](download.md)).
2. **Match** → paperwork matches that official batch. **Mismatch** →
   do not use; re-flash (Option B).

This does **not** prove the microSD in the box was flashed correctly —
only that the paperwork matches a published batch.

#### A2. Hash the microSD on your computer (advanced)

To check the **card itself** without re-flashing:

1. **Do not boot the Pi.** Remove the microSD and insert it into your
   computer (USB card reader).
2. Copy or hash the entire card (example on Linux; adjust device name):

   ```bash
   sudo dd if=/dev/sdX bs=4M status=progress | shasum -a 256
   ```

   On macOS, use `/dev/rdiskN` and `shasum -a 256` the same way.

3. Compare the result to the **published card hash** for your Image ID
   on piwalletsv.com (when provided for your batch).

If no card hash is published, this step cannot confirm the card — use
Option B instead. In practice **re-flashing is easier** than maintaining
a full-card dump workflow.

#### A3. Verify the release file on the download page

Confirms the **official `.img.xz` file** on piwalletsv.com is intact.
Required before Option B; **does not** prove the microSD in your kit
matches that file.

1. From [Download](download.md), note the **SHA-256** for
   `piwalletsv-<VERSION>.img.xz` (also in `SHA256SUMS`).
2. Download the same `.img.xz` and run:

   ```bash
   shasum -a 256 piwalletsv-<VERSION>.img.xz
   ```

3. The output must **exactly match** the published hash.

---

## Already flashed the card yourself?

If you downloaded, verified, and flashed before first boot, you already
followed Option B. Proceed to [First boot](#1-first-boot).

---

## After verification

- **Settings → Maintenance → Airgap status** — confirm Wi‑Fi / Bluetooth / network
  indicators
  ([User manual § Airgap status](#airgap-status)).
- Create or restore your wallet; test on **testnet** before mainnet.

If anything fails after a verified re-flash, stop and contact support
before signing.
