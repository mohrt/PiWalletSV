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

## 3. First boot housekeeping

Power on, SSH in (`ssh pi@piwallet-1.local`), then:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y \
    git python3-venv python3-pip \
    python3-picamera2 libzbar0t64 \
    libatlas-base-dev   # for numpy on the Pi
```

The `python3-picamera2` apt package matters: building Picamera2 from
PyPI on a Pi Zero 2 W takes >30 minutes and pulls in libcamera headers
that don't exist in pip world.

Reboot once after the upgrade so any kernel/firmware bumps land:

```bash
sudo reboot
```

## 4. Enable SPI + tune the kernel buffer

The bonnet uses SPI; the default `spidev` buffer (4 KB) is too small
for a 240×240 frame and produces the classic "good top half, garbage
bottom half" symptom. Raise it to 128 KB:

```bash
sudo raspi-config nonint do_spi 0    # enable SPI
echo 'spidev.bufsiz=131072' | sudo tee /boot/firmware/cmdline.append
# Append the same flag to /boot/firmware/cmdline.txt (single line):
sudo sed -i 's|$| spidev.bufsiz=131072|' /boot/firmware/cmdline.txt
```

Verify after reboot:

```bash
cat /sys/module/spidev/parameters/bufsiz
# 131072
```

Re-assign the SPI chip-select pins so the bonnet's CE0/CE1 don't
collide:

```bash
sudo /home/pi/PiWallet/scripts/raspi-spi-reassign.py \
    --ce0 disabled --ce1 disabled
sudo reboot
```

(See [`GETTING_STARTED.md`](https://github.com/example/piwallet/blob/main/GETTING_STARTED.md)
for the bonnet electrical details.)

## 5. Clone the repo and install the venv

The signer code lives in a single repo at a fixed path. Picking a
predictable path is what lets the systemd unit and the
`scripts/run_bonnet.sh` launcher be checked-in defaults.

```bash
cd /home/pi
git clone https://github.com/example/piwallet.git PiWallet
cd PiWallet

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -e ".[display,camera]"
```

The two extras matter:

- **`[display]`** pulls Adafruit Blinka + the CircuitPython RGB-display
  driver. Linux-only.
- **`[camera]`** is empty by default — the Pi camera dependencies
  (`picamera2`, `libcamera`) come from apt, not pip, because they
  bundle native libs. We keep the marker so future optional pip
  dependencies can land cleanly.

Smoke test:

```bash
piwallet --help
piwallet mnemonic new
```

If both work, the offline core is functional. If the bonnet hardware
is wired correctly, you can also run the Pillow + buttons demo:

```bash
python scripts/rgb_display_pillow_bonnet_buttons.py
```

You should see a coloured frame + see the joystick/buttons cycle the
picture.

## 6. Pick a vault path

The encrypted vault is a single file. Pick a path that survives
reboots and is owned by the `pi` user. The convention used throughout
the docs and the systemd example is:

```
/home/pi/.piwallet-dev/vault.bin
```

Create the directory and the empty vault:

```bash
mkdir -p ~/.piwallet-dev
piwallet vault --vault-path ~/.piwallet-dev/vault.bin init
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
    --vault-path ~/.piwallet-dev/vault.bin add --label "First wallet"
```

Save the mnemonic somewhere offline. The CLI does not store it — the
vault holds the encrypted xprv only. You'll need the mnemonic to
restore.

## 7. First-boot disclaimer state

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

## 8. Run the bonnet manually

Verify the full boot path works under your user before wiring up
systemd:

```bash
./scripts/run_bonnet.sh --vault-path ~/.piwallet-dev/vault.bin
```

You should see the disclaimer (only if not yet accepted), the PIN
entry screen, the wallet list, and the per-wallet manage menu.
`Ctrl-C` (or hold the bonnet's B button) exits. The display should go
dark on exit — if it doesn't, you've hit a bug; file it.

## 9. Wire up systemd for autostart

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

## 10. Verify the kiosk

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

## 11. Update procedure

Day-to-day updates are a `git pull` + venv refresh + service restart:

```bash
ssh pi@piwallet-1.local
cd /home/pi/PiWallet
git pull
source .venv/bin/activate
pip install -e ".[display,camera]"
sudo systemctl restart piwallet-bonnet
```

If the update changes a wire format (CBOR keys, PW1 framing, etc.)
you'll also need to update the companion PWA on whatever device you
pair with. The docs site and the [Protocol spec](protocol/README.md)
note any non-backwards-compatible changes per release.

## 12. What you didn't have to do

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

## 13. Reproducible image (planned)

A future v0.1 release will ship a `pi-gen`-built SD image with the
signer pre-installed and the vault directory pre-created, signed with
the project's PGP key. Tracking issue: `phase8-hardening`. Until that
lands, the manual sequence in this chapter is the canonical install.
