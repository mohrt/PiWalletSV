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

Use the bootstrap script — it installs apt packages, enables SPI/I2C,
sets the OV5647 overlay, creates the venv, and configures bonnet hardware:

```sh
# from workstation
./scripts/sync-to-pi.sh <user>@<host> --bootstrap

# or on the Pi after rsync:
cd <repo-path>
bash scripts/bootstrap-pi-dev.sh
bash scripts/bootstrap-pi-dev.sh --resume   # after reboot(s)
```

See [Build & deploy — Bootstrap](../build.md#3-bootstrap-the-pi-recommended)
and [bootstrap reference](../includes/bootstrap-pi-dev.md).

Sanity-check after bootstrap:

```sh
ls /dev/spidev0.*                 # expect /dev/spidev0.0 and /dev/spidev0.1
cat /sys/module/spidev/parameters/bufsiz   # 131072
rpicam-hello --list-cameras       # expect ov5647
./scripts/run_display_demo.sh     # bonnet panel + buttons
```

!!! note "Other libcamera sensors (DIY)"
    The libcamera stack supports other CSI sensors when the matching
    `dtoverlay` is set in `config.txt`. PiWalletSV v1 is tested with
    the kit **ArduCam OV5647** only. See
    [Supported cameras](../build.md#supported-cameras-libcamera) for
    common overlays if you bring your own camera.

!!! note "libcamera tool rename on Trixie"
    On Pi OS Trixie the libcamera CLI tools were renamed:
    `libcamera-hello` -> `rpicam-hello`, `libcamera-still` ->
    `rpicam-still`, etc. The Python `picamera2` API is unchanged.

## 2. Push the code

From your workstation (or use `sync-to-pi.sh` which rsyncs + bootstraps):

```sh
rsync -av --delete \
    --exclude .git --exclude .venv --exclude node_modules \
    --exclude '__pycache__' --exclude companion --exclude site \
    --exclude hardware \
    ./ <user>@<host>:<repo-path>/
```

The `companion/` PWA isn't needed for the bonnet test, so it's
excluded to keep the transfer small.

## 3. Install on the Pi

If you used `sync-to-pi.sh --bootstrap`, skip this section. Otherwise:

```sh
ssh <user>@<host>
cd <repo-path>
bash scripts/bootstrap-pi-dev.sh
```

To refresh Python deps after a code push:

```sh
bash scripts/install-piwallet-deps.sh
```

## 4. Seed a vault (one-time)

The bonnet boot loop handles first-boot vault creation on-screen — if no
vault exists it walks the operator through picking a PIN twice before
reaching the wallet list. To skip the on-screen setup and pre-seed a
vault from the CLI:

```sh
.venv/bin/piwallet vault init
# enter PIN (e.g. 123456) twice

.venv/bin/piwallet mnemonic new --words 12 > /tmp/m.txt
.venv/bin/piwallet vault add --label daily < /tmp/m.txt
shred -u /tmp/m.txt
```

(Or use an existing vault you've already set up.)

The vault lives at `~/.piwallet/vault.bin` by default; the
disclaimer state lives at `~/.piwallet/terms.json`. Wiping
that directory resets the device to a "first boot" state.

If the vault file becomes corrupt, use `piwallet vault recover` to
diagnose it and optionally rename the corrupt file and create a fresh
empty vault.

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
   `~/.piwallet/terms.json`.
5. Show the **Enter PIN** screen with 6 empty cells.
6. UP/DOWN cycles the active cell digit; LEFT/RIGHT moves
   between cells; A confirms.
7. After confirming the correct PIN, show the **Wallets** list
   with any pre-seeded wallets. UP/DOWN navigates; A drills in.
   The list also has **New wallet**, **Restore wallet**, and
   **Settings** rows.
8. The **New / Restore wallet** flows walk through: word count →
   network (mainnet/testnet) → HD path → entropy / word entry →
   label → success banner. After saving, the device offers to
   display the companion-pairing QR.
9. The **wallet detail** screen shows a crisp QR code for the
   m/0/0 receive address plus the address text in two lines.
   LEFT/RIGHT step the receive index; A advances.
10. Single-press **B** returns to the wallet list. Short **B** from the
    wallet list opens **Settings** (see `piwallet/ui/settings_screen.py`).
    Hold **B** for five seconds on the **boot splash** to open factory
    diagnostics (`piwallet/bonnet/splash.py`, `piwallet/bonnet/utility.py`).
    There is no UI gesture to exit the bonnet app — power off externally.

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
- **Top third random noise while the bottom looks fine?**
  Wrong ST7789 row offset. Adafruit bonnet **[4506](https://www.adafruit.com/product/4506)**
  needs ``y_offset=80`` — that is now the default in
  ``piwallet/ui/display.py::ST7789Display``. Sanity script tunable via
  ``scripts/bonnet_sanity.py --y-offset``.

## 7. Remaining gaps

The screens below are not yet wired into the bonnet UI:

- Scan-proposal / display-signed-tx flow (currently CLI-only via
  `piwallet sign` and `piwallet verify`).

If anything in the checklist above misbehaves, the per-screen
fixes live next to the screen code:

- Disclaimer: `piwallet/firstboot/disclaimer.py`
- PIN entry: `piwallet/ui/pin_entry.py`
- Unlock screen: `piwallet/bonnet/unlock.py`
- Wallet list: `piwallet/bonnet/wallet_list.py`
- Wallet detail: `piwallet/bonnet/wallet_detail.py`
- Create / restore flows: `piwallet/bonnet/create_wallet.py`, `piwallet/bonnet/restore_wallet.py`
- Companion pairing: `piwallet/bonnet/companion_pairing.py`
- Settings: `piwallet/ui/settings_screen.py`
- Boot loop: `piwallet/bonnet/app.py`
- Display driver: `piwallet/ui/display.py`
- Input backend: `piwallet/ui/input.py`
