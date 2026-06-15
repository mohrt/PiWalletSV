# PiWalletSV

> **Beta software — read [`DISCLAIMER.md`](DISCLAIMER.md) before use.**
> No warranty. Non-custodial: your funds are always recoverable from any
> BIP39-compatible wallet using your seed phrase; PiWalletSV is not required.
> Report security issues per [`SECURITY.md`](SECURITY.md).

Air-gapped **Bitcoin SV** wallet built on a **Raspberry Pi**, a **TFT bonnet** (joystick + buttons), and an **ArduCam OV5647** camera. Signing is performed entirely offline; a companion web app on your phone or laptop handles all on-chain work.

User-facing site: **[piwalletsv.com](https://piwalletsv.com/)** · Live wallet: **[app.piwalletsv.com](https://app.piwalletsv.com/)**

The wire format, QR transport, derivation rules, and SPV requirements are documented as an open spec in [`docs/protocol/`](docs/protocol/README.md) so any project can build a compatible companion (or a compatible signer) against PiWalletSV. Canonical test vectors live in [`tests/fixtures/`](tests/fixtures/).

## Offline core (dev / air-gapped signer)

Python 3.11+ (Python 3.14 is not yet supported by all transitive wheels; use 3.13 on macOS).

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

- **CLI:** `piwallet --help` — vault, sign, decode, multipart QR (`piwallet qr join`, `piwallet qr scan-camera` on Pi), USB backup (`piwallet backup export|import`).
- **Pi bring-up:** `./scripts/sync-to-pi.sh user@host --bootstrap` or `bash scripts/bootstrap-pi-dev.sh` on the Pi. Smoke tests: `./scripts/run_display_demo.sh`, `./scripts/run_bonnet.sh`. See [docs/build.md](docs/build.md).

## Companion web app

Vanilla TypeScript + Vite, in [`companion/`](companion/). The shared `PW1` multipart-QR module is byte-for-byte compatible with `piwallet.qr` on the Pi.

```bash
cd companion
npm install
npm run dev          # https://localhost:5173/  +  https://<lan-ip>:5173/
npm test             # vitest: round-trip vs tests/fixtures/proposal_01.cbor
npm run build        # tsc --noEmit + vite build to companion/dist
```

Routes:

- **`/#/wallets`** — paired-wallet list (IndexedDB). Rename, copy xpub, remove. Default landing surface; the Pi side is unaffected by removals.
- **`/#/wallets/<id>`** — wallet detail with **Balance**, **Send**, **Receive**, and **Recent addresses** sections. Balance does a gap-limit-20 UTXO scan via [WhatsOnChain](https://api.whatsonchain.com/v1/bsv/main) across `m/0/i` and `m/1/i`. Send runs greedy coin selection, fetches per-input TSC Merkle proofs + block headers, builds a BSV BEEF via `@bsv/sdk`, and emits an `unsigned_proposal` animated as PW1 frames. Receive derives `m/0/<index>` children, addresses computed via `@scure/bip32` + `@noble/hashes` and cross-checked against `piwallet.core.derivation` byte-for-byte.
- **`/#/scan`** — `getUserMedia` + `jsqr` + `MultipartAssembler` reassembles a PW1 stream. Recognises real envelopes (`xpub_export`, `unsigned_proposal`, `signed_tx`) and renders the right action card. `signed_tx` POSTs raw hex to WhatsOnChain `/tx/raw`, surfaces the returned txid + a `whatsonchain.com/tx/<txid>` link, and warns if the broadcaster echoes a different txid than the Pi signed.
- **`/#/loop`** *(dev only)* — round-trips every envelope kind (build → CBOR + gzip → PW1 split → reassemble → gunzip + CBOR decode) on page load. Tree-shaken out of production builds.

Cross-domain links (footer, "Why is this safe?", terms-modal pointers) are driven by `VITE_DOCS_BASE_URL` at build time so dev mirrors stay self-contained. See [`companion/.env`](companion/.env) and [`companion/src/lib/config.ts`](companion/src/lib/config.ts).

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

`piwallet decode /tmp/xpub.bin` prints the same human-readable summary the web app shows for sanity checks.

### iPhone / phone scanning

`getUserMedia` is only exposed over a secure origin, so `npm run dev` serves HTTPS by default with a throwaway self-signed cert (via `@vitejs/plugin-basic-ssl`).

1. Connect your phone to the same Wi-Fi.
2. Open the **Network** URL Vite logs (e.g. `https://192.168.x.y:5173/`).
3. iOS Safari → "This Connection Is Not Private" → **Show Details** → **visit this website** → **Visit Website**. After that the Scan tab can request the camera.
4. To skip the warning entirely, generate a real-looking cert with [`mkcert`](https://github.com/FiloSottile/mkcert), install its root CA on the phone, and wire the cert files into `vite.config.ts` (`server.https = { key, cert }`).

Set `PIWALLET_HTTP=1 npm run dev` to disable HTTPS for plain localhost work.

## Protocol spec & compatibility

PiWalletSV is designed so that anyone can build a compatible companion or signer against it. The full wire-format spec is in [`docs/protocol/`](docs/protocol/README.md):

- [`derivation.md`](docs/protocol/derivation.md) — BIP39/32/44 layout, P2PKH address encoding, wallet fingerprint.
- [`envelopes.md`](docs/protocol/envelopes.md) — CBOR + gzip shapes for `xpub_export`, `unsigned_proposal`, `signed_tx`.
- [`qr-transport.md`](docs/protocol/qr-transport.md) — the `PW1` multipart QR framing.
- [`spv.md`](docs/protocol/spv.md) — what a v1 signer verifies before producing signatures (BEEF + Merkle path + header anchors + change re-derivation + value conservation).
- [`conformance.md`](docs/protocol/conformance.md) — canonical test vectors in [`tests/fixtures/`](tests/fixtures/) you can diff your implementation against.

The reference Python signer in `piwallet/` and the reference TypeScript companion in `companion/` both validate themselves against these fixtures on every test run, so they cannot silently drift from the spec.
