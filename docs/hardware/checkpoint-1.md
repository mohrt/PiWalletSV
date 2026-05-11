# Hardware test checkpoint #1: bonnet boot path

**Goal.** Verify the disclaimer -> PIN unlock -> wallet list -> wallet detail
loop on the real Pi Zero 2 WH + 1.3" 240x240 TFT bonnet (Adafruit 4506).

This is the first end-to-end hardware test of the bonnet UI stack.
Everything below is exercised by 258 host-side tests, but only the Pi
can prove that:

- the ST7789 driver actually paints the framebuffer,
- the joystick and A/B buttons map to the expected logical buttons,
- the long-press LONG event fires at the right point,
- segno renders a scannable QR for a real address.

!!! note "SSH target placeholders"
    Replace `<user>@<host>` and `<repo-path>` below with the SSH
    target and remote checkout path for your device. The runbook
    doesn't depend on any specific hostname.

## 1. Prep the Pi

A working Raspberry Pi OS Lite (Bookworm or later, 64-bit) on an SD
card, with SSH + the standard Bookworm Python 3.11+ stack. SPI must
be enabled (`sudo raspi-config nonint do_spi 0`).

```sh
ssh <user>@<host>
sudo apt update
sudo apt install -y python3-venv python3-dev \
    rpicam-apps python3-picamera2 python3-libcamera \
    libzbar0t64

# Enable SPI (bonnet) and reboot.
sudo raspi-config nonint do_spi 0
sudo reboot
```

After it comes back, sanity-check that the kernel sees both peripherals:

```sh
ls /dev/spidev0.*                 # expect /dev/spidev0.0 and /dev/spidev0.1
rpicam-hello --list-cameras       # expect e.g. "imx708" listed
```

!!! note "libcamera tool rename on Trixie"
    On Pi OS Trixie the libcamera CLI tools were renamed:
    `libcamera-hello` -> `rpicam-hello`, `libcamera-still` ->
    `rpicam-still`, etc. The Python `picamera2` API is unchanged.

## 2. Push the code

From your workstation:

```sh
rsync -av --delete \
    --exclude .venv --exclude node_modules --exclude '__pycache__' \
    --exclude companion --exclude site --exclude _site \
    ./ <user>@<host>:<repo-path>/
```

The `companion/` PWA isn't needed for the bonnet test, so it's
excluded to keep the transfer small.

## 3. Install on the Pi

```sh
ssh <user>@<host>
cd <repo-path>
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e '.[display,camera]'
```

The `[display]` extra pulls in `adafruit-blinka` and
`adafruit-circuitpython-rgb-display`, which are the ST7789 driver
plus the GPIO HAL.

## 4. Seed a vault (one-time)

The bonnet boot loop expects a vault to already exist. From the SSH
session, create one with a known PIN and add a single wallet:

```sh
.venv/bin/piwallet vault init
# enter PIN (e.g. 123456) twice

.venv/bin/piwallet mnemonic new --words 12 > /tmp/m.txt
.venv/bin/piwallet wallet add --label daily < /tmp/m.txt
shred -u /tmp/m.txt
```

(Or use an existing vault you've already set up.)

The vault lives at `~/.piwallet-dev/vault.bin` by default; the
disclaimer state lives at `~/.piwallet-dev/terms.json`. Wiping
that directory resets the device to a "first boot" state.

## 5. Run the bonnet

```sh
.venv/bin/piwallet bonnet
```

The display should:

1. Show the **alpha-software disclaimer** page 1, with a blue
   accent border and a single highlighted page-indicator dot.
2. Advance to pages 2 and 3 when you push the joystick right.
3. Show a red-bordered "No liability" final page, with a
   "HOLD A to accept" footer.
4. When you hold A for ~700 ms, fill a small red bar at the
   bottom of the modal; on release-after-completion the disclaimer
   exits with `accepted v1` recorded in
   `~/.piwallet-dev/terms.json`.
5. Show the **Enter PIN** screen with 6 empty cells.
6. UP/DOWN cycles the active cell digit; LEFT/RIGHT moves
   between cells; A confirms.
7. After confirming the correct PIN, show the **Wallets** list
   with the wallet you added in step 4. UP/DOWN navigates;
   A drills in.
8. The **wallet detail** screen shows a crisp QR code for the
   m/0/0 receive address plus the address text in two lines.
   LEFT/RIGHT step the receive index; A advances.
9. Single-press B returns to the wallet list. Long-press B from
   either screen exits the bonnet app (back to the shell).

## 6. Things to write down

- Are colors correct? (Disclaimer accent should be blue;
  danger / final page should be red; wallet list cursor
  highlight should be a muted blue.)
- Does the QR scan with a phone camera from ~10 cm away?
- Any visible tearing or flicker? (If yes, tune SPI baudrate
  in `piwallet/ui/display.py::ST7789Display`.)
- Joystick / buttons all register? (If a direction never
  fires, double-check the BCM pin map in
  `piwallet/ui/input.py::BonnetInputBackend._PINS`.)
- LONG-press timing comfortable? (Bumpable via
  `piwallet/ui/app.py::make_input_manager(long_ms=...)`.)

## 7. Known gaps surfaced here

The screens below are explicit TODOs:

- Word entry (BIP39 mnemonic create / restore on the bonnet).
- Two-tier vault format upgrade.
- Scan-proposal / display-signed-tx flow on the bonnet
  (currently CLI-only).

If anything in the checklist above misbehaves, the per-screen
fixes live next to the screen code:

- Disclaimer: `piwallet/firstboot/disclaimer.py`
- PIN entry: `piwallet/ui/pin_entry.py`
- Unlock screen: `piwallet/bonnet/unlock.py`
- Wallet list: `piwallet/bonnet/wallet_list.py`
- Wallet detail: `piwallet/bonnet/wallet_detail.py`
- Boot loop: `piwallet/bonnet/app.py`
- Display driver: `piwallet/ui/display.py`
- Input backend: `piwallet/ui/input.py`
