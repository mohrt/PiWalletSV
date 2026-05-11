# PiWallet

Air-gapped **Bitcoin SV** wallet work targeting **Raspberry Pi Zero WH** + **Adafruit 1.3" TFT bonnet** (joystick + buttons).

## Offline core (dev / air-gapped signer)

Python 3.11+ (Python 3.14 is not yet supported by all transitive wheels; use 3.13 on macOS).

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

- **CLI:** `piwallet --help` — vault, sign, decode, multipart QR (`piwallet qr join`, `piwallet qr scan-camera` on Pi).
- **Pi camera path:** install `python3-picamera2` via apt, then in a venv use `pip install pyzbar` and `sudo apt install libzbar0t64`. See [GETTING_STARTED.md](GETTING_STARTED.md).

## Companion PWA (preview)

Vanilla TypeScript + Vite, in [`companion/`](companion/). The shared `PW1` multipart-QR module is byte-for-byte compatible with `piwallet.qr` on the Pi.

```bash
cd companion
npm install
npm run dev          # http://localhost:5173 (encoder live; scan page is a stub)
npm test             # vitest: round-trip vs tests/fixtures/proposal_01.cbor
npm run build        # tsc --noEmit + vite build to companion/dist
```

Use the encode page to paste any payload (text / hex / base64 / base64url) and watch it animate as `PW1|…` QR frames the Pi camera path can ingest.
