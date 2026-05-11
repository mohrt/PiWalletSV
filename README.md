# PiWalletSV

Air-gapped **Bitcoin SV** wallet targeting **Raspberry Pi Zero 2 WH** + **Adafruit 1.3" TFT bonnet** (joystick + buttons) + **Pi Camera Module 3**. Signing is performed entirely offline; a companion PWA on your phone or laptop handles all on-chain work.

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
npm run dev          # https://localhost:5173/  +  https://<lan-ip>:5173/
npm test             # vitest: round-trip vs tests/fixtures/proposal_01.cbor
npm run build        # tsc --noEmit + vite build to companion/dist
```

- **`/#/encode`** — paste any text / hex / base64(url) and watch it animate as `PW1|…` QR frames the Pi camera path can already ingest.
- **`/#/scan`** — `getUserMedia` + `jsqr` + `MultipartAssembler` reassembles a PW1 stream and shows it as text / hex / base64url, with `.bin` download. When the bytes are a real PiWalletSV envelope (`xpub_export`, `unsigned_proposal`, or `signed_tx`), the parsed structure is rendered inline. When an `xpub_export` is detected, a "Save as paired wallet" card appears that writes `{label, xpub, fingerprint, path, addedAt}` to IndexedDB.
- **`/#/wallets`** — paired-wallet list backed by IndexedDB. Rename, copy xpub, or remove an entry. The Pi side is unaffected by removals.
- **`/#/loop`** — runs an in-memory round-trip of every envelope kind (build → CBOR + gzip → PW1 split → reassemble → gunzip + CBOR decode) on page load and shows pass/fail. One-page sanity check that the wire stack agrees with itself.

### Pi-side pairing

To produce an `xpub_export` envelope on the Pi for pairing:

```bash
piwallet xpub-export --wallet-id <id> -o /tmp/xpub.bin   # writes CBOR + gzip blob
piwallet decode /tmp/xpub.bin                            # human-readable preview
```

For now you can render the blob to animated QR on a laptop (Encode page, base64url mode) and scan from the phone; once Phase 2 lands, the Pi bonnet itself will drive the PW1 stream.

### iPhone / phone scanning

`getUserMedia` is only exposed over a secure origin, so `npm run dev` serves HTTPS by default with a throwaway self-signed cert (via `@vitejs/plugin-basic-ssl`).

1. Connect your phone to the same Wi-Fi.
2. Open the **Network** URL Vite logs (e.g. `https://192.168.x.y:5173/`).
3. iOS Safari → "This Connection Is Not Private" → **Show Details** → **visit this website** → **Visit Website**. After that the Scan tab can request the camera.
4. To skip the warning entirely, generate a real-looking cert with [`mkcert`](https://github.com/FiloSottile/mkcert), install its root CA on the phone, and wire the cert files into `vite.config.ts` (`server.https = { key, cert }`).

Set `PIWALLET_HTTP=1 npm run dev` to disable HTTPS for plain localhost work.
