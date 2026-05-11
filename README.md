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
- **`/#/scan`** — `getUserMedia` + `jsqr` + `MultipartAssembler` reassembles a PW1 stream and shows it as text / hex / base64url, with `.bin` download. When the bytes are a real PiWalletSV envelope (`xpub_export`, `unsigned_proposal`, or `signed_tx`), the parsed structure is rendered inline.
  - **xpub_export** → a "Save as paired wallet" card writes `{label, xpub, fingerprint, path, addedAt}` to IndexedDB.
  - **signed_tx** → a "Broadcast signed transaction" card POSTs the Pi's raw hex to WhatsOnChain `/tx/raw`, surfaces the returned txid + a `whatsonchain.com/tx/<txid>` link, and warns if the broadcaster echoes a different txid than the Pi signed.
- **`/#/wallets`** — paired-wallet list backed by IndexedDB. Rename, copy xpub, or remove an entry. The Pi side is unaffected by removals.
- **`/#/wallets/<id>`** — wallet detail with four sections:
  - **Balance**: gap-limit (20) UTXO scan via [WhatsOnChain](https://api.whatsonchain.com/v1/bsv/main) across `m/0/i` and `m/1/i`. Shows total sats / BSV, UTXO count, scrollable UTXO table tagged with derivation. Snapshot is cached on the wallet record so re-opening the page is instant; the **Refresh balance** button re-scans.
  - **Send**: paste a recipient address + amount, click **Build proposal**. The companion runs greedy coin selection, fetches a TSC Merkle proof from `/tx/<txid>/proof/tsc` and the block header from `/block/<hash>/header` per input, builds a BSV BEEF via `@bsv/sdk`, derives the change address from `m/1/<lastChangeUsed + 1>`, and emits an `unsigned_proposal` envelope which is animated as PW1 frames for the Pi camera. Change is folded into the fee when below the 546-sat dust threshold.
  - **Receive**: derives `m/0/<index>` children of the paired xpub, shows the current address as text + QR (P2PKH base58check, BSV mainnet prefix `0x00`), with **Next address / Previous** stepping that persists `nextReceiveIndex` on the wallet record. Pure derivation via `@scure/bip32` + `@noble/hashes`, cross-checked against `piwallet.core.derivation` byte-for-byte (see `tests/fixtures/addresses_canonical.json`).
  - **Recent addresses**: a window of 8 around the current receive pointer.
- **`/#/loop`** — runs an in-memory round-trip of every envelope kind (build → CBOR + gzip → PW1 split → reassemble → gunzip + CBOR decode) on page load and shows pass/fail. One-page sanity check that the wire stack agrees with itself.

### Pi-side pairing demo

Until the bonnet display (Phase 2) drives QR rendering directly, you can pipe the envelope through `qrencode` and scan the terminal from the phone:

```bash
sudo apt install qrencode
piwallet xpub-export --wallet-id <id> -o /tmp/xpub.bin
piwallet qr split --chunk-chars 200 /tmp/xpub.bin |
    while IFS= read -r line; do
        clear
        qrencode -t UTF8 -- "$line"
        sleep 0.4
    done
```

Then on the phone, open `https://<pi-or-laptop-lan-ip>:5173/#/scan`, hit **Start camera**, and point it at the Pi terminal. When the assembler completes, the **Save as paired wallet** card appears; the wallet shows up under `/#/wallets`. The reverse direction (laptop/phone PW1 → Pi camera) already works via `piwallet qr scan-camera`.

`piwallet decode /tmp/xpub.bin` prints the same human-readable summary the PWA shows for sanity checks.

### iPhone / phone scanning

`getUserMedia` is only exposed over a secure origin, so `npm run dev` serves HTTPS by default with a throwaway self-signed cert (via `@vitejs/plugin-basic-ssl`).

1. Connect your phone to the same Wi-Fi.
2. Open the **Network** URL Vite logs (e.g. `https://192.168.x.y:5173/`).
3. iOS Safari → "This Connection Is Not Private" → **Show Details** → **visit this website** → **Visit Website**. After that the Scan tab can request the camera.
4. To skip the warning entirely, generate a real-looking cert with [`mkcert`](https://github.com/FiloSottile/mkcert), install its root CA on the phone, and wire the cert files into `vite.config.ts` (`server.https = { key, cert }`).

Set `PIWALLET_HTTP=1 npm run dev` to disable HTTPS for plain localhost work.
