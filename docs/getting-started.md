# Getting started

This chapter walks you from "the parts arrived" to "I can sign a
transaction in a CLI smoke test." For the user-facing journey
(pairing, sending, receiving) see the [User manual](user-manual.md).

## What you need

- A **Raspberry Pi Zero 2 WH** (the W has a wireless module the
  enclosure design assumes; the H has the pre-soldered header the
  bonnet plugs into).
- An **Adafruit 1.3" 240×240 TFT bonnet** ([product 4506](https://www.adafruit.com/product/4506)) —
  ST7789-class panel with a joystick and A/B buttons.
- An **ArduCam OV5647** camera module (kit camera) plus the ribbon
  cable adapter for the Pi Zero CSI connector.
- A **microSD card** (8 GB is enough; 16 GB is more comfortable).
- A **5 V power supply** with a micro-USB connector that plugs into
  the bonnet's **PWR IN** port (the one farthest from the SD slot).
- A **phone, tablet, or laptop** with a camera, to run the
  companion web app. Any modern browser (Chrome/Safari/Firefox) works.

## Bring up the bonnet

The bonnet hardware setup is its own multi-step process — SPI
buffer tuning, the dual-stack Adafruit driver situation, and so on.
Rather than duplicate it here, read the canonical guide in
[`GETTING_STARTED.md`](https://github.com/example/piwallet/blob/main/GETTING_STARTED.md)
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

## Wire up the camera

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
[Supported cameras](build.md#supported-cameras-libcamera) in the build guide.

## Install the offline core

On a **laptop** (offline protocol development):

```bash
git clone https://github.com/example/piwallet.git
cd piwallet
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

On a **Raspberry Pi** with the bonnet already working, sync the repo
and run the bootstrap script (apt, boot config, venv, pip — including
the armv6l `coincurve` workaround):

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

For an actual end-to-end signing demo (without the bonnet UI),
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
