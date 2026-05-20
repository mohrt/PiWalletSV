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
  snapshots) lives in your browser's `IndexedDB` and stays there.
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
  ultimately your seed phrase).

## 2. The PIN protects an encrypted vault, not magic

- The Pi's vault file (`~/.piwallet/vault.bin`) is AES-GCM encrypted.
  The key is derived from your PIN with
  [scrypt](https://en.wikipedia.org/wiki/Scrypt), which is
  intentionally slow and memory-hard. That makes brute-forcing a long
  PIN very expensive — but it is **not impossible**.
- **PIN length matters.** A 6-digit PIN has only a million
  combinations; a determined attacker with the vault file and a GPU
  farm can chew through that. Use a long PIN — ideally 12+ digits —
  if you treat your seed as a high-value secret.
- **Six wrong PIN attempts in a row wipe the vault** from the Pi. This
  is a circuit breaker, not a guarantee: if someone copies
  `vault.bin` off the device they can retry forever offline. Your
  seed phrase backup is what protects you in that scenario.
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
  the Pi is annoying; losing the seed is permanent.
- **Air-gap discipline still applies.** Don't plug the Pi into the
  internet, don't type the seed into anything online, and don't let
  cameras or screen-recorders see the disclaimer-revealed phrase
  during initial setup or recovery.

## Release key

Every PiWalletSV image artifact published from the
[Download](download.md) page is signed with a single OpenPGP release
key. Pin the fingerprint here so a substituted website can't lie
about it.

| Field | Value |
|-------|-------|
| Fingerprint | `<RELEASE_KEY_FINGERPRINT>` (published with the first signed alpha release) |
| User ID | `PiWalletSV releases <releases@piwalletsv.com>` |
| Keyserver | `hkps://keys.openpgp.org` |

Until the first signed release ships, this fingerprint is a
placeholder. **Do not flash an image whose signature you cannot
verify against the fingerprint listed here.** A failed verification
is the boundary between a sealed appliance and a compromised one;
treat it as a stop-the-world signal.

If you need to verify a download manually:

```bash
gpg --keyserver hkps://keys.openpgp.org --recv-keys <RELEASE_KEY_FINGERPRINT>
gpg --verify piwalletsv-<VERSION>.img.xz.asc piwalletsv-<VERSION>.img.xz
```

The release key is held in a hardware keystore (Yubikey, OpenPGP
applet) that never touches a networked machine; new releases are
signed by physically presenting the key on a build host whose only
network exit is the upload to `download.piwalletsv.com`.

## Reporting a vulnerability

Found a security-relevant bug? Please report it privately first — the
disclosure process is documented at the bottom of this page (the
embedded `SECURITY.md`).

---

## `SECURITY.md` (embedded)

--8<-- "SECURITY.md"
