# Security Policy

## Supported Versions

PiWalletSV is currently pre-release / alpha software. Only the `main`
branch and the latest tagged release receive security fixes. There is
no LTS commitment yet.

| Version           | Supported          |
| ----------------- | ------------------ |
| `main` (alpha)    | :white_check_mark: |
| any pre-`v0.1.0`  | :x:                |

## Reporting a Vulnerability

If you believe you have found a security-relevant issue in PiWalletSV
(any code in this repository, on the Pi signer, in the companion web
app, or in the documented operational procedures), please report it
**privately** before disclosing it publicly.

### Preferred channel

GitHub private vulnerability reporting:

1. Open `https://github.com/mohrt/PiWalletSV/security/advisories/new`.
2. Fill in a clear title, a reproduction, the impact, and what
   versions / configurations are affected.
3. We will respond on the advisory thread.

If you cannot use GitHub's private reporting:

- Email: `security@piwalletsv.invalid` (placeholder — replace with your
  real address before publishing the v0.1 release).
- PGP key: see `docs/security/piwalletsv-disclosure.asc` (placeholder;
  fingerprint will be published alongside the v0.1 release).

### What to include

- Affected component (Pi `piwallet` CLI, vault, envelope codec,
  companion proposal builder, broadcast path, …).
- Reproduction steps. A failing test case in `tests/` is ideal but
  not required.
- Estimated severity / impact in your own words (we will independently
  triage).
- Whether you have already disclosed this to anyone else.

### What we'll do

- Acknowledge receipt within 5 business days.
- Triage within 14 days. If we cannot reproduce, we will ask you for
  more detail rather than silently close the report.
- Coordinate a fix. We aim to ship a patch + advisory within 90 days
  of a confirmed report, sooner for critical issues.
- Credit you in the published advisory (CVE if applicable), unless you
  ask to remain anonymous.

### Out of scope

The following are **not** considered security vulnerabilities for this
project at the alpha stage:

- Bugs that require the user to type their seed phrase into something
  that has network access. The user instructions explicitly forbid
  this, and the disclaimer reiterates it.
- Bugs in upstream dependencies (`bsv-sdk`, `@bsv/sdk`, `@scure/bip32`,
  `@noble/hashes`, `cryptography`, etc.) — report those upstream. If
  the bug affects PiWalletSV specifically, please mention us in your
  upstream report or open a follow-up advisory here.
- Bugs in WhatsOnChain or any other third-party service this project
  consumes. Report those to the operator.
- Issues that require physical possession of the Pi for arbitrary
  amounts of time. We rely on operational tamper-evidence (see the
  `docs/security.md` chapter — coming in v0.1) plus the PIN-attempts
  vault-wipe; we do not claim that a determined adversary with
  unlimited physical access cannot extract the encrypted vault file.

### Public disclosure

Please give us a reasonable window to ship a fix before publishing
details. Coordinated disclosure protects other PiWalletSV users.

## Hardening Notes

Brief, non-exhaustive hardening notes for operators. The full security
chapter will live in `docs/security.md` once mkdocs-material is set up.

- The Pi should be air-gapped. Verify that Wi-Fi and Bluetooth are
  disabled (`/boot/firmware/config.txt` has `dtoverlay=disable-wifi` and
  `dtoverlay=disable-bt`). Do not plug in an Ethernet adapter.
- Boot integrity: pin the SHA-256 of `/boot/cmdline.txt`, of the
  `piwallet` Python package, and of `/etc/piwallet/version`. Compare
  on each boot before unlocking the vault.
- Vault file at `~/.piwallet/vault.bin`: AES-GCM, scrypt-derived KEK
  from the user PIN, per-wallet random DEK. Six wrong PIN attempts in
  a row wipe the vault. The seed is **never** persisted; it lives only
  in transient memory long enough to derive the master xprv.
- The companion app's IndexedDB store contains only public material
  (xpubs, fingerprints, cached UTXO snapshots). Loss of the companion
  browser profile is not a loss of funds.
- All envelopes are versioned (`v1`); when we change the wire format
  we will increment the version byte and refuse to decode older
  envelopes from the trusted side.

Thank you for helping keep PiWalletSV safe.
