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
./scripts/sync-to-pi.sh pisv@piwalletsv.local --prepare
```

This rsyncs with the allowlist, verifies the payload, applies Pi Zero W
HDMI/tty2 boot settings, and reboots the Pi.

After reboot: plug in HDMI + USB keyboard, press **Ctrl+Alt+F2** (Mac:
**Ctrl+Fn+Option+F2**), log in as `pisv`.

For dev sync only (no image build), omit `--prepare`:

```bash
./scripts/sync-to-pi.sh pi@piwallet-builder.local --bootstrap
```

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

After sync + `--prepare` (§1b), on **tty2** (not over SSH):

```bash
sudo bash ~/PiWallet/deploy/provision-pi.sh \
  --src ~/PiWallet \
  --local \
  --release-version 0.1.0-r3 \
  --image-channel round1-zero-w
sudo reboot
# Bonnet shows disclaimer on tty1; no SSH; radios off.
# --local forces inline radio purge even if SSH_CONNECTION is inherited on tty2.
```

Provision from a local console so radio packages purge inline (purging
over SSH can hang). Re-flash a **fresh** SD if you previously ran a
builder provision with `--keep-ssh --keep-radios` (§1c).

Note **Image ID** from `/etc/piwalletsv-release` (or
`/opt/piwallet/RELEASE.json`) for kit insert printing.

## 2. Capture, shrink, compress, and checksum (workstation)

Power off the Pi. Insert the SD into **your** reader on Mac/Linux, then run
the all-in-one script (capture → PiShrink → `xz` → `SHA256SUMS`):

```bash
# Beta (GitHub pre-release) — adds -beta to filename
./scripts/capture-sd-image.sh --version 0.1.0-r3 --maturity beta diskN

# Alpha (local only, never GitHub) — lands in images/alpha/
./scripts/capture-sd-image.sh --version 0.1.0-r3 --maturity alpha diskN

# GA / full release — no suffix (default)
./scripts/capture-sd-image.sh --version 1.0.0 diskN

# Already captured a raw .img? Skip dd:
./scripts/capture-sd-image.sh --version 0.1.0-r3 --maturity beta --from path/to/capture.img

# Add GPG detach-signatures for GitHub upload:
./scripts/capture-sd-image.sh --version 0.1.0-r3 --maturity beta diskN --sign
```

### Filename convention

Same firmware revision (`0.1.0-r3`) can produce multiple captures. Use
**maturity in the filename** on your workstation; use **Image ID** on the card
(`/etc/piwalletsv-release`) to tell builds apart.

| Maturity | Filename | GitHub? |
|----------|----------|---------|
| `alpha` | `piwalletsv-0.1.0-r3-alpha.img.xz` | Never — local QA only |
| `beta` | `piwalletsv-0.1.0-r3-beta.img.xz` | Pre-release / community beta |
| `release` | `piwalletsv-1.0.0.img.xz` | GA — no suffix |

Alpha builds skip `releases/SHA256SUMS` and `releases.json` updates.

Output lands in `images/` by default (`images/alpha/` for alpha):

| File | Purpose |
|------|---------|
| `piwalletsv-0.1.0-r3-beta.img.xz` | Published image (example beta name) |
| `images/SHA256SUMS` | **Single-line** checksum file — upload this to the GitHub Release |
| `releases/SHA256SUMS` | **Cumulative** checksums for all releases — committed to the repo |
| `releases/releases.json` | `sha256` field updated automatically for the built version |
| `*.asc` | Detached signatures (with `--sign`) |

Each GitHub Release gets its own `SHA256SUMS` asset with one line (that release's
`.img.xz` only). The repo-root `releases/SHA256SUMS` lists every published image
so older versions stay verifiable from source control.

The script captures to an uncompressed `.img` first (not straight to `.xz`) so
PiShrink can resize partitions, then removes the `.img` after `xz` unless you
pass `--keep-img`.

PiShrink uses **`-s`** by default (no first-flash filesystem expand, so no
automatic reboot after Imager write). The shrunk image already fits 8 GB cards.
Set ``PISHRINK_AUTOEXPAND=1`` when shrinking if you want larger cards to expand
on first boot (one reboot, slower UX).

**Baked into the captured image** (buyer's first boot should be fast):

| Done at provision (before `dd`) | Skipped on buyer first boot |
|--------------------------------|-----------------------------|
| Radio package purge inline (tty2 / `--local`) | No `apt purge` wait |
| cloud-init units masked | No cloud-init timeouts |
| Wi-Fi/BT firmware disabled + units masked | RF already off |
| Bonnet app + venv in `/opt/piwallet` | No install step |

If provision ran over SSH without `--local`, ``radio-purge.pending`` may still
be in the image → first boot runs ``apt purge`` (60–120 s, no reboot).

On **macOS**, shrink runs PiShrink inside Docker (`--privileged`). On **Linux**,
install PiShrink natively or set `PISHRINK=/path/to/pishrink`.

Individual steps (if you need them):

```bash
./scripts/shrink-sd-image.sh images/piwalletsv-0.1.0-r3.img
xz -f -T0 images/piwalletsv-0.1.0-r3.img
shasum -a 256 images/piwalletsv-0.1.0-r3.img.xz | tee images/SHA256SUMS
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
