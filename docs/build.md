# Build & deploy

How to take a stock Raspberry Pi Zero 2 WH from a freshly-flashed
SD card to a self-launching PiWalletSV signer. This chapter is
narrowly about the **Pi-side install**. Hardware bring-up (bonnet,
camera, SPI tuning) is in [Getting started](getting-started.md);
the user-facing journey is in the [User manual](user-manual.md).

If you only want to develop on a laptop, you don't need any of this —
`pip install -e ".[dev]"` and `pytest` is enough.

## 1. Decide what you're building

There are three sensible deployment shapes:

| Shape | What runs | Who it's for |
|-------|-----------|--------------|
| **Dev workstation** | core only, `pytest`, no display | Working on the protocol, fixtures, or PWA |
| **Bonnet kiosk**    | `piwallet bonnet` under systemd, autostart | Day-to-day signer, single-purpose Pi |
| **Headless CLI**    | `piwallet` from a shell over SSH | Initial vault setup, scripted backups, or running on a Pi without the bonnet |

This page covers the **bonnet kiosk** shape end to end. The other two
share most of the same install steps and end before the systemd
section.

## 2. Pick an OS image

- **Raspberry Pi OS Lite (64-bit, Bookworm or later)** is the tested
  baseline. The 32-bit image works but `picamera2` is much slower on
  it.
- **Pi OS Lite Trixie** is the newest tested target (used in
  [Hardware checkpoint #1](hardware/checkpoint-1.md)).
- Avoid Desktop images on a Pi Zero 2 W — the X server eats the RAM
  and SD-card lifetime that the signer wants for itself.

Flash the SD card with [`rpi-imager`](https://www.raspberrypi.com/software/),
not `dd`. The imager pre-seeds:

- the `pi` user with a password (or your SSH public key),
- Wi-Fi credentials,
- locale, timezone, hostname.

Set the **hostname** to something distinctive (`piwallet-1.local`).
Set the **timezone** correctly — the signer doesn't have a real-time
clock, and BEEF anchor verification compares header timestamps.

## 3. Bootstrap the Pi (recommended)

The checked-in bootstrap script replaces the manual apt/SPI/Blinka/pip
steps below. Run it **on the Pi** after syncing the repo from your
workstation.

--8<-- "docs/includes/bootstrap-pi-dev.md"

Sections 4–5 below are **reference only** if you need to debug individual
steps. For a new SD card, use the bootstrap script.

## 4. Manual reference: first boot housekeeping

Power on, SSH in, then (bootstrap does this automatically):

```bash
sudo apt update
sudo apt full-upgrade -y
```

## 5. Manual reference: SPI + kernel buffer

The bonnet uses SPI; the default `spidev` buffer (4 KB) is too small
for a 240×240 frame. Bootstrap sets `spidev.bufsiz=131072` on the kernel
cmdline and enables SPI/I2C in `config.txt`.

Verify after reboot:

```bash
ls -l /dev/spidev0.*
cat /sys/module/spidev/parameters/bufsiz   # 131072
```

Bonnet display also requires Adafruit Blinka + SPI CE reassign —
handled by `scripts/setup-bonnet-hardware.sh` (called from bootstrap).

(See [`GETTING_STARTED.md`](https://github.com/mohrt/PiWalletSV/blob/main/GETTING_STARTED.md)
for bonnet electrical details and the display-only demo.)

## 6. Sync the repo (if not using sync-to-pi.sh)

The signer code lives at a predictable path so `scripts/run_bonnet.sh`
and the systemd example unit work out of the box.

```bash
./scripts/sync-to-pi.sh pi@piwallet-1.local --bootstrap
```

Or rsync + bootstrap manually — see the include above.

`sync-to-pi.sh` and `provision-pi.sh --src` use the allowlist in
[`scripts/rsync-pi-includes.txt`](https://github.com/mohrt/PiWalletSV/blob/main/scripts/rsync-pi-includes.txt)
via [`scripts/rsync-pi-payload.sh`](https://github.com/mohrt/PiWalletSV/blob/main/scripts/rsync-pi-payload.sh).
Forbidden paths are checked with
[`scripts/rsync-pi-excludes.txt`](https://github.com/mohrt/PiWalletSV/blob/main/scripts/rsync-pi-excludes.txt).
and runs [`scripts/verify-pi-payload.sh`](https://github.com/mohrt/PiWalletSV/blob/main/scripts/verify-pi-payload.sh) on the Pi
after every sync. The same exclude list is enforced when
[`deploy/provision-pi.sh`](https://github.com/mohrt/PiWalletSV/blob/main/deploy/provision-pi.sh) installs to `/opt/piwallet`.

After bootstrap completes, smoke-test:

```bash
./scripts/run_display_demo.sh
./scripts/run_camera_qr_test.sh --once
piwallet --help
piwallet mnemonic new
```

If the bonnet hardware is wired correctly, the display demo shows a
coloured frame and the buttons cycle the picture.

## 7. Supported cameras (libcamera)

The sealed PiWalletSV image ships with the **ArduCam OV5647** (fixed
focus). That is the kit minimum and the only combination tested for v1.

| Sensor / module | Typical overlay | Notes |
|-----------------|-----------------|-------|
| **OV5647** (ArduCam kit) | `camera_auto_detect=1` (sealed image default) or `dtoverlay=ov5647` | Sealed images use auto-detect like a stock Pi OS SD. For no-EEPROM DIY modules, set `camera_auto_detect=0` and add `dtoverlay=ov5647` manually. |
| IMX219 (Pi Camera v2) | `dtoverlay=imx219` | Fixed focus. |
| IMX477 (HQ Camera) | `dtoverlay=imx477` | Fixed focus. |
| IMX708 (Pi Camera Module 3) | `dtoverlay=imx708` or `camera_auto_detect=1` | Autofocus sensor; hold at a consistent distance. |
| IMX296 (Global Shutter) | `dtoverlay=imx296` | Fixed focus. |

See Raspberry Pi's [camera documentation](https://www.raspberrypi.com/documentation/computers/camera.html)
for the full sensor list and wiring.

## 8. Pick a vault path

The encrypted vault is a single file. Pick a path that survives
reboots and is owned by the `pi` user. The convention used throughout
the docs and the systemd example is:

```
/home/pi/.piwallet/vault.bin
```

Create the directory and the empty vault:

```bash
mkdir -p ~/.piwallet
piwallet vault --vault-path ~/.piwallet/vault.bin init
```

`vault init` is interactive: it prompts for a PIN (4-12 digits),
confirms it, scrypt-derives a KEK, writes a fresh empty vault, and
exits. Re-running it is refused if the vault already exists — that's
intentional, see [Operate](operate.md#wiping-the-vault) for the wipe
procedure.

Add at least one wallet from a fresh mnemonic so the bonnet has
something to display:

```bash
piwallet mnemonic new | piwallet vault \
    --vault-path ~/.piwallet/vault.bin add --label "First wallet"
```

Save the mnemonic somewhere offline. The CLI does not store it — the
vault holds the encrypted xprv only. You'll need the mnemonic to
restore.

## 9. First-boot disclaimer state

The disclaimer acceptance lives in a plain JSON file (it's checked
*before* vault unlock so it can't be in the encrypted vault):

```bash
piwallet firstboot status                     # not accepted
piwallet firstboot run --headless             # accepts in CI/test mode
# or run on the bonnet itself:
piwallet firstboot run                        # interactive, hold-A to accept
```

Once `firstboot status` reports `accepted` for the current terms
version, the bonnet boot path will skip the disclaimer screen.

## 10. Run the bonnet manually

Verify the full boot path works under your user before wiring up
systemd:

```bash
./scripts/run_bonnet.sh --vault-path ~/.piwallet/vault.bin
```

You should see the disclaimer (only if not yet accepted), the PIN
entry screen, the wallet list, and the per-wallet manage menu.
`Ctrl-C` (or hold the bonnet's B button) exits. The display should go
dark on exit — if it doesn't, you've hit a bug; file it.

## 11. Wire up systemd for autostart

Copy the example unit and journald drop-in into place:

```bash
sudo cp deploy/systemd/piwallet-bonnet.service.example \
    /etc/systemd/system/piwallet-bonnet.service
sudo cp deploy/systemd/journald-piwallet.conf.example \
    /etc/systemd/journald.conf.d/piwallet.conf
```

Adjust `User=`, `WorkingDirectory=`, and `--vault-path` if your paths
differ from `/home/pi`. Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart systemd-journald
sudo systemctl enable --now piwallet-bonnet
sudo systemctl status piwallet-bonnet
```

What the unit does:

- `After=network-pre.target graphical.target` — wait for the basic
  boot graph; we don't need network (intentionally).
- `Conflicts=getty@tty1.service` — the bonnet doesn't compete with
  the console getty for the panel.
- `Restart=always` with `RestartSec=3` — if the bonnet exits with a
  non-zero code (vault wipe, missing vault, disclaimer declined),
  systemd brings it back with the disclaimer / unlock flow. See
  [Operate § Exit codes](operate.md#exit-codes) for what each code
  means and how to design around them.

The journald drop-in caps persistent journal size (32 MB) and rotates
files at 8 MB. This matters on small SD cards — without bounds the
journal can grow until the filesystem refuses writes.

### USB backup (production images)

Sealed SD-card images are built with `deploy/provision-pi.sh`, which
installs the USB mount stack automatically:

--8<-- "docs/includes/usb-backup-provisioning.md"

Dev installs that use `piwallet-bonnet.service.example` above do **not**
include this stack. Either run the `step_usb_backup` function from
`provision-pi.sh` on the Pi, or use the CLI with a manually mounted
stick ([CLI § `piwallet backup`](cli.md#piwallet-backup)).

## 12. Verify the kiosk

After enabling the unit:

1. Reboot the Pi: `sudo reboot`.
2. Wait ~30 seconds. The bonnet should display the disclaimer (if
   not already accepted) or the PIN entry screen.
3. From a workstation: `ssh pi@piwallet-1.local
   "journalctl -u piwallet-bonnet -n 50 --no-pager"` and confirm there
   are no tracebacks.
4. Power-cycle the Pi by pulling the cable. The bonnet should come
   back up to the same state.

If steps 2 or 3 fail, jump to [Operate § Troubleshooting](operate.md#troubleshooting).

## 13. Update procedure

Day-to-day updates are a `git pull` + venv refresh + service restart:

```bash
ssh pi@piwallet-1.local
cd /home/pi/PiWallet
git pull
source .venv/bin/activate
bash scripts/install-piwallet-deps.sh
sudo systemctl restart piwallet-bonnet
```

If the update changes a wire format (CBOR keys, PW1 framing, etc.)
you'll also need to update the companion PWA on whatever device you
pair with. The docs site and the [Protocol spec](protocol/README.md)
note any non-backwards-compatible changes per release.

## 14. What you didn't have to do

- **No Wi-Fi access points.** The signer has no inbound services and
  doesn't need to be on the same network as the companion.
- **No NTP daemon.** The signer doesn't accept inbound traffic and
  doesn't need a synchronised clock for verification — header
  anchors carry their own timestamps. (You still want a roughly-right
  RTC time for log readability; that's covered by the OS image's
  default `systemd-timesyncd`.)
- **No remote shell on the production unit.** SSH is convenient
  during install. For a hardened deploy, disable the SSH service
  after this chapter and rely on physical access for maintenance.
  See [Security](security.md) for the threat-model rationale.

## 15. Official SD image

The sealed image is built with
[`deploy/provision-pi.sh`](https://github.com/mohrt/PiWalletSV/blob/main/deploy/provision-pi.sh)
on **Raspberry Pi OS Lite 32-bit** (Pi Zero W / Zero WH), captured with `dd`,
shrunk with [`scripts/shrink-sd-image.sh`](https://github.com/mohrt/PiWalletSV/blob/main/scripts/shrink-sd-image.sh)
so it fits **8 GB** microSD cards, then compressed and signed. Signed `.img.xz`
artifacts are published on **GitHub Releases** — see [Download](download.md).

Operator workflow (sync → provision → capture → sign → publish):
[`docs/includes/image-release-operator.md`](includes/image-release-operator.md).
Dev and production share one payload manifest — never sync `companion/`, `docs/`,
`tests/`, or local vault state to the Pi.

Future work: `pi-gen` reproducible builds (`phase8-hardening`).
Until then, the manual provision + capture sequence above is canonical.
