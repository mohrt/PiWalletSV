# Pi bootstrap (dev / checkpoint)

Canonical bring-up for a **development** or **hardware-checkpoint** Pi.
Production sealed images use `deploy/provision-pi.sh` (same Python install
and bonnet-hardware helpers).

## What it does

`scripts/bootstrap-pi-dev.sh` on the Pi, after you sync the repo:

| Phase | Actions |
|-------|---------|
| **Packages** | picamera2, libzbar0t64, secp256k1/ffi dev libs, build tools, … |
| **Boot** | SPI + I2C, `spidev.bufsiz=131072`, OV5647 overlay |
| **User** | `spi`, `gpio`, `video`, `i2c`, `dialout` groups |
| **Python** | `.venv` with `--system-site-packages` + `install-piwallet-deps.sh` |
| **Bonnet** | Adafruit `raspi-blinka.py` + `raspi-spi-reassign.py` (via `setup-bonnet-hardware.sh`) |
| **Verify** | SPI nodes, camera, CLI import check |

Expect **1–3 reboots** on a fresh SD card (boot config → Blinka → SPI reassign).

## Workstation → Pi

From the repo root on your Mac/Linux machine:

```bash
./scripts/sync-to-pi.sh user@piwallet.local --bootstrap
```

Or manually:

```bash
./scripts/sync-to-pi.sh user@piwallet.local

ssh user@piwallet.local 'cd ~/PiWallet && bash scripts/bootstrap-pi-dev.sh'
```

Excludes are listed in [`scripts/rsync-pi-excludes.txt`](https://github.com/mohrt/PiWalletSV/blob/main/scripts/rsync-pi-excludes.txt)
(vault state, dev caches, companion PWA, docs site, hardware CAD, tests, …).
`sync-to-pi.sh` runs [`scripts/verify-pi-payload.sh`](https://github.com/mohrt/PiWalletSV/blob/main/scripts/verify-pi-payload.sh)
on the Pi after each sync; production `provision-pi.sh` runs the same check before pip.

**Include `scripts/`** in the sync. Do not exclude it.

After the first reboot:

```bash
ssh user@piwallet.local 'cd ~/PiWallet && bash scripts/bootstrap-pi-dev.sh --resume'
```

## Options

| Flag | Meaning |
|------|---------|
| `--resume` | Skip apt, boot config, venv — hardware + verify only |
| `--skip-apt` / `--skip-boot` / `--skip-venv` | Skip individual phases |
| `--skip-blinka` / `--skip-spi-reassign` | Skip bonnet hardware steps |
| `--no-reboot` | Print reboot reminder instead of rebooting |

State markers under `~/.cache/piwallet-bootstrap/`:

- `blinka.done` — `import board` works in the venv
- `spi-reassign.done` — CE0/CE1 disabled for bonnet SPI
- `complete.done` — full bootstrap verified

## Python install (`install-piwallet-deps.sh`)

Always use this on the Pi instead of bare `pip install -e ".[display,camera]"`.

On **Pi Zero WH (32-bit, armv6l)**, `bsv-sdk` pulls `coincurve>=21.0.0`, whose
sdist fails to build. The install script pins **`coincurve==20.0.0`** (piwheels
armv6 wheel) and installs `bsv-sdk` with `--no-deps`.

```bash
bash scripts/install-piwallet-deps.sh --create-venv
```

## Smoke tests (use venv wrappers)

Do **not** run bonnet scripts with system `python3` — Blinka lives in `.venv`.

```bash
cd ~/PiWallet
source .venv/bin/activate

./scripts/run_display_demo.sh          # bonnet panel + buttons
./scripts/run_camera_qr_test.sh --once # camera + QR
.venv/bin/piwallet vault init
./scripts/run_bonnet.sh                # full UI
```

## Platform matrix

| Board | OS | Notes |
|-------|-----|-------|
| **Pi Zero 2 WH** (recommended) | Pi OS Lite **64-bit** | Production target; normal pip on aarch64 |
| **Pi Zero WH** (budget / legacy) | Pi OS Lite **32-bit** | Works; slow pip; coincurve pin required |
| **Laptop** | macOS / Linux | `pip install -e ".[dev]"` only — no bootstrap |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `/dev/spidev0.0 does not exist` | Enable SPI, reboot: `sudo raspi-config nonint do_spi 0` |
| `ModuleNotFoundError: board` | Use `.venv/bin/python` or `source .venv/bin/activate` |
| `Permission denied` on scripts | Re-run bootstrap (chmod) or `bash scripts/...` |
| Garbled display bands | Confirm `cat /sys/module/spidev/parameters/bufsiz` → **131072** |
| `coincurve` metadata error on pip | Use `install-piwallet-deps.sh`, not bare `pip install -e` |

Manual SPI reassign marker (if you ran Adafruit scripts by hand):

```bash
mkdir -p ~/.cache/piwallet-bootstrap
date -Iseconds > ~/.cache/piwallet-bootstrap/spi-reassign.done
```
