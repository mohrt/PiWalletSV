# Flash and first run

This is the user-facing path from "I have a downloaded SD-card image"
to "I've signed my first transaction." It describes the flow that
ships **without compiling anything yourself**, using the prebuilt
PiWalletSV image distributed from the [Download](download.md) page.

If you'd rather build the image yourself from source, see
[Build &amp; deploy](build.md). Both paths produce a sealed appliance
that boots straight into the bonnet UI; this page is shorter because
the prebuilt image has already done the provisioning step for you.

!!! warning "Alpha software"

    PiWalletSV is alpha. Use TESTNET and small amounts only. The image
    artifact described here is published as a community alpha — there
    is no commercial support behind it, and you remain responsible
    for verifying signatures and reading the [Disclaimer](disclaimer.md).

## What you need

- A downloaded image (`.img.xz`) and its `.asc` signature, both from
  the official [Download](download.md) page.
- A **microSD card**, 8&nbsp;GB or larger.
- A **Raspberry Pi Zero 2&nbsp;W** with the Adafruit 1.3&quot; 240×240 TFT
  bonnet ([product 4506](https://www.adafruit.com/product/4506)) and a
  Pi Camera Module v2 or v3.
- A **5&nbsp;V power supply** with a micro-USB plug for the bonnet's
  PWR-IN port.
- A computer with `gpg`, `xz`, and either Raspberry Pi Imager or the
  ability to run `dd` (Linux/macOS) or balenaEtcher (cross-platform).

## Step 1 &mdash; Verify the download

This is the single most important step. The whole point of an
air-gapped signer is that you trust the firmware running on it; if
you flash a tampered image you've defeated the security model
yourself. Skipping this step makes everything else meaningless.

```bash
# In the directory where you downloaded the files:

# 1. Import the PiWalletSV release key (one-time).
gpg --keyserver hkps://keys.openpgp.org --recv-keys <RELEASE_KEY_FINGERPRINT>

# 2. Verify the signature on the image.
gpg --verify piwalletsv-<VERSION>.img.xz.asc piwalletsv-<VERSION>.img.xz

# 3. Cross-check the SHA-256 against the published value.
shasum -a 256 piwalletsv-<VERSION>.img.xz
```

The Download page lists the expected fingerprint and the SHA-256.
A successful signature check ends with **&ldquo;Good signature&rdquo;** and the
release key fingerprint &mdash; nothing else counts. If the verification
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
       *No filtering* (or pick *Raspberry Pi Zero 2 W*).
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

## Step 3 &mdash; Assemble the hardware

1. Insert the flashed SD card into the Pi Zero 2&nbsp;W.
2. Plug the bonnet onto the Pi's GPIO header. The bonnet's PWR-IN
   micro-USB port is the one **farther from the SD slot**; that's
   where you'll connect power.
3. Connect the Pi Camera ribbon to the Pi's CSI port (small flex
   cable connector under the bonnet, near the SD slot edge).
4. Plug the 5&nbsp;V power supply into the bonnet's PWR-IN.

The first boot takes 30&ndash;45 seconds. The panel stays dark for the
first 15&ndash;20 seconds while systemd brings up local-fs.target, then
lights up with the disclaimer screen.

## Step 4 &mdash; Accept the disclaimer

The bonnet will show the legal disclaimer the very first time it
boots. Read it; the alpha-software language is not boilerplate. Use
the joystick to scroll, and press **A** to accept.

The acceptance is recorded in `~/.piwallet/terms.json` and you won't
see this screen again unless the disclaimer version changes.

## Step 5 &mdash; Set a PIN

Next you'll be asked to choose a PIN. The PIN protects the encrypted
vault on disk; it's not strong on its own (the vault file would be
extracted off the SD card by anyone with physical access), but it
does prevent casual misuse and gates every signing operation.

- Use the joystick to scroll digits, **A** to confirm a digit, **B**
  to delete the previous digit.
- The bonnet asks you to enter the PIN twice to catch typos.

## Step 6 &mdash; Create or restore your wallet

You'll see a choice between:

- **New wallet** &mdash; the bonnet generates a fresh BIP39 mnemonic on
  device. The mnemonic is shown to you a few words at a time so you
  can write it down on paper. **Write it down**: this is the only
  way to recover the wallet if the SD card is damaged or wiped.
- **Restore wallet** &mdash; you enter an existing 12- or 24-word BIP39
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

1. **Long-press B** to open Settings.
2. Joystick down to **&ldquo;Airgap status&rdquo;**.
3. Press **A**.

You should see a green **&ldquo;Air-gapped&rdquo;** header and six rows reading
`OK`:

| Check | What it proves |
|-------|----------------|
| `modules` | No Wi-Fi or Bluetooth driver modules are loaded into the kernel. |
| `rfkill` | Every radio the kernel knows about is soft- or hard-blocked. |
| `interfaces` | Only the loopback (`lo`) network interface is present. |
| `services` | wpa\_supplicant, NetworkManager, hciuart, and bluetooth are all inactive. |
| `boot_config` | Firmware-level overlays disable Wi-Fi and Bluetooth at boot. |
| `blacklist` | The radio kernel modules are blacklisted in modprobe. |

If any row shows `!!`, **stop**. The device is leaking somewhere
and the prebuilt image has been altered or built incorrectly. Re-do
Step&nbsp;1 (signature verification) and re-flash. If the second flash
also fails the airgap check, contact [@PiWalletSV on X](https://x.com/PiWalletSV)
or file an issue on
[GitHub](https://github.com/mohrt/PiWalletSV/issues) with the
specific failing rows.

Press **A** at any time to refresh the report. Press **B** to return
to Settings.

## Step 8 &mdash; Pair with the companion PWA

The PiWalletSV companion is a Progressive Web App that handles the
online half of the wallet (UTXO discovery, watch-only balances,
broadcast). It never sees your private keys.

1. On a separate device with a camera, open the
   [companion]({{ companion_url }}) in a modern browser.

### Add the companion to your Home Screen

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
device that can pull updates is not air-gapped. To upgrade:

1. Back up your existing vault: see
   [Operate](operate.md#vault-stewardship).
2. Download and verify a new image from the [Download](download.md)
   page (Step&nbsp;1 above).
3. Re-flash and re-set up.
4. Restore the wallet from your written-down mnemonic, OR import the
   vault file from the backup.

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
The Pi Camera v2 has a fixed focal length around 30&nbsp;cm. If your
companion device is closer or farther, the QR sequence will be
blurry. Hold the bonnet about a foot away. The Camera v3 has
autofocus and is much more forgiving.

**&ldquo;Airgap status&rdquo; shows BREACH.**
This is the diagnostic working as designed: it found a leak. Don't
sign anything on this device until the report is all-green. The
fastest fix is to re-verify the image signature (Step&nbsp;1) and
re-flash; if it persists, contact [@PiWalletSV on X](https://x.com/PiWalletSV)
or file a [GitHub issue](https://github.com/mohrt/PiWalletSV/issues).

For everything else, see [Operate](operate.md) or
[Help & support](index.md#help--support).

## Help & support

--8<-- "docs/includes/support-contact.md"

*[PWA]: Progressive Web App
*[CSI]: Camera Serial Interface
*[GPIO]: General-Purpose Input/Output
*[BIP39]: Bitcoin Improvement Proposal 39 (mnemonic)
*[BIP44]: Bitcoin Improvement Proposal 44 (HD path)
