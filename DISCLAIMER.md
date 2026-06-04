# PiWalletSV Disclaimer

**Read this entire document before you install, build, or use PiWalletSV.**
By installing, building, or using any part of PiWalletSV (the Raspberry
Pi signer, the companion web app, the documentation, or any helper
scripts in this repository — collectively "the Software") you confirm
that you have read this document, that you understand it, and that you
accept the terms set out below.

This is the **canonical disclaimer** for the project. It is referenced
from the project README, from the Pi's first-boot terms-of-service flow,
and from the companion web app's first-load acknowledgment modal.

---

## 1. Alpha Software

PiWalletSV is **alpha-quality, pre-release software** authored as a
personal / hobbyist project. It has **not** been independently audited
for security, correctness, or fitness for handling funds. Bugs,
regressions, undocumented behavior changes, and incompatible breaking
changes may occur in any release.

Do not store an amount of Bitcoin SV (BSV) in PiWalletSV that you are
not prepared to lose entirely.

## 2. Provided "As Is" — No Warranty

The Software is provided **"AS IS", WITHOUT WARRANTY OF ANY KIND**,
express or implied, including but not limited to the warranties of
merchantability, fitness for a particular purpose, title, and
non-infringement. The full license text (MIT) is in `LICENSE`.

No representation is made that:

- the Software is free of bugs or vulnerabilities;
- the Software will protect your funds from theft, loss, or seizure;
- transactions you sign will be accepted by any miner or be confirmed
  by the network;
- the cryptography used by the Software remains secure against future
  attacks, advances in computing, or implementation flaws in upstream
  dependencies (`bsv-sdk`, `@bsv/sdk`, `@scure/bip32`, `@noble/hashes`,
  `cryptography`, `cbor2`, the Linux kernel, etc.).

## 3. You Are Responsible For Your Keys

PiWalletSV is **non-custodial**. The author, contributors, and any
third-party services referenced by the Software (WhatsOnChain, BSV
Association, GitHub, Adafruit, Raspberry Pi Ltd., etc.) have **no
access** to your seed phrase, your encrypted vault, your PIN, or your
signing keys.

You are solely responsible for:

- generating your seed phrase in a secure environment;
- writing it down on a durable medium and storing it where you alone
  can find it;
- choosing a PIN that resists casual guessing without locking you out;
- physically protecting the Pi signer, its SD card, and any backup
  media;
- maintaining your own backups — the Software does not perform cloud
  backup;
- reviewing every transaction proposal on the Pi's screen before you
  press the confirm button.

**If you lose your seed phrase, your funds are lost. No one can recover
them. The author cannot recover them.**

If your PIN attempt counter reaches zero, the encrypted vault is wiped
and the device returns to first-boot state. **This is intentional.**
Recover from your seed backup, not from the device.

## 4. Air Gap Caveats

The Pi signer is designed as an air-gapped device. **You** are
responsible for keeping it air-gapped:

- never connect the signer Pi to a network if you have entered or
  imported a seed;
- never type, photograph, or paste your seed phrase into anything that
  has network access — including the companion web app, a phone, a
  password manager, a cloud document editor, or AI assistant;
- the companion web app **is online by design**: it queries
  WhatsOnChain for UTXOs, fetches Merkle proofs, and broadcasts signed
  transactions. It only ever sees public extended keys (xpubs) and
  pre-signed transactions. The xpub is enough to enumerate every
  address you have ever used with that wallet, so treat the companion
  as a privacy-sensitive (but not key-sensitive) device.

## 5. No Financial / Legal / Tax Advice

Nothing in this repository — code, comments, documentation, commit
messages — constitutes financial advice, legal advice, tax advice, or
investment advice. Cryptocurrency, including Bitcoin SV, is volatile
and is subject to legal and tax treatment that varies by jurisdiction
and changes over time. **Consult qualified professionals** before
relying on any wallet, including this one, for material amounts.

## 6. No Affiliation

PiWalletSV is **not affiliated with, endorsed by, or sponsored by**:

- Bitcoin Association for BSV / BSV Association;
- WhatsOnChain / TAAL;
- Raspberry Pi Ltd. or the Raspberry Pi Foundation;
- Adafruit Industries;
- the maintainers of `bsv-sdk` (Python), `@bsv/sdk`, `@scure/bip32`,
  `@noble/hashes`, or any other upstream dependency.

Trademarks (BSV, Raspberry Pi, Bonnet, etc.) belong to their respective
owners and are used here only for descriptive interoperability.

## 7. Third-Party Network Risk

The companion app talks to WhatsOnChain by default. WoC is operated by
TAAL and is **not** under the control of the PiWalletSV authors. Its
availability, accuracy, and rate limits can change without notice.
A malicious or compromised WoC response cannot make the Pi sign an
invalid transaction (the Pi verifies SPV proofs locally before
signing), but it **can** cause:

- incorrect balance display;
- failed broadcasts;
- a built proposal that the network later refuses to accept.

Broadcasted transactions cannot be recalled. Once a signed transaction
hits a miner, it is final.

## 8. Limitation of Liability

To the maximum extent permitted by applicable law, **the author and
contributors shall not be liable** for any direct, indirect, incidental,
special, exemplary, or consequential damages (including but not limited
to loss of cryptocurrency, loss of funds, loss of data, loss of profit,
business interruption, or punitive damages) arising in any way out of
the use of, inability to use, or any reliance on the Software, even if
advised of the possibility of such damage.

If a court of competent jurisdiction holds that any portion of this
section is unenforceable, the maximum aggregate liability of the author
and contributors to you for any and all claims relating to the Software
shall not exceed **the greater of (a) the amount you paid the author
for the Software (which is zero) or (b) one United States dollar**.

## 9. Jurisdictional Compliance

You are responsible for ensuring that your use of the Software is
permitted under the laws and regulations of your jurisdiction. The
Software is not designed or marketed for users in jurisdictions where
non-custodial cryptocurrency wallets are illegal, restricted, or
require licensing. **Do not use PiWalletSV if doing so would put you in
violation of local law.**

## 10. Reporting Security Issues

Please report security issues responsibly. See `SECURITY.md` for the
contact channel and PGP key. Publicly disclosing an unpatched
vulnerability that costs other users their funds violates the spirit of
this project and may also violate your local law.

## 11. Updates to This Disclaimer

This document may be updated as the project evolves. The Pi's
first-boot acknowledgment flow and the companion app's first-load
modal both track a `termsVersion` integer; when that integer is
incremented (because this document materially changed), you will be
re-prompted to acknowledge the updated disclaimer before continuing.

## 12. Kits and Case — No Unauthorized Resale

The Software in this repository is licensed under the MIT License
(see `LICENSE`). Nothing in this section limits your rights under that
license to use, modify, or distribute the **source code or software**.

Separately, without **prior written permission** from the project,
you may not sell, offer for sale, or commercially transfer:

- a **PiWalletSV kit** or assembled signer marketed or sold as
  PiWalletSV hardware;
- a **3D-printed enclosure** made from the PiWallet case design in
  this repository;
- the **printable case design or a printed case by itself** (standalone
  commercial sale of case files or printed shells).

To request permission, contact **[@PiWalletSV on X](https://x.com/PiWalletSV)**.
Personal, non-commercial use — including printing a case for your own
device — is permitted.

Generic Raspberry Pi, bonnet, camera, and other third-party parts may
be bought and sold independently; this section applies only to
PiWalletSV-branded kits and the PiWallet case design/goods described
above.

---

By continuing to use PiWalletSV, you acknowledge that you have read
and accepted this Disclaimer in full.

_Last reviewed: 2026-05-27. termsVersion: 2._
