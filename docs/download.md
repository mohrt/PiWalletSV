# Download

The fastest way to run PiWalletSV is to flash the prebuilt SD-card
image onto a microSD and boot. The image is a sealed appliance: it
boots straight into the bonnet UI, has no SSH or Wi-Fi, and runs the
PiWalletSV application as the only foreground task on the device.

!!! info "Image artifact in flight"

    The downloadable image artifact is currently being prepared. The
    URLs below will go live alongside the alpha release.
    Until then, you can produce the same image yourself by following
    [Build &amp; deploy](build.md) &mdash; the prebuilt image is exactly
    what `deploy/provision-pi.sh` produces.

## Files

| File | Purpose |
|------|---------|
| `piwalletsv-<VERSION>.img.xz` | The compressed SD-card image. Decompress and flash. |
| `piwalletsv-<VERSION>.img.xz.asc` | Detached PGP signature over the image. |
| `SHA256SUMS` | Plain-text checksum for double-checking after download. |
| `SHA256SUMS.asc` | PGP signature over the checksum file. |

All four files come from the same release URL on
`download.piwalletsv.com`. The release-key fingerprint and the
expected SHA-256 are pinned in
[`docs/security.md`](security.md#release-key) so a substituted
website can't lie about either.

## Verify before you flash

The signing device's whole security claim is &ldquo;keys never leave the
device.&rdquo; That claim collapses if the firmware running on the device
isn't the one we built. **Verify the signature before you flash.**

```bash
# One-time: import the release key.
gpg --keyserver hkps://keys.openpgp.org --recv-keys <RELEASE_KEY_FINGERPRINT>

# Verify the image.
gpg --verify piwalletsv-<VERSION>.img.xz.asc piwalletsv-<VERSION>.img.xz

# Cross-check the SHA-256.
shasum -a 256 piwalletsv-<VERSION>.img.xz
```

A successful verification ends with **&ldquo;Good signature&rdquo;** and the
release-key fingerprint. Anything else means the file has been
tampered with in transit, or someone has replaced the website.
**Do not flash an unverified image.**

## Flash the image

!!! tip "Jump straight to the flashing guide"
    The [Flash and first run](build-image.md#step-2-flash-the-image)
    page has step-by-step instructions for every platform:

    - **Windows** — Raspberry Pi Imager or balenaEtcher (GUI, no command line needed)
    - **macOS** — Raspberry Pi Imager via GUI or `brew`, or `dd` from the terminal
    - **Linux** — `dd` from the terminal, or Raspberry Pi Imager via `apt` / Flatpak

    Both recommended GUI tools handle `.img.xz` decompression
    automatically — no need to unzip the file first.

## Next steps

Once the image is verified and flashed:

- Follow [Flash and first run](build-image.md) for first-boot
  setup: disclaimer, PIN, wallet creation, airgap check, and a
  TESTNET smoke test.
- See the [User manual](user-manual.md) for routine use after the
  device is set up, including
  [Upgrade your device](user-manual.md#upgrade-your-device) and
  [Airgap status](user-manual.md#airgap-status).

## Building from source

If you'd rather build the image yourself &mdash; you'll need a Raspberry
Pi running Raspberry Pi OS Lite, a network connection during
provisioning, and the patience for a 10-minute scripted bring-up &mdash;
see [Build &amp; deploy](build.md). The build path produces a
bit-identical sealed image to the one published here, modulo the
date stamp baked into `/etc/piwalletsv-release`.
