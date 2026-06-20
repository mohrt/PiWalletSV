# Download

The fastest way to run PiWalletSV is to flash the prebuilt SD-card image
onto a microSD and boot. The image is a sealed appliance: it boots straight
into the bonnet UI, has no SSH or Wi-Fi, and runs PiWalletSV as the only
foreground task on the device.

**Canonical host:** signed firmware lives on
[GitHub Releases]({{ firmware_release_page }}). The same download URLs are
linked from **piwalletsv.com** and **dev.piwalletsv.com** — there is no
separate “dev firmware.”

!!! info "Current release"
    Release **{{ firmware_github_tag }}** (`{{ firmware_version }}`, board **{{ firmware_board }}**, beta)
    targets **Raspberry Pi Zero / Zero W / Zero WH** (32-bit armv6). Download from
    [GitHub Releases]({{ firmware_release_page }}) or follow
    [Build & deploy](build.md) to reproduce the image from source.

## Which image file?

Board slugs follow [SeedSigner](https://github.com/SeedSigner/seedsigner/releases)
(processor tier, not Wi‑Fi vs non‑W):

| Board slug | Raspberry Pi hardware |
|------------|------------------------|
| **pi0** | Pi Zero v1.3, Pi Zero W, Pi Zero WH |
| **pi02w** | Pi Zero 2 W, Pi 3 Model B *(future)* |
| **pi2** | Pi 2 Model B *(future)* |
| **pi4** | Pi 4 Model B, Pi 400 *(future)* |

For round‑1 kits use **`pi0`**.

## Files (release {{ firmware_github_tag }})

| File | Download |
|------|----------|
| `{{ firmware_image_file }}` | [Image (.xz)]({{ firmware_release_base }}/{{ firmware_image_file }}) |
| `{{ firmware_image_file }}.asc` | [OpenPGP signature]({{ firmware_release_base }}/{{ firmware_image_file }}.asc) |
| `SHA256SUMS` | [Checksums]({{ firmware_release_base }}/SHA256SUMS) |
| `SHA256SUMS.asc` | [Signed checksums]({{ firmware_release_base }}/SHA256SUMS.asc) |

Machine-readable manifest:
[`releases/releases.json`](https://github.com/mohrt/PiWalletSV/blob/main/releases/releases.json)
in the source repo.

## Verify before you flash

The signing device's whole security claim is “keys never leave the device.”
That claim collapses if the firmware running on the device is not the one
we built. **Verify the signature before you flash.**

```bash
# One-time: import the release key (fingerprint in docs/security.md).
gpg --keyserver hkps://keys.openpgp.org --recv-keys 9E048B6E7F54C49DE2D5AEB5DA261F4F2B0CA281

# Verify the image.
gpg --verify {{ firmware_image_file }}.asc \
    {{ firmware_image_file }}

# Cross-check the SHA-256.
shasum -a 256 {{ firmware_image_file }}
```

A successful verification ends with **“Good signature”** and the release-key
fingerprint pinned in [`docs/security.md`](security.md#release-key).
**Do not flash an unverified image.**

## Flash the image

!!! tip "Step-by-step flashing"
    [Flash and first run § Flash the image](build-image.md#step-2-flash-the-image)
    covers Windows, macOS, and Linux (Raspberry Pi Imager or `dd`).

You need a **USB microSD reader/writer** on your computer. PiWalletSV kits
include a microSD and SD adapter when a full kit is offered; **they do not
include a USB reader.**

## Next steps

Once the image is verified and flashed:

- **Full kit with factory-flashed card?** Before you fund, **strongly
  recommend re-flashing** from this download page —
  [User manual § Verify your SD card](user-manual.md#verify-sd-card-on-arrival).
- Follow [Flash and first run](build-image.md) for disclaimer, vault PIN,
  wallet creation, airgap check, and a TESTNET smoke test.
- Routine use: [User manual](user-manual.md) ([USB backup](user-manual.md#usb-backup),
  [Upgrade your device](user-manual.md#upgrade-your-device),
  [Airgap status](user-manual.md#airgap-status)).

## Building from source

Need a custom tree or no GitHub asset yet? Flash Raspberry Pi OS Lite
32-bit, run
[`deploy/provision-pi.sh`](https://github.com/mohrt/PiWalletSV/blob/main/deploy/provision-pi.sh),
and capture your own image — see
[Build & deploy](build.md) and the operator notes in
[`docs/includes/image-release-operator.md`](includes/image-release-operator.md).
