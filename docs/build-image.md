# Flash and first run

This is the user-facing path from "I have a downloaded SD-card image"
to "I've signed my first transaction." It describes the flow that
ships **without compiling anything yourself**, using the prebuilt
PiWalletSV image from
[GitHub Releases](https://github.com/mohrt/PiWalletSV/releases)
([Download](download.md) links there).

If you'd rather build the image yourself from source, see
[Build &amp; deploy](build.md). Both paths produce a sealed appliance
that boots straight into the bonnet UI; this page is shorter because
the prebuilt image has already done the provisioning step for you —
including the USB backup mount daemon, FAT/exFAT tools, and bonnet
`ReadWritePaths` for `/mnt/piwallet-usb`
([Operate § USB vault backup](operate.md#usb-vault-backup)).

!!! warning "Beta software"

    PiWalletSV software is **beta**. It is fully functional with **no currently
    known issues**. Bugs that turn up will be fixed and released; all notices
    are posted on [@PiWalletSV](https://x.com/PiWalletSV). You remain responsible
    for verifying signatures and reading the [Disclaimer](disclaimer.md).

## What you need

- A downloaded image (`.img.xz`) and its `.asc` signature, both from
  [GitHub Releases](https://github.com/mohrt/PiWalletSV/releases).
- A **microSD card**, 8&nbsp;GB or larger.
- A **Raspberry Pi Zero W or Zero WH** with the Adafruit 1.3&quot; 240×240 TFT
  bonnet ([product 4506](https://www.adafruit.com/product/4506)) and an
  **ArduCam OV5647** camera module (32-bit Raspberry Pi OS Lite image).
- A **5&nbsp;V power supply** with a micro-USB plug for the bonnet's
  PWR-IN port.
- A computer with `gpg`, `xz`, and either Raspberry Pi Imager or the
  ability to run `dd` (Linux/macOS) or balenaEtcher (cross-platform).

## Step 1 &mdash; Verify the download { #step-1-verify-the-download }

This is the single most important step. The whole point of an
air-gapped signer is that you trust the firmware running on it; if
you flash a tampered image you've defeated the security model
yourself. Skipping this step makes everything else meaningless.

```bash
# In the directory where you downloaded the files:

# 1. Import the PiWalletSV release key (one-time).
gpg --keyserver hkps://keys.openpgp.org --recv-keys 9E048B6E7F54C49DE2D5AEB5DA261F4F2B0CA281

# 2. Verify the signature on the image.
gpg --verify piwalletsv-<VERSION>-<BOARD>[-maturity].img.xz.asc \
    piwalletsv-<VERSION>-<BOARD>[-maturity].img.xz

# 3. Cross-check the SHA-256 against the published value.
shasum -a 256 piwalletsv-<VERSION>-<BOARD>[-maturity].img.xz
```

Assets and checksums are on
[GitHub Releases](https://github.com/mohrt/PiWalletSV/releases)
([Download](download.md) is only a landing page). The release-key
fingerprint is in
[Security § Release key](security.md#release-key).
A successful signature check ends with **&ldquo;Good signature&rdquo;** against
that fingerprint &mdash; nothing else counts. If the verification
fails, **stop**: do not flash. Mismatched signatures are how
supply-chain attacks reach end-user devices.

## Step 2 &mdash; Flash the image

Pick the tab for your operating system. All recommended tools are free
and open source; they handle decompression of the `.img.xz` file
automatically so you don't need to unzip first.

=== ":fontawesome-brands-windows: Windows"

    **Recommended: [Raspberry Pi Imager](https://www.raspberrypi.com/software/)**
    (official, open source, easiest option on any platform)

    1. Download and install Raspberry Pi Imager from
       [raspberrypi.com/software](https://www.raspberrypi.com/software/).
    2. Launch Imager. Under **Raspberry Pi Device** choose
       *No filtering* (or pick *Raspberry Pi Zero W*).
    3. Under **Operating System** click
       **&ldquo;Use custom&rdquo;** and select the verified `.img.xz` file.
       Imager decompresses it for you — you do not need 7-Zip or
       any other tool.
    4. Under **Storage** pick your microSD card. Double-check the
       drive letter — Imager will erase it entirely.
    5. Click **Next**. When prompted about OS customisation, choose
       **&ldquo;No&rdquo;** — PiWalletSV is a sealed appliance and does not
       use SSH, Wi-Fi credentials, or any custom hostname.
    6. Click **Yes** to confirm the write, then wait. Imager
       verifies the written data automatically; let it finish before
       ejecting the card.

    **Alternative: [balenaEtcher](https://etcher.balena.io/)**
    (also open source; slightly simpler UI, no device-filter step)

    1. Download and install balenaEtcher.
    2. Click **Flash from file** and select the verified `.img.xz`.
    3. Click **Select target** and pick your SD card.
    4. Click **Flash!** and wait for the verification pass to complete.

=== ":fontawesome-brands-apple: macOS (GUI)"

    **Recommended: [Raspberry Pi Imager](https://www.raspberrypi.com/software/)**

    Install via the download page *or* with Homebrew:

    ```bash
    brew install --cask raspberry-pi-imager
    ```

    Then follow the same steps as the Windows tab above. Imager on
    macOS requests administrator permission to write to the SD card
    via a standard system prompt — grant it.

    **Alternative: [balenaEtcher](https://etcher.balena.io/)**

    ```bash
    brew install --cask balenaetcher
    ```

    1. Click **Flash from file** → select the `.img.xz`.
    2. Click **Select target** → pick the SD card disk (e.g. `disk4`,
       not a partition like `disk4s1`).
    3. Click **Flash!**

=== ":material-bash: macOS / Linux (CLI)"

    **Prerequisites**

    `xz` is needed to decompress `.img.xz`.
    It is pre-installed on most Linux distros.
    On macOS, install it with Homebrew:

    ```bash
    brew install xz
    ```

    **Identify your SD card**

    ```bash
    diskutil list   # macOS — look for a disk whose size matches the card
    lsblk           # Linux  — same idea
    ```

    Note the device path: on macOS it will be something like `/dev/disk4`
    (use the **raw** variant `/dev/rdisk4` for `dd`); on Linux
    something like `/dev/sdb`.

    **Unmount (macOS only) — do this before writing**

    ```bash
    diskutil unmountDisk /dev/diskN   # replace diskN with your disk, e.g. disk4
    ```

    **Write the image**

    The pipe form decompresses on the fly, so you don't need free disk
    space for the uncompressed `.img`:

    ```bash
    # macOS — /dev/rdiskN is the raw (fast) device
    xz -dc piwalletsv-<VERSION>.img.xz | sudo dd of=/dev/rdiskN bs=4m

    # Linux
    xz -dc piwalletsv-<VERSION>.img.xz | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
    ```

    Or decompress first if you prefer two separate steps:

    ```bash
    unxz piwalletsv-<VERSION>.img.xz          # produces .img alongside .img.xz
    sudo dd if=piwalletsv-<VERSION>.img of=/dev/rdiskN bs=4m   # macOS
    sudo dd if=piwalletsv-<VERSION>.img of=/dev/sdX bs=4M status=progress conv=fsync  # Linux
    sync
    ```

    **Eject (macOS)**

    ```bash
    diskutil eject /dev/diskN
    ```

    !!! danger "Triple-check the device path"
        `dd` has no undo. Writing to the wrong device will silently
        overwrite your system disk or another drive. Verify
        `diskutil list` / `lsblk` output carefully before running the
        write command.

!!! question "Received a pre-flashed kit?"
    The assembled kit was booted for factory diagnostics, so the shipped
    card will not byte-match the pristine image checksum. You should
    **re-flash from a signed, checksum-verified download** (recommended)
    before you create a wallet. Accepting it as shipped relies on the
    factory and delivery chain.
    See [User manual § Verify your SD card on arrival](user-manual.md#verify-sd-card-on-arrival).

--8<-- "docs/includes/remove-microsd-tip.md"

## Step 3 &mdash; Assemble the hardware

1. Insert the flashed SD card into the Pi Zero / Zero&nbsp;W.
2. Plug the bonnet onto the Pi's GPIO header. The bonnet's PWR-IN
   micro-USB port is the one **farther from the SD slot**; that's
   where you'll connect power.
3. Connect the Pi Camera ribbon to the Pi's CSI port (small flex
   cable connector under the bonnet, near the SD slot edge).
4. Plug the 5&nbsp;V power supply into the bonnet's PWR-IN.

The **first boot after flashing** takes longer than normal because the image
**expands the root partition to your SD card size**, then reboots once. Expect
roughly **2–3 minutes total** on a Pi Zero W before the disclaimer (about
**1–2 minutes longer** than everyday boots).

| Phase | What you see |
|-------|----------------|
| Power on → ~60–90 s | Panel may stay dark while the Pi boots |
| First boot | Automatic reboot when SD expansion finishes |
| Second boot | Logo splash → disclaimer (~1 minute after power-on) |

Every boot after that is a **single** boot (~1 minute to splash). The panel
may stay dark until the logo appears — that is normal on Pi Zero W.

If the panel stays blank for more than **3–5 minutes** after the second boot,
check HDMI tty2 or re-flash.

## Step 4 &mdash; Accept the disclaimer

The bonnet will show the legal disclaimer the very first time it
boots. Read it; the beta-software language is not boilerplate. Use
the joystick to scroll, and press **A** to accept.

The acceptance is recorded in `~/.piwallet/terms.json` and you won't
see this screen again unless the disclaimer version changes.

## Step 5 &mdash; First setup (vault)

You'll see **First setup** with two choices:

- **New vault (set PIN)** &mdash; choose and confirm a **6-digit** vault
  PIN. Use the joystick to scroll digits, **A** to confirm each digit,
  **B** to delete. The PIN protects the encrypted vault on disk.
- **Restore from USB** &mdash; import a backup stick if you're
  replacing the SD card or upgrading firmware
  ([User manual § USB backup](user-manual.md#usb-backup)).

If you chose **New vault**, the bonnet drops you on an empty **wallet
list** after PIN setup.

## Step 6 &mdash; Create or restore your first wallet

From the **wallet list**, choose:

- **+ New wallet** &mdash; the bonnet generates a fresh BIP39 mnemonic on
  device. The mnemonic is shown to you a few words at a time so you
  can write it down on paper. **Write it down**: this is the only
  way to recover the wallet if the SD card is damaged or wiped.
- **+ Restore wallet** &mdash; you enter an existing 12- or 24-word BIP39
  mnemonic via the on-screen word-entry keyboard. The bonnet
  validates the checksum word so a typo is caught before the wallet
  is created.

In either case you'll be asked for a short label (so you can tell
multiple wallets apart later) and the BIP-44 derivation path. The
bonnet defaults to the BSV mainnet path (`m/44'/236'/0'`); change
this only if you know exactly why.

When this step completes, the bonnet drops you onto the **wallet
list** screen. The wallet you just created is the one row.

## Step 7 &mdash; Verify the air-gap

Before you trust this device with anything sensitive, prove to
yourself that it's actually quiet on the airwaves. From the wallet
list:

1. **Press B** to open Settings.
2. Joystick down to **&ldquo;Airgap status&rdquo;**.
3. Press **A**.

You should see a green **&ldquo;Air-gapped&rdquo;** header and three
summary rows (**Wi-Fi**, **Bluetooth**, **Network**) reading `OK`. The full reference for the header, status glyphs (`OK` /
`!!` / `--`), and each check row lives in the
[User manual § Airgap status](user-manual.md#airgap-status); it is
included here for convenience:

--8<-- "docs/includes/airgap-status-reference.md"

If any row shows `!!`, **stop** and follow the BREACH steps above.
For a prebuilt image, re-do Step&nbsp;1 (signature verification) and
re-flash before contacting support.

## Step 8 &mdash; Pair with the companion PWA

The PiWalletSV companion is a Progressive Web App that handles the
online half of the wallet (UTXO discovery, watch-only balances,
broadcast). It never sees your private keys.

1. On a separate device with a camera, open the
   [companion]({{ companion_url }}) in a modern browser.

### Add the companion to your Home Screen

Prefer **Chrome** or **Firefox** over Safari — see
[User manual § Add to Home Screen](user-manual.md#add-to-home-screen)
for why. Then:

--8<-- "docs/includes/pwa-install-steps.md"

2. The companion's first-run flow walks you through pairing: it
   shows a button to start a pairing handshake.
3. On the bonnet, scroll to the wallet on the wallet list and press
   **A** to open it. From the wallet detail screen, choose
   **&ldquo;Pair with companion&rdquo;**.
4. The bonnet shows an animated QR sequence containing your wallet's
   public extended key (`xpub`). The companion captures the frames
   with its camera and reconstructs the pairing payload.

The pairing handshake transmits **only the xpub**, never private
material. Once it completes, the companion can derive addresses, scan
the chain for your UTXOs, and prepare unsigned transaction proposals
&mdash; but it cannot move funds without sending those proposals back to
the bonnet for an explicit human-confirmed signature.

## Step 9 &mdash; Sign your first transaction

To round-trip the full flow with no risk:

1. In the companion, switch to **TESTNET** mode (Settings &rarr; Network).
2. Send a small TESTNET amount to one of your wallet's receive
   addresses (use a faucet such as
   [satoshisvision.network](https://satoshisvision.network/)).
3. Once the UTXO is visible in the companion, draft an outgoing
   TESTNET transaction (back to the faucet, or to any TESTNET
   address you control).
4. The companion produces an **unsigned proposal** as an animated QR
   sequence. Point the bonnet's camera at the screen.
5. The bonnet reconstructs the proposal, displays the human-readable
   summary (output addresses, amounts, fee), and asks for the PIN.
6. Approve. The bonnet signs and produces an animated QR of the
   **signed transaction** for the companion to capture.
7. The companion broadcasts the signed transaction to the BSV
   testnet via [WhatsOnChain](https://test.whatsonchain.com/).

If steps 1&ndash;7 round-trip cleanly on TESTNET, the device is fully
operational.

## Routine use

Day-to-day, you only do steps 5&ndash;7 from above:

- Power on; enter PIN.
- Select wallet from the list.
- Camera in, scan unsigned proposal.
- Approve and PIN.
- Camera out, show signed QR back to the companion.

When you're done, you can simply unplug the device. There's no
&ldquo;safe shutdown&rdquo; ritual: the bonnet's filesystem is read-only
except for the small `.piwallet/` state directory, and write
operations there are deliberately atomic.

## Updating

There is no in-place update mechanism, by design: an air-gapped
device that can pull updates is not air-gapped. The full end-user
workflow — backup, re-flash, restore mnemonic or vault file, and
post-upgrade verification — is documented in
[User manual § Upgrade your device](user-manual.md#upgrade-your-device).

Brief summary:

1. Back up your mnemonic and/or run **Settings → Maintenance → USB backup → Backup to USB**
   (or copy `vault.bin` off the SD card)
   **before** flashing.
2. Download and verify a new image from
   [GitHub Releases](https://github.com/mohrt/PiWalletSV/releases)
   (Step&nbsp;1 above).
3. Re-flash the microSD (Step&nbsp;2 above).
4. Restore from your written-down mnemonic, or copy `vault.bin` back
   onto the new image — see the user manual for step-by-step detail.
5. Re-run **Airgap status** and a TESTNET smoke test.

## Troubleshooting

**Panel stays dark after 60 seconds.**
Most often the bonnet isn't fully seated on the GPIO header, or the
camera ribbon is loose. Power off, re-seat both, and try again. If
the bonnet's tiny green LED never lights, you have a power-supply
problem (5&nbsp;V/2.5&nbsp;A or better is the minimum).

**Joystick or buttons unresponsive.**
A bonnet revision difference: some early Adafruit batches mount the
joystick chip on a different I2C address. Contact
[@PiWalletSV on X](https://x.com/PiWalletSV) or open an issue on
[GitHub](https://github.com/mohrt/PiWalletSV/issues) with your
bonnet's silkscreen revision string.

**Camera doesn't detect QR codes.**
The kit **ArduCam OV5647** is fixed-focus around 30&nbsp;cm (~1&nbsp;ft).
If your companion device is closer or farther, the QR sequence will be
blurry. Hold the bonnet at about that distance while scanning.

**&ldquo;Airgap status&rdquo; shows BREACH.**
This is the diagnostic working as designed: it found a leak. See
[User manual § Airgap status](user-manual.md#airgap-status) for what
each indicator means. Don't sign anything until the report is
all-green. The fastest fix is to re-verify the image signature
(Step&nbsp;1) and re-flash.

For everything else, see [Operate](operate.md) or
[Help & support](index.md#help--support).

## Help & support

--8<-- "docs/includes/support-contact.md"

*[PWA]: Progressive Web App
*[CSI]: Camera Serial Interface
*[GPIO]: General-Purpose Input/Output
*[BIP39]: Bitcoin Improvement Proposal 39 (mnemonic)
*[BIP44]: Bitcoin Improvement Proposal 44 (HD path)
