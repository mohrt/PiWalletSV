# Operator guide — build, capture, sign, and publish an SD image

This page is for **you** (the project operator), not kit buyers. Customers
flash from [Download](../download.md) on GitHub Releases.

## Target

- **Hardware:** Raspberry Pi **Zero W / Zero WH** + Adafruit **4506** bonnet + **OV5647**
- **OS base:** Raspberry Pi OS **Lite 32-bit** (Bookworm or Trixie)
- **Provisioner:** [`deploy/provision-pi.sh`](../../deploy/provision-pi.sh)
- **Version tag:** `0.1.0-r1` → Git tag `v0.1.0-r1`

## Payload rules (dev and production)

Every Pi tree — dev checkout (`~/PiWallet`) and sealed install (`/opt/piwallet`)
— must contain **only** the runtime firmware:

| Included | Excluded |
|----------|----------|
| `piwallet/`, `scripts/`, `deploy/`, `pyproject.toml` | `companion/`, `hardware/`, `docs/`, `tests/`, `releases/`, `site/`, dev caches, local vault state |

Canonical exclude list:
[`scripts/rsync-pi-excludes.txt`](../../scripts/rsync-pi-excludes.txt)

| Step | Tool | What it does |
|------|------|----------------|
| Workstation → Pi | [`scripts/sync-to-pi.sh`](../../scripts/sync-to-pi.sh) | `rsync` with excludes + `verify-pi-payload.sh` on the Pi |
| `--src` → `/opt/piwallet` | [`deploy/provision-pi.sh`](../../deploy/provision-pi.sh) | Same excludes + verify before venv install |
| Git clone fallback | `provision-pi.sh` | `prune-pi-payload.sh` then verify |

**Never** raw `rsync` without `--exclude-from=scripts/rsync-pi-excludes.txt`.
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
  --release-version 0.1.0-r1 \
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
  --release-version 0.1.0-r1 \
  --image-channel round1-zero-w
sudo reboot
# Bonnet shows disclaimer on tty1; no SSH; radios off.
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

## Dev vs production summary

| | Dev (`sync-to-pi.sh`) | Production (`provision-pi.sh`) |
|--|----------------------|-------------------------------|
| Destination | `~/PiWallet` | `/opt/piwallet` |
| Excludes | `rsync-pi-excludes.txt` | same file |
| Verify | `verify-pi-payload.sh` after rsync | after rsync/prune, before pip |
| SSH / Wi‑Fi | unchanged | off unless `--keep-ssh` / `--keep-radios` |
| User | your login | `pwsv` (locked, no shell) |
