# Operator guide — build, capture, sign, and publish an SD image

This page is for **you** (the project operator), not kit buyers. Customers
flash from [Download](../download.md) on GitHub Releases.

## Target

- **Hardware:** Raspberry Pi **Zero W / Zero WH** + Adafruit **4506** bonnet + **OV5647**
- **OS base:** Raspberry Pi OS **Lite 32-bit** (Bookworm or Trixie)
- **Provisioner:** [`deploy/provision-pi.sh`](../../deploy/provision-pi.sh)
- **Version tag:** `0.1.0-r1` → Git tag `v0.1.0-r1`

## 1. Build the sealed root filesystem

On a Pi with network (builder card — **not** the image you ship yet):

```bash
# Sync a known commit to the Pi, then:
cd /path/to/PiWallet
sudo deploy/provision-pi.sh \
  --src "$(pwd)" \
  --release-version 0.1.0-r1 \
  --image-channel round1-zero-w \
  --keep-ssh --keep-radios   # builder only
sudo reboot
```

After reboot, run factory QA:

```bash
sudo bash /opt/piwallet/scripts/factory-smoke-test.sh --serial BUILD-001
```

When happy, **re-flash a fresh SD** (or wipe and re-provision) **without**
`--keep-ssh` or `--keep-radios` to produce the sealed appliance:

```bash
sudo deploy/provision-pi.sh \
  --src /path/to/PiWallet \
  --release-version 0.1.0-r1 \
  --image-channel round1-zero-w
sudo reboot
# Bonnet should show disclaimer on tty1; no SSH.
```

Note **Image ID** from `/etc/piwalletsv-release` (or
`/opt/piwallet/RELEASE.json`) for kit insert printing.

## 2. Capture the image (workstation)

Power off the Pi. Insert the SD into **your** reader on Mac/Linux:

```bash
# macOS example — replace rdiskN with the raw SD device
sudo dd if=/dev/rdiskN bs=4m conv=sync,noerror status=progress \
  | xz -T0 > piwalletsv-0.1.0-r1.img.xz

shasum -a 256 piwalletsv-0.1.0-r1.img.xz | tee SHA256SUMS
gpg --armor --detach-sign piwalletsv-0.1.0-r1.img.xz
gpg --armor --detach-sign SHA256SUMS
```

## 3. Publish GitHub Release

1. Tag the source commit: `git tag -s v0.1.0-r1 -m "Pi Zero W round-one image"`
2. Create a [GitHub Release](https://github.com/mohrt/PiWalletSV/releases) `v0.1.0-r1`
3. Upload: `.img.xz`, `.img.xz.asc`, `SHA256SUMS`, `SHA256SUMS.asc`
4. Update [`docs/security.md`](../security.md#release-key) with the release-key fingerprint
5. Update [`releases/releases.json`](../../releases/releases.json) `sha256` field after upload

Both **piwalletsv.com** and **dev.piwalletsv.com** link to the same GitHub
asset URLs (see mkdocs `firmware_release_base` in `mkdocs.yml`).

## 4. Factory burn (full kits)

For each kit microSD (after the GitHub release is live):

1. Flash `piwalletsv-0.1.0-r1.img.xz` with Raspberry Pi Imager (**Use custom**)
2. Optional spot-check: boot once, run smoke test, then re-flash if you booted
3. Ship with **SD adapter** (customer uses **their own** USB reader to re-flash)
4. Print kit insert with **Firmware version** + **Image ID** matching the release

Tell every full-kit buyer: **re-flash from GitHub before funding** —
see [Verify your SD card](../user-manual.md#verify-sd-card-on-arrival).
