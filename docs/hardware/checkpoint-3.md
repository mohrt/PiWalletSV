# Hardware test checkpoint #3: full companion round-trip on testnet

**Goal.** Prove the bonnet + companion PWA pair correctly, derive a
working watch-only address, fund it from a TBSV faucet, and produce a
broadcast-ready signed transaction. After this checkpoint passes, the
two-device protocol is end-to-end real on testnet — the only thing
mainnet adds is that the coins have a price tag.

Everything below is exercised by 511 Python tests + 104 companion
tests, but only the round-trip on real hardware can prove that:

- The pairing multipart-QR animation reassembles cleanly under the
  Pi camera (xpub envelope round-trip including the new `net` field).
- The companion's per-wallet WoC base URL actually points at testnet
  WhatsOnChain when the wallet was created with `network=test`.
- The "TESTNET" badge fires consistently in three places (wallets list
  row, wallet detail header, scan page pair card).
- A testnet P2PKH receive address scans, accepts faucet TBSV, and the
  resulting UTXO appears in the companion within a sane number of
  poll cycles.
- A signed proposal produced on the bonnet broadcasts on the WoC
  testnet endpoint and the txid matches what the bonnet displayed.

!!! note "SSH target placeholders"
    Replace `<user>@<host>` and `<repo-path>` with the SSH target and
    remote checkout path for your device. `<mac-ip>` is the LAN
    address of the dev machine the companion is served from.

## 0. Prereqs

- Bonnet boot loop already passing checkpoint #1 / #2 on this device.
- A phone (iOS Safari or Android Chrome) on the same Wi-Fi as the dev
  machine.
- A workstation that can serve the companion PWA over HTTPS reachable
  by the phone — the repo's `vite dev` does this out of the box via
  `@vitejs/plugin-basic-ssl`. Self-signed cert; tap-through-on-first-load
  is fine.
- TBSV in your pocket — a faucet such as
  [scrypt.io faucet](https://scrypt.io/faucet) or
  [test.bitails.io faucet](https://test.bitails.io) works for v1.

## 1. Push the new code

From the dev machine:

```sh
./scripts/sync-to-pi.sh <user>@<host> --path <repo-path>
```

Excludes and post-sync verification are defined in
[`scripts/rsync-pi-excludes.txt`](https://github.com/mohrt/PiWalletSV/blob/main/scripts/rsync-pi-excludes.txt)
(drops `site/`, `companion/`, `docs/`, `tests/`, dev caches, vault state, …).

On the Pi:

```sh
ssh <user>@<host>
cd <repo-path>
bash scripts/install-piwallet-deps.sh
sudo systemctl restart piwallet-bonnet  # or kill & relaunch interactive
```

## 2. Serve the companion PWA from the dev machine

```sh
cd <repo-path>/companion
npm install            # first run only
npm run dev
```

`vite dev` listens on `0.0.0.0:5173` over HTTPS by default. Note the
LAN address it prints (e.g. `https://192.168.1.50:5173`).

On the phone:

1. Open that URL.
2. Accept the self-signed cert warning ("Show details" → "visit
   anyway" / "Advanced" → "Proceed").
3. Accept the beta disclaimer modal.
4. You should land on the Wallets page with an empty list.

## 3. Create a testnet wallet on the bonnet

From the wallet list:

1. Joystick `DOWN` to `+ New wallet`. Press `A`.
2. Pick **12 words** (faster than 24 for a round-trip test).
3. **NEW SCREEN: Pick a network.** Press `DOWN` to highlight
   `Testnet (TBSV)`, then press `A`. Footer should warn
   `Testnet has no real value`.
4. HD path: accept the BSV preset (`m/44'/236'/0'`) by pressing `A`.
5. Entropy source: pick `Use the Pi's RNG (CSR)` and press `A`.
6. Page through the 12 displayed words and write them down — these
   are your only recovery if the device wipes.
7. Confirm the phrase via the shuffled-pick screens.
8. Accept the default label `wallet-1`.
9. The bonnet shows the green `Wallet saved` modal and drops back to
   the wallet list.

Drill into the wallet (`A`) and pick **Wallet info**. The screen
must show:

- `Network: TESTNET` (capitalised — that's the operator-readable
  shout-out for the no-real-money case).
- `HD path: m/44'/236'/0'`
- A 4-byte fingerprint and a creation date.

## 4. Pair the bonnet to the companion

From the wallet management menu, pick **Show xpub** (or **Pair with
companion**, depending on your menu wording — both run
`piwallet.bonnet.companion_pairing`).

The bonnet renders a multipart-QR animation containing the
`xpub_export` envelope, now including `net: "test"`.

On the phone:

1. Tap **Scan** in the companion's bottom nav.
2. Grant camera permission. Hold the phone roughly 8–15 cm from the
   bonnet's panel.
3. The frame counter at the bottom of the scan screen should
   advance as parts arrive. When all parts are received, the page
   flips to a **Pair card** showing:
    - Wallet label (`wallet-1`).
    - Fingerprint (first 4 bytes hex).
    - HD path (`m/44'/236'/0'`).
    - **`TESTNET` badge** rendered in red/orange next to the label.
4. Tap **Pair this wallet**. The companion writes a record to
   IndexedDB and bounces you back to the Wallets tab.
5. The Wallets list now shows `wallet-1` with a `TESTNET` badge
   beside the label.

If the **TESTNET badge is missing**, the round-trip failed silently:
either the bonnet didn't include `net: "test"` in the envelope, or
the companion's `parseXpub` defaulted it back to `"main"`. Check the
bonnet's pairing payload by re-running with `PIWALLET_LOG_LEVEL=DEBUG`
and grepping the journal.

## 5. Receive TBSV from a faucet

Tap the wallet row to open the detail page. The header should show:

- `wallet-1` with the TESTNET badge.
- `BSV testnet` in the metadata line (compare with the wording for a
  mainnet wallet — it should read `BSV mainnet` there).

The first receive address (`m/44'/236'/0'/0/0`) is rendered as a QR
plus the bech32-style fallback string. Copy/paste the address into a
TBSV faucet and request a small amount (≤ 0.1 TBSV is enough — the
faucets cap requests anyway).

Within ~30s of broadcast (testnet is fast), the companion should:

- Pull the new UTXO from `https://api.whatsonchain.com/v1/bsv/test`.
- Update the balance line on the wallet detail page.
- Surface a `Send` button.

If the balance never moves: confirm the WoC client really points at
the testnet base. In DevTools → Network, the requests should hit
`api.whatsonchain.com/v1/bsv/test/...`, not
`api.whatsonchain.com/v1/bsv/main/...`. If they hit the mainnet
path, the network field didn't propagate from IndexedDB — see
[Known gaps](#known-gaps) below.

## 6. Build a proposal on the companion

1. Tap **Send**. Enter a recipient address — easiest is to spin up a
   second testnet wallet on the bonnet (repeat §3) and use *its*
   first receive address. That way both ends are observable from
   the same dev machine.
2. Enter an amount well below the faucet drip (e.g. 1000 sats).
3. Tap **Build proposal**. The companion:
    - Picks UTXOs.
    - Fetches BEEF proofs from WoC.
    - Renders a multipart QR for the bonnet to scan.

## 7. Sign on the bonnet

From the bonnet wallet management menu, pick **Scan proposal**.

The Pi camera captures the companion's animated QR until the proposal
envelope is fully reassembled. The verifier:

1. Re-derives change addresses **using the wallet's own network** (the
   feature that landed in commit `421bd9b` / testnet 3-of-6).
2. Verifies the BEEF proofs.
3. Shows a `Confirm send` summary: recipient, amount, fee.

Press `A` to sign. The bonnet renders a multipart QR of the signed
transaction.

## 8. Broadcast from the companion

On the phone, the **Scan signed tx** flow takes the QR and:

1. Decodes the signed envelope.
2. POSTs to the WoC testnet broadcast endpoint
   (`api.whatsonchain.com/v1/bsv/test/tx/raw`).
3. Shows a `Broadcast OK` card with a clickable link to the testnet
   block explorer.

Click the link. The transaction should appear on
`test.whatsonchain.com/tx/<txid>` within a few seconds. Compare the
txid against what the bonnet displayed at the end of the sign flow —
they must be identical.

## 9. Confirm round-trip closure

- Recipient wallet on the bonnet (the second testnet wallet from §6,
  if you went that route) eventually shows the new UTXO via the
  companion's polling loop.
- The originating wallet's balance drops by `amount + fee`.
- A reboot (`sudo reboot`) preserves both wallets and their network
  fields. After reboot the companion still routes their requests to
  the testnet WoC base.

When all of the above pass, mark checkpoint #3 done in your hardware
notes and the testnet support series is confirmed end-to-end.

## Known gaps

- The companion does not (yet) expose a "switch this wallet's network"
  knob. By design — once paired, a wallet's network is fixed. To
  change it, delete the pairing and re-pair from a freshly created
  bonnet wallet on the desired network.
- The faucet round-trip depends on a working internet connection from
  the phone. The Pi remains air-gapped throughout — only the phone
  ever talks to the network.
- Mainnet round-trip is **not** part of this checkpoint. Once testnet
  is confirmed, repeat §3-§8 with `network=main` and a *small* real
  amount of BSV before you call mainnet ready for production use.

## Per-screen fix points

If something looks off:

- Network chooser screen (text, footer, default cursor): edit
  `piwallet/bonnet/network_chooser.py`.
- Wallet info "Network" row formatting: edit
  `piwallet/bonnet/wallet_info.py::WalletInfoScreen._format_network`.
- Companion TESTNET badge styling: `companion/src/app/styles.css`
  → `.testnet-badge`.
- Per-wallet WoC base URL selection: `companion/src/lib/woc.ts`
  → `wocBaseForNetwork`.
- Per-wallet P2PKH prefix: `companion/src/lib/derive.ts`
  → `prefixForNetwork`.
- Pi-side address rendering: `piwallet/core/derivation.py`
  → `_bsv_network`.

When this all works end-to-end on testnet, you have a real two-device
signer. Mainnet is one config flag away.
