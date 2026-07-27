# Security briefing

This page is the canonical operator-facing trust model for PiWalletSV.
The companion app at [{{ companion_url|replace('https://', '') }}]({{ companion_url }}/)
links here from its first-load disclaimer, its terms-of-service modal,
and from the "Why is this safe?" affordances on the Send flow — there's
one source of truth instead of a copy embedded in the app bundle that
slowly drifts out of sync.

The complete disclosure / reporting policy lives in the project's
`SECURITY.md`, which is embedded verbatim at the bottom of this page.

## 1. The companion website is static

- **There is no server.** The companion is a stack of HTML, CSS and
  JavaScript files. Once your browser has downloaded them, everything
  runs locally.
- **Nothing about your wallet is sent back to the site.** No login,
  no telemetry, no analytics, no "sync" anywhere. Paired-wallet
  metadata (xpub, fingerprint, label, derivation path, cached UTXO
  snapshots) lives in your browser's `IndexedDB` (prefs in
  `localStorage`). That list is an **ephemeral watch-only cache**, not
  custody — the browser can delete it at any time.
- **The only outbound calls** the companion makes are to two
  public blockchain APIs — neither receives anything private:
    - [WhatsOnChain](https://whatsonchain.com/) for UTXO discovery,
      Merkle proofs, fee rate recommendations, and broadcasting
      signed transactions.
    - [Bitails](https://bitails.io) for transaction history (the
      History tab fetches per-address tx history with satoshi
      deltas inline).
  Both services see only public data: BSV addresses, transaction
  IDs, and raw transaction hex. They never see your seed, PIN,
  or private keys.
- **Losing the browser profile is not a loss of funds.** The companion
  only holds *public* material; spending still requires the Pi (and
  ultimately your seed phrase). Prefer **Chrome** or **Firefox** on
  mobile. **Safari** (Intelligent Tracking Prevention) can delete all
  script-writable site data — including IndexedDB and localStorage —
  after about **seven days of Safari use** with no click, tap, or
  keyboard interaction on the companion site. That is not the same as
  closing a tab, but it often feels sudden. Clearing history or
  “Prevent Cross-Site Tracking” can also wipe the list.
- **Restore is easy.** Re-pair from the Pi (Show pairing QR / re-import
  the xpub), or migrate from another companion via **Settings → Export /
  Import** (QR or JSON). Prefer installing the companion to the Home
  Screen; standalone Home Screen apps are largely exempt from Safari’s
  seven-day ITP timer.

## 2. The PIN protects an encrypted vault, not magic

- The Pi's vault file (`~/.piwallet/vault.bin`) is AES-GCM encrypted.
  The key is derived from your PIN with
  [scrypt](https://en.wikipedia.org/wiki/Scrypt), which is
  intentionally slow and memory-hard. That makes offline guessing
  expensive — but it is **not impossible**.
- **The vault PIN is 6 digits.** Treat it as a barrier against casual
  access to the encrypted file on the device, not as a substitute for
  your seed phrase backup.
- **Six wrong PIN attempts in a row wipe the vault** from the Pi. This
  is a circuit breaker, not a guarantee: if someone copies
  `vault.bin` off the device they can retry forever offline. Your
  seed phrase backup is what protects you in that scenario.
- **USB backup sticks hold the same encrypted vault file** as the SD
  card. Treat a stick like a second copy of `vault.bin`: store it
  offline. Anyone with the stick **and** your vault PIN can sign.
  See [User manual § USB backup](user-manual.md#usb-backup).
- **The seed itself is never persisted.** It only exists in transient
  memory long enough to derive the master xprv and is then zeroed.

## 3. Treat the device like the seed phrase itself

- **Keep the Pi in a vault, not a desk drawer.** Anyone with extended
  physical access can copy the encrypted vault file and attack it
  offline at their leisure. There is no secure element, no tamper
  mesh, no anti-rollback fuse. It is a Raspberry Pi.
- **PiWalletSV is for cold storage, not daily transactions.** It is
  designed for long-term, infrequent signing of larger amounts. If
  you need to move funds every day, use a hot wallet on a phone or
  laptop and keep PiWalletSV for the savings stack.
- **Your seed phrase is the source of truth, not the Pi.** Back it up
  on something durable (steel plates, multiple geographic locations)
  and store it the way you would store the deed to a house. Losing
  the Pi is annoying; losing the seed is permanent. If the device is
  unavailable, you can still recover funds with any BIP44-compatible
  BSV tool (same BIP39 mnemonic, path `m/44'/236'/0'`) — see
  [Recover without device](recover-without-device.md)
  ([iancoleman.io/bip39](https://iancoleman.io/bip39/),
  [satofinder.com](https://satofinder.com), ElectrumSV, and others).
- **Air-gap discipline still applies.** Don't plug the Pi into the
  internet, don't type the seed into anything online, and don't let
  cameras or screen-recorders see the disclaimer-revealed phrase
  during initial setup or recovery. Verify the device is still quiet
  with **Settings → Maintenance → Airgap status** on the bonnet; see
  [User manual § Airgap status](user-manual.md#airgap-status) for
  what each indicator means.

## Seed generation { #seed-generation }

Seed phrases are created **only on the Pi** (bonnet UI or
`piwallet mnemonic new`). The companion app never generates mnemonics.

When you create a wallet on the bonnet you pick one of three entropy
sources:

| Source | What happens |
|--------|----------------|
| **Random (recommended)** | `secrets.token_bytes` draws 128 bits (12 words) or 256 bits (24 words) from the OS CSPRNG (`getrandom(2)` on Linux, mixing hardware RNG when available). |
| **Photo + random** | A full-resolution camera JPEG is hashed together with fresh OS random bytes. The preview stream on the TFT is **not** used for entropy. |
| **Dice + random** | At least 48 die faces (12 words) or 96 (24 words) are recorded, then hashed together with fresh OS random bytes. |

Photo and dice paths **augment** OS random — they never replace it.
Even a static photo or predictable dice sequence still yields a phrase
whose collision resistance is lower-bounded by the CSPRNG-only path.

**Collision math:** a 12-word BIP39 phrase encodes 128 bits of
entropy. Two independently generated phrases collide with probability
about **2⁻¹²⁸ ≈ 3×10⁻³⁹**. You would need on the order of 2⁶⁴ wallets
before birthday-paradox collisions become plausible. 24-word phrases
use 256 bits — astronomically safer still.

**Operator guidance:** use **Random** unless you have a reason to mix
in physical entropy. If you choose photo or dice, still capture a varied
scene or a long, honestly random roll sequence — that adds defense in
depth and per-user uniqueness on top of the OS random that always
participates.

The seed is shown once on the bonnet, confirmed via a shuffled word
picker (which uses `secrets.SystemRandom` only for UI decoys, not for
phrase generation), encrypted into the vault, and zeroed from memory.
It is never written to disk in cleartext.

## Address verification { #address-verification }

The companion app is a browser-based watch-only wallet. That means it
derives and displays your receive addresses using only your public key —
no private key ever leaves the Pi. This is by design and safe, but it
introduces one specific risk worth understanding:

**A compromised browser, extension, or network could substitute a
different address in the companion's UI without your knowledge.** If you
share that address with a sender, the funds go to whoever controls the
substituted address — not to your Pi wallet.

This is not unique to PiWalletSV; it applies to every software wallet
and web app that shows you a receive address. The conventional mitigation
is a hardware wallet with a trusted display, which shows the address on a
screen that the computer cannot influence.

PiWalletSV provides the same protection: **the Pi's bonnet is that
trusted display.** Before sharing a receive address, you can confirm it
independently on the bonnet:

1. On the Pi, navigate to the wallet and choose **Show deposit address**.
2. The bonnet starts at **address #0**. Press **RIGHT** (or **A**) once
   for each index step — e.g. press RIGHT 3 times to reach **address #3**.
3. Confirm the address shown on the bonnet matches what the companion
   app is showing you.

If they match, you can be confident the companion has not been tampered
with. If they don't match, do not share the address and investigate
before proceeding.

**This verification step is optional for low-value amounts or testnet
use.** For mainnet amounts you care about, treat it the same way you
would verify an address on a Ledger or Trezor — do it before sharing.

## Release key

Every PiWalletSV image artifact is signed with a single OpenPGP release
key and published on
[GitHub Releases](https://github.com/mohrt/PiWalletSV/releases).
Pin the fingerprint here so a substituted website cannot lie about it.

| Field | Value |
|-------|-------|
| Fingerprint | `9E04 8B6E 7F54 C49D E2D5  AEB5  DA26  1F4F  2B0C  A281` |
| User ID | `Monte Ohrt <monte@ohrt.com>` |
| Keyserver | `hkps://keys.openpgp.org` |

**Do not flash an image whose signature you cannot verify against the
fingerprint listed here.** A failed verification is the boundary between
a sealed appliance and a compromised one; treat it as a stop-the-world signal.

If you need to verify a download manually:

```bash
gpg --keyserver hkps://keys.openpgp.org --recv-keys 9E048B6E7F54C49DE2D5AEB5DA261F4F2B0CA281
gpg --verify piwalletsv-<VERSION>.img.xz.asc piwalletsv-<VERSION>.img.xz
```

Import the fingerprint from the **Release key** table on this page (or from
`keys.openpgp.org`) before verifying. Filenames and checksums for each
release come from
[GitHub Releases](https://github.com/mohrt/PiWalletSV/releases) — not from
this site.

Current releases are signed on the build host with the software key listed
here. A hardware keystore (YubiKey or OpenPGP card) is the long-term target
for production releases.

## Verify a pre-flashed SD card

Kits ship with a pre-flashed card that has been booted for factory
diagnostics and hardware tests. That testing changes card contents, so
the shipped card cannot byte-match the pristine release image or be
validated against its whole-image checksum. The checksum still verifies
the downloadable release file.

Before you fund the device:

- **Re-flash a verified image** (recommended) — download, GPG-verify,
  checksum, and flash the card yourself. Easiest real assurance.
- **Light checks** (optional) — Image ID on the **kit insert** vs the
  matching [GitHub release](https://github.com/mohrt/PiWalletSV/releases)
  (paperwork only). Accepting the tested card as shipped
  relies on the factory and delivery chain; there is no on-device
  verification of the full card.

Full steps: [User manual § Verify your SD card on arrival](user-manual.md#verify-sd-card-on-arrival).

## Reporting a vulnerability

Found a security-relevant bug? Please report it privately first — the
disclosure process is documented at the bottom of this page (the
embedded `SECURITY.md`).

---

## `SECURITY.md` (embedded)

--8<-- "SECURITY.md"
