# Getting started

This chapter walks you from "the parts arrived" to "I can sign a
transaction in a CLI smoke test." For the user-facing journey
(pairing, sending, receiving) see the [User manual](user-manual.md).

## What you need

PiWalletSV runs on two devices. Pick your device's tab; every tab on the
page follows.

=== "Zero"

    - A **Raspberry Pi Zero / Zero W / Zero WH**. Prefer
      **Zero W** or **Zero WH** — the W has the wireless module the
      enclosure design assumes; the H has the pre-soldered header the
      bonnet plugs into. **Pi Zero 2 W is not yet supported OOTB.**
    - An **Adafruit 1.3" 240×240 TFT bonnet** ([product 4506](https://www.adafruit.com/product/4506)) —
      ST7789-class panel with a joystick and A/B buttons.
    - An **ArduCam OV5647** camera module (kit camera) plus the ribbon
      cable adapter for the Pi Zero CSI connector.
    - A **5 V power supply** with a micro-USB connector that plugs into
      the bonnet's **PWR IN** port (the one farthest from the SD slot).
    - Raspberry Pi OS Lite **32-bit**.

=== "Pro"

    - A **Raspberry Pi 3 Model B**.
    - A **Waveshare 3.5 inch LCD (F)** — ST7796S panel, 320×480, with a
      GT911 capacitive touch controller.
    - An **ArduCam OV5647** camera module (kit camera) and ribbon cable.
    - A **5 V, 2.5 A power supply** with a micro-USB connector for the
      Pi's power port.
    - Raspberry Pi OS Lite **64-bit** (Trixie).

- A **microSD card** (8 GB is enough; 16 GB is more comfortable).
- A **phone, tablet, or laptop** with a camera, to run the
  companion web app. Prefer **Chrome** or **Firefox** on mobile —
  companion wallets are an ephemeral IndexedDB cache. Safari’s ITP can
  purge that storage after ~7 days of idle Safari use. Re-import the
  xpub from the Pi, or migrate via companion **Settings → Export /
  Import** — funds are unaffected.

## Bring up the screen

=== "Zero"

    The bonnet hardware setup is its own multi-step process — SPI
    buffer tuning, the dual-stack Adafruit driver situation, and so on.
    Rather than duplicate it here, read the canonical guide in
    [`GETTING_STARTED.md`](https://github.com/mohrt/PiWalletSV/blob/main/GETTING_STARTED.md)
    at the project root, which walks through:

    1. Flashing Raspberry Pi OS Lite (Bookworm) with `raspi-imager`.
    2. Enabling SPI, installing PIL / NumPy, raising the `spidev` kernel
       buffer to 131072 (the default 4096 is the cause of the
       classic "good half / garbage half" symptom).
    3. Setting up a Python virtualenv with Blinka and the
       CircuitPython RGB display driver.
    4. Re-assigning the SPI chip-select pins via
       `raspi-spi-reassign.py --ce0 disabled --ce1 disabled`.
    5. Running the `scripts/rgb_display_pillow_bonnet_buttons.py` demo
       to confirm the panel and joystick work.

    When the bonnet shows the demo's "Hello World" frame and the
    buttons cycle the picture, the hardware side is ready.

=== "Pro"

    The Pro panel is a kernel framebuffer, so there is no SPI buffer
    tuning or Blinka. The provisioner sets it up: it writes the
    `mipi-dbi-spi` (ST7796S) and `goodix` (touch) lines to
    `/boot/firmware/config.txt`, installs the `st7796s.bin` panel init
    firmware, and leaves `dtoverlay=vc4-kms-v3d` in place for the
    camera. On a fresh 64-bit Raspberry Pi OS Lite card:

    ```bash
    cd ~/PiWallet
    sudo bash deploy/provision-pi.sh --product pro --src "$(pwd)" \
        --keep-ssh --keep-radios
    sudo reboot
    ```

    `--keep-ssh --keep-radios` keeps SSH and Wi-Fi for development. Never
    use them for an image you hand to anyone. After the reboot,
    `piwallet-touch.service` draws the UI on the LCD; check it with the
    HDMI cable unplugged. See
    [Image release (operator)](https://github.com/mohrt/PiWalletSV/blob/main/docs/includes/image-release-operator.md) for
    the sealed build.

## Wire up the camera

=== "Zero"

    Add the kit camera overlay to `/boot/firmware/config.txt`:

    ```bash
    sudo tee -a /boot/firmware/config.txt <<'EOF'
    camera_auto_detect=0
    dtoverlay=ov5647
    EOF
    sudo reboot
    ```

    Install the libcamera stack and QR decoder:

    ```bash
    sudo apt install -y python3-picamera2 libzbar0t64
    source ~/.venvs/piwallet/bin/activate
    pip install pyzbar
    ```

=== "Pro"

    The provisioner already enables the camera (`camera_auto_detect=1`
    with `vc4-kms-v3d`) and installs the libcamera stack and QR decoder.
    Connect the ribbon to the Pi 3's CSI port, between the HDMI and
    audio jacks.

Smoke test:

```bash
rpicam-hello -t 2000          # confirms the CSI cable is seated
python scripts/camera_qr_test.py /tmp/cap.jpg
```

The script grabs a frame, runs `pyzbar` against it, and prints the
decoded text. If `rpicam-hello` shows live preview and
`camera_qr_test.py` decodes a real QR code from your phone, the
camera is ready.

DIY builders using a different libcamera-supported sensor must install
the matching `dtoverlay` and apt packages — see
[Supported cameras](build.md#7-supported-cameras-libcamera) in the build guide.

## Install the offline core

On a **laptop** (offline protocol development):

```bash
git clone https://github.com/mohrt/PiWalletSV.git
cd PiWalletSV
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

On a **Pi Zero** with the bonnet already working, sync the repo
and run the bootstrap script (apt, boot config, venv, pip — including
the armv6l `coincurve` workaround). On the **Pro**, the
`provision-pi.sh --product pro` run above has already built the venv
under `/opt/piwallet`.

```bash
cd ~/PiWallet
bash scripts/bootstrap-pi-dev.sh
```

See [Build & deploy — Bootstrap the Pi](build.md#3-bootstrap-the-pi-recommended)
for rsync excludes and platform notes.

You should see 150-ish tests pass on a laptop. The `[dev]` extra pulls in
`pytest`, `pytest-cov`, and `ruff`. Pi-side display/camera deps install
via `bootstrap-pi-dev.sh` or `install-piwallet-deps.sh`.

The CLI is installed as `piwallet`. Run `piwallet --help` to see
the top-level commands: `mnemonic`, `vault`, `xpub-export`,
`decode`, `sign`, `qr`.

## Install the companion PWA

The companion is a Vite + vanilla-TypeScript PWA in `companion/`.
Any device with a modern browser can run it; for development it
hosts on `https://localhost:5173/`.

```bash
cd companion
npm install
npm test            # 80-ish Vitest tests
npm run dev         # serves on https://localhost:5173/  AND  https://<lan-ip>:5173/
```

When you visit the URL, the first-load disclaimer modal pops up.
Tick the box and click **Continue**. The state machine is described
in the [Architecture](architecture.md#7-first-load-disclaimer)
chapter; `localStorage` keeps the acknowledgement until the version
bumps.

The PWA serves over HTTPS by default with a throwaway self-signed
certificate (see [`@vitejs/plugin-basic-ssl`](https://www.npmjs.com/package/@vitejs/plugin-basic-ssl))
because `getUserMedia` (camera access) requires a secure origin.
On iOS Safari you'll see a "This Connection Is Not Private" warning
the first time — click **Show Details → visit this website**.
After that the camera permission can be requested. To skip the
warning entirely, use [`mkcert`](https://github.com/FiloSottile/mkcert)
to generate a trusted certificate and wire it into `vite.config.ts`.

`PIWALLET_HTTP=1 npm run dev` disables HTTPS for plain
localhost work.

## Sanity-check end to end

The fastest way to confirm both halves agree is the round-trip page:

1. Open `https://localhost:5173/#/loop` in your browser.
2. Wait a second. The page builds one of each envelope kind,
   encodes it through CBOR + gzip + PW1 multipart, then assembles
   it back and asserts byte-equality.

Every row should be green. If any row is red, the wire stack has
drifted; check the version of the `companion/` build matches the
Python repo and rerun the test suites.

For an actual end-to-end signing demo (without the on-device UI),
follow the [User manual](user-manual.md). For the deepest test of
the SPV stack, run the canonical fixture through the CLI:

```bash
python -m tests.fixtures.generate_fixtures
piwallet decode tests/fixtures/proposal_01.cbor
```

The first command rebuilds the fixture; the second prints a
human-readable summary of its contents (inputs, outputs, fees,
anchors). The Python suite already exercises a full `verify` +
`sign` round-trip against it.

## Next steps

- :material-account-tie: [User manual](user-manual.md) — pairing,
  send, receive, broadcast.
- :material-shape: [Architecture](architecture.md) — what the two
  halves actually do, what they trust, and what they verify.
- :material-code-tags: [Develop](develop.md) — repo layout,
  testing matrix, fixture tools, release checklist.
