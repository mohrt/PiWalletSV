# Operator guide — build, capture, sign, and publish an SD image

This page is for **you** (the project operator), not kit buyers. Customers
flash from [Download](../download.md) on GitHub Releases.

## Target

- **Hardware:** Raspberry Pi **Zero W / Zero WH** + Adafruit **4506** bonnet + **OV5647**
- **OS base:** Raspberry Pi OS **Lite 32-bit** (Bookworm or Trixie)
- **Provisioner:** [`deploy/provision-pi.sh`](https://github.com/mohrt/PiWalletSV/blob/main/deploy/provision-pi.sh)
- **Published image:** ≤ 8 GiB uncompressed (fits 8 GB microSD; burns to larger cards too)
- **Version tag:** `0.1.0-r3` → Git tag `v0.1.0-r3`

## Payload rules (dev and production)

Every Pi tree — dev checkout (`~/PiWallet`) and sealed install (`/opt/piwallet`)
— must contain **only** the runtime firmware:

| Included | Excluded |
|----------|----------|
| `piwallet/`, `scripts/`, `deploy/`, `pyproject.toml` | `companion/`, `hardware/`, `docs/`, `tests/`, `releases/`, `site/`, dev caches, local vault state |

Canonical allowlist:
[`scripts/rsync-pi-includes.txt`](https://github.com/mohrt/PiWalletSV/blob/main/scripts/rsync-pi-includes.txt)
(copied by [`scripts/rsync-pi-payload.sh`](https://github.com/mohrt/PiWalletSV/blob/main/scripts/rsync-pi-payload.sh)).
Forbidden-path checks:
[`scripts/rsync-pi-excludes.txt`](https://github.com/mohrt/PiWalletSV/blob/main/scripts/rsync-pi-excludes.txt)

| Step | Tool | What it does |
|------|------|----------------|
| Workstation → Pi | [`scripts/sync-to-pi.sh`](https://github.com/mohrt/PiWalletSV/blob/main/scripts/sync-to-pi.sh) | `rsync` with excludes + `verify-pi-payload.sh` on the Pi |
| `--src` → `/opt/piwallet` | [`deploy/provision-pi.sh`](https://github.com/mohrt/PiWalletSV/blob/main/deploy/provision-pi.sh) | Same excludes + verify before venv install |
| Git clone fallback | `provision-pi.sh` | `prune-pi-payload.sh` then verify |

**Never** raw `rsync` the whole repo — use `sync-to-pi.sh` or
`scripts/rsync-pi-payload.sh` (allowlist).
**Never** provision from a tree that still contains `docs/`, `tests/`, or `companion/`.

## 1. Build the sealed root filesystem

### 1a. Flash a builder SD card

Raspberry Pi Imager → **Pi OS Lite 32-bit** → hostname, user, Wi‑Fi, SSH key.

### 1b. Sync source to the Pi (workstation)

From your Mac at a **known commit**:

```bash
./scripts/sync-to-pi.sh pi@piwallet-builder.local
# adds --bootstrap to run bootstrap-pi-dev.sh after verify
```

This rsyncs with excludes and runs `verify-pi-payload.sh` on the Pi before
you proceed.

### 1c. Builder provision (keep SSH + radios)

On the Pi:

```bash
cd ~/PiWallet
sudo deploy/provision-pi.sh \
  --src "$(pwd)" \
  --release-version 0.1.0-r3 \
  --image-channel round1-zero-w \
  --keep-ssh --keep-radios
sudo reboot
```

`provision-pi.sh` rsyncs `~/PiWallet` → `/opt/piwallet` with the **same**
exclude file, runs `verify-pi-payload.sh`, then builds the venv and seals
everything except SSH/radios.

### 1d. Factory QA

After reboot:

```bash
sudo bash /opt/piwallet/scripts/factory-smoke-test.sh --serial BUILD-001
```

### 1e. Seal the shipping image

Re-flash a **fresh** SD (or wipe and re-provision) **without** builder flags:

```bash
# sync again if needed, then on the Pi:
sudo deploy/provision-pi.sh \
  --src ~/PiWallet \
  --release-version 0.1.0-r3 \
  --image-channel round1-zero-w
sudo reboot
# Bonnet shows disclaimer on tty1; no SSH; radios off.
# Provision scrubs Imager Wi-Fi/network files; ~/PiWallet dev copy removed
# (runtime is /opt/piwallet only); login user kept for console.
```

Note **Image ID** from `/etc/piwalletsv-release` (or
`/opt/piwallet/RELEASE.json`) for kit insert printing.

## 2. Capture the image (workstation)

Power off the Pi. Insert the SD into **your** reader on Mac/Linux:

```bash
# macOS — replace rdiskN with the raw whole-disk device
diskutil unmountDisk /dev/diskN
sudo dd if=/dev/rdiskN of=piwalletsv-0.1.0-r3.img bs=4m conv=sync,noerror status=progress
```

Capture to an uncompressed `.img` first (not straight to `.xz`) so the shrink
step can resize partitions.

## 2b. Shrink for 8 GB compatibility

```bash
chmod +x scripts/shrink-sd-image.sh
./scripts/shrink-sd-image.sh piwalletsv-0.1.0-r3.img
# Replaces input in-place with a shrunk copy (or use -o other.img)

xz -T0 piwalletsv-0.1.0-r3.img
xz -l piwalletsv-0.1.0-r3.img.xz    # uncompressed must be ≤ ~8 GiB
```

On **macOS**, the shrink script runs PiShrink inside Docker (`--privileged`).
On **Linux**, install PiShrink natively or set `PISHRINK=/path/to/pishrink`.

## 2c. Checksum and sign

```bash
shasum -a 256 piwalletsv-0.1.0-r3.img.xz | tee SHA256SUMS
gpg --armor --detach-sign piwalletsv-0.1.0-r3.img.xz
gpg --armor --detach-sign SHA256SUMS
```

## 3. Publish GitHub Release

1. Tag the source commit: `git tag -s v0.1.0-r3 -m "Pi Zero W alpha r3 image"`
2. Create a [GitHub Release](https://github.com/mohrt/PiWalletSV/releases) `v0.1.0-r3`
3. Upload: `.img.xz`, `.img.xz.asc`, `SHA256SUMS`, `SHA256SUMS.asc`
4. Update [`docs/security.md`](../security.md#release-key) with the release-key fingerprint
5. Update [`releases/releases.json`](../../releases/releases.json) `sha256` field after upload

Both **piwalletsv.com** and **dev.piwalletsv.com** link to the same GitHub
asset URLs (see mkdocs `firmware_release_base` in `mkdocs.yml`).

## 4. Factory burn (full kits)

For each kit microSD (after the GitHub release is live):

1. Flash `piwalletsv-0.1.0-r3.img.xz` with Raspberry Pi Imager (**Use custom**)
2. Optional spot-check: boot once, run smoke test, then re-flash if you booted
3. Ship with **SD adapter** (customer uses **their own** USB reader to re-flash)
4. Print kit insert with **Firmware version** + **Image ID** matching the release

Tell every full-kit buyer: **re-flash from GitHub before funding** —
see [Verify your SD card](../user-manual.md#verify-sd-card-on-arrival).

## Dev vs production summary

| | Dev (`sync-to-pi.sh`) | Production (`provision-pi.sh`) |
|--|----------------------|-------------------------------|
| Destination | `~/PiWallet` | `/opt/piwallet` |
| Excludes | `rsync-pi-includes.txt` + `rsync-pi-payload.sh` | same allowlist |
| Verify | `verify-pi-payload.sh` after rsync | after rsync/prune, before pip |
| SSH / Wi‑Fi | unchanged | off unless `--keep-ssh` / `--keep-radios` |
| User | your login | `pwsv` (locked, no shell) + Imager login for console (e.g. `pisv`) |
