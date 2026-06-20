# User manual

This chapter is the user-facing journey: from "I have an unflashed
SD card" to "I just signed and broadcast a transaction." It assumes
you've already done the hardware bring-up in
[Getting started](getting-started.md). The bonnet-driven UI for
some of these steps is part of Phase 2 and is noted in each section;
until it ships, the CLI on the Pi (and the companion web app on the
phone) provides the same workflows.

!!! warning "Beta software"
    PiWalletSV is beta-quality. Until v1.0, exercise these flows
    with **testnet-scale amounts only**. The [Disclaimer](disclaimer.md)
    and [Security policy](security.md) describe the risks and your
    responsibilities.

## Verify your SD card on arrival { #verify-sd-card-on-arrival }

Pre-flashed kits should be verified **before** you create a wallet or
receive funds:

- **Option B — Re-flash a verified image** (recommended): download from
  [Download](download.md), verify GPG + SHA-256, and flash the card
  yourself **before first boot**. Easiest way to trust the microSD.
- **Option A — Light checks** (optional, weaker): compare **Image ID** on
  the kit insert to piwalletsv.com (paperwork only), or hash the card
  in a computer reader without booting the Pi (advanced). The device
  cannot verify the card on-screen.

A **printable version** of this section ships in the kit:
[`docs/print/kit-insert.md`](print/kit-insert.md).

--8<-- "docs/includes/verify-sd-card.md"

## 1. First boot

On a **freshly flashed** SD card, the Pi reboots **once** while the image
expands to the card size. The panel may stay dark for up to ~1 minute until
the logo splash appears. After that one-time expand reboot, every boot is
single-stage.

When you first boot the Pi with PiWalletSV installed, the bonnet shows
the **PiWalletSV logo** briefly, then walks you through a three-page
disclaimer:

1. **Beta software.** A short statement that this is pre-release
   code with no warranty.
2. **You are your own custodian.** A reminder that nobody can
   recover funds for you if the seed is lost.
3. **No liability.** A confirmation that operating this device is
   on your own responsibility.

You hold the **A** button on the third page to confirm. The
acknowledgement is persisted (with the disclaimer version and
timestamp) into the vault file's metadata so the device doesn't
re-prompt on every boot. A version bump in the disclaimer text
re-prompts on next boot.

Hold **B** for five seconds on the boot logo to open
[factory diagnostics](#factory-diagnostics) instead of continuing setup.

Until Phase 2 ships, the equivalent acknowledgement happens in the
companion's first-load modal (see §3 below).

## 2. Create your first wallet

A "wallet" in PiWalletSV is one BIP39 seed plus one BIP44 account
at `m/44'/236'/0'`. The device supports multiple wallets in the
same vault; each has its own seed, its own xpub, and its own pair
of receive / change branches.

=== "CLI (today)"

    ```bash
    # 1. Initialise the vault (asks for a PIN twice).
    piwallet vault init

    # 2. Generate a fresh mnemonic and write it down on paper / steel.
    piwallet mnemonic new --words 12 > /dev/tty
    #    (or --words 24 for 256-bit entropy)

    # 3. Add the mnemonic to the vault. The CLI prompts for the
    #    PIN and reads the mnemonic from stdin.
    cat <<MNEMO | piwallet vault add --label "primary"
    word1 word2 ... word12
    MNEMO
    ```

    The mnemonic never touches disk in cleartext: it's read,
    used to derive the account xprv, encrypted under the vault's
    PIN-derived KEK, and discarded. The encrypted xprv plus its
    fingerprint, label, and BIP44 path are what get persisted.

=== "Bonnet (Phase 2)"

    The bonnet will provide:

    - A "**New wallet**" menu that generates a fresh mnemonic and
      walks you through reading each word aloud while a piece of
      paper is in front of you.
    - A "**Restore wallet**" menu that lets you re-enter a mnemonic
      via the joystick + A/B with BIP39 prefix autocomplete (the
      `word-entry-ui` task on the roadmap).

The "label" is purely for display — it's what shows up on the
bonnet selector and in the companion's wallet list. Pick something
that distinguishes wallets to you ("savings", "lightning float",
etc.); the label is included in the `xpub_export` envelope but is
not authoritative metadata.

## 3. First-load companion

Open the companion in your browser. The URL is whatever you decided
during the setup (`https://localhost:5173/` for development;
`https://your-domain.example/` once you deploy the static build).

On the first visit you'll see a **blocking modal**:

- A short summary of the disclaimer's key points.
- A checkbox: "I have read and accept the full DISCLAIMER.md on my
  own responsibility."
- A **Continue** button that's disabled until the box is ticked.

This modal re-appears whenever the disclaimer version increases.
`localStorage` tracks the acknowledgement; clearing site data
re-prompts.

After accepting, you land on `/#/wallets`, which is empty until you
pair a wallet.

### Add to Home Screen { #add-to-home-screen }

On a phone, install the companion to your home screen so it opens
full-screen like an app — without the browser address bar getting in
the way during QR scans.

--8<-- "docs/includes/pwa-install-steps.md"

## 4. Pair the Pi with the companion

Pairing copies the **public** account xpub from the Pi onto the
companion so the companion can watch the wallet (discover UTXOs,
display the next receive address, build proposals). No private
material crosses the gap.

=== "Bonnet (Phase 2)"

    Select **Pair → Show pairing QR** on the bonnet. The screen
    animates the multipart QR. The companion's **Scan** page reads
    it.

=== "Terminal QR (today)"

    ```bash
    # On the Pi:
    sudo apt install qrencode
    piwallet xpub-export --wallet-id <id> -o /tmp/xpub.bin
    piwallet qr split --chunk-chars 200 /tmp/xpub.bin |
        while IFS= read -r line; do
            clear
            qrencode -t UTF8 -- "$line"
            sleep 0.4
        done
    ```

    Then on the companion (`/#/scan`), tap **Start camera** and
    point it at the terminal.

Once the assembler completes:

1. The companion shows the parsed `xpub_export` envelope inline:
   label, fingerprint (hex), derivation path, xpub.
2. A **Save as paired wallet** card appears. You can rename the
   wallet locally before saving.
3. Click **Save**. The wallet shows up under `/#/wallets`.

The companion verifies the 4-byte self-fingerprint of the xpub
matches the envelope's `fp` field. If it doesn't (corrupted scan,
malicious source), saving is refused.

## 5. Receive

On `/#/wallets/<id>` you'll see a **Receive** card.

- **Address.** The next unused address (derived at
  `m/0/<nextReceiveIndex>`).
- **QR.** A QR code of the address text for the sender.
- **Previous / Next.** Step through addresses without revealing the
  current one. The "next" pointer is persisted; clicking past it
  advances the counter.

The receive flow is **purely client-side** — no Pi involvement.
The companion derives the address from the cached xpub. The Pi
never knows or cares which addresses you've handed out.

When a payment arrives, you don't need to do anything on the Pi.
Hit **Refresh balance** on the companion's **Balance** card to
re-scan. The scanner walks both `m/0/*` and `m/1/*` with a default
gap-limit of 20 and reports total sats, total BSV, UTXO count, and
the per-UTXO details (txid, vout, amount, derivation).

### Confirmed vs. pending (mempool) balance

The balance scan includes **both** confirmed on-chain UTXOs and
**pending** UTXOs still in the mempool (shown with `height = 0` /
"mempool" in the UTXO list). Your **total** includes both.

Only **confirmed** coins can be used as inputs when you send. This is
a deliberate SPV requirement, not a bug:

- Each spend input must carry a **Merkle proof** tying the funding
  transaction to a specific block header.
- Mempool transactions are not yet in a block, so no Merkle proof
  exists for them.
- The companion therefore refuses to build a proposal that spends
  unconfirmed UTXOs, and the Pi would reject one if it were supplied.

After you send, your **change** output often lands in the mempool
first. It appears in Balance as pending but is **not spendable** until
it confirms (typically one block). The Send tab shows **Spendable:**
as confirmed-only and labels any pending amount separately.

See [SPV verification](protocol/spv.md) for the full trust model and
what the Pi re-checks before signing.

## 6. Send (Build a proposal)

On `/#/wallets/<id>` find the **Send** card.

The **Spendable** line at the top shows confirmed coins only. If you
have mempool UTXOs, they are listed separately as pending and cannot
be selected for the next send until they confirm.

1. Enter the **Recipient address**. Any valid BSV mainnet P2PKH
   address is accepted. The companion validates the checksum
   client-side; bad addresses are rejected before anything is built.
2. Enter the **Amount (sats)**.
3. Optional: under **Advanced**, change the fee rate (sats per kB).
   Default is 500 sats/kB; the Pi rejects rates above 10000
   sats/kB by default.
4. Click **Build proposal**.

What happens next, in order:

1. **Select confirmed inputs.** Greedy coin selection picks from
   confirmed UTXOs only (largest-first) until the target + estimated
   fee is covered. Mempool UTXOs are skipped entirely.
2. **Fetch and verify SPV proofs.** For each selected UTXO, the proof
   fetcher calls the block-explorer endpoint to get the prior tx hex,
   its TSC Merkle proof, and the containing block's header.
3. **Cross-check Merkle roots.** The TSC proof is translated into the
   `@bsv/sdk` `MerklePath` format, then re-checked against the
   header's Merkle root. If the computed root doesn't match the
   header, the build aborts with a clear error — that's the
   companion's last-mile sanity check before it relies on the proof.
4. A BEEF blob is assembled from the prior tx + path.
5. The change address is derived at `m/1/<lastChangeUsed + 1>`.
   If the residue after fees is below the 546-sat dust threshold,
   change is folded into the fee instead.
6. An `unsigned_proposal` envelope is built per the
   [Envelope spec](protocol/envelopes.md) §4.
7. The envelope is gzipped + CBORed + split into PW1 multipart
   frames and animated on the canvas.

While steps 1–3 run, the companion shows an **SPV build progress**
indicator (Select inputs → Verify SPV proofs → Build proposal) with
per-input status such as "verified at block N (Merkle root matches
header)." When all checks pass, a green banner confirms that SPV
verification completed and reminds you that the Pi will re-verify
before signing.

The card now shows:

- The proposal frame counter (`Frame X / Y · Z bytes total`).
- A **Pause** / **Resume** button.
- A **New send** button to discard the proposal and start over.

## 7. Verify and sign (Pi)

Take the Pi to wherever the companion's screen is. Point the camera
at the QR canvas.

=== "Bonnet"

    From the wallet manage menu (the screen you reach by selecting
    a wallet from the list), pick **"Sign transaction"**. The
    bonnet opens a live camera preview with a status line beneath
    it:

    - **Aiming...** — the camera is settling and no `PW1|`
      fragment has decoded yet.
    - **frame N / M** — fragments are arriving; the count climbs
      until N == M and the proposal is fully assembled.

    Press **B** at any time to abort the scan and return to the wallet
    manage menu.

    Once assembly completes, the bonnet shows a **Verifying SPV**
    screen with a progress bar and a live status line as each input's
    BEEF path, Merkle proof, and block anchor are checked. On success
    it advances automatically to the **review** screen, which includes
    a green **SPV verified** badge (input count and block height
    range) above:

    - **Send** / **Fee** / **Net** (sats and network).

    This is the Pi's **second SPV gate**: it re-parses each input's
    BEEF, recomputes the Merkle root from the embedded BUMP path,
    and checks it against the `header_anchors` map the companion
    supplied. Signing only proceeds if every input passes.

    If verification fails on the SPV screen, the rejection reason
    is shown there; press **B** to return to the manage menu.

    If verification rejected the proposal on the review screen (legacy
    path when no pre-verify result is injected), the screen shows the
    rejection reason instead of the summary, and pressing **A**
    is a no-op.

    On a clean proposal, press **A** to sign. The Pi derives the
    per-input keys, builds the Atomic BEEF, wraps it in a
    `signed_tx` envelope, and animates it back to the companion
    as `PW1|` multipart QR frames at the same density used for
    pairing. Press **A** or **B** when the companion confirms it
    has the full set.

=== "CLI (today)"

    Until the bonnet flow ships, run the steps as discrete CLI
    invocations:

    ```bash
    # 1. On the Pi, capture the animated QR with the camera:
    piwallet qr scan-camera -o /tmp/proposal.bin

    # 2. (Optional) print a human-readable summary first:
    piwallet decode /tmp/proposal.bin

    # 3. Sign. The CLI prompts for the PIN, runs verify_proposal()
    #    end to end, prints the verification result, and writes
    #    the signed_tx envelope:
    piwallet sign \
        --wallet-id <id> \
        --max-fee-rate-satskb 10000 \
        -o /tmp/signed.bin \
        /tmp/proposal.bin

    # 4. Display the signed envelope back as an animated terminal
    #    QR for the companion to scan:
    piwallet qr split --chunk-chars 200 /tmp/signed.bin |
        while IFS= read -r line; do
            clear
            qrencode -t UTF8 -- "$line"
            sleep 0.4
        done
    ```

The signer **must** display the recipient, amount, fee, and anchor
pairs to the user before producing any signature. The signer
**must not** display the seed, mnemonic, or any private key.

## 8. Broadcast

Back on the companion's `/#/scan` page, point the laptop/phone
camera at the Pi's signed-tx QR. When assembly completes, the
parsed `signed_tx` shows up inline:

- Wallet fingerprint (hex, matched against the proposal you sent).
- Txid (lowercase hex, 64 chars).
- Raw hex (collapsed; expandable for inspection).

A **Broadcast signed transaction** card appears with a button. Click
it. The companion `POST`s the raw hex to the block-explorer's
broadcast endpoint and shows the returned txid plus a link to the
public explorer page.

If the returned txid differs from the one the Pi signed, the card
warns you. This usually means the broadcaster found a malleable
form of your signature or refused to relay it; treat as suspicious
and re-investigate before assuming the transaction will confirm.

If the broadcast fails outright (network error, "too few fees",
"missing inputs"), the card shows the error inline and the
**Broadcast** button stays available so you can retry. The original
`signed_tx` envelope stays in memory until you navigate away or hit
**Reset** — so you can fail, fix the network, and retry without
asking the Pi to re-sign.

## 9. Restore from mnemonic

Lost a vault, replaced a SD card, switching devices? If you need to
recover funds without access to the device at all, see
[Recover without device](recover-without-device.md) for step-by-step
instructions using iancoleman.io/bip39/ or ElectrumSV.

=== "Bonnet (Phase 2)"

    Select **Restore wallet** on the bonnet's main menu. The
    joystick word-entry UI lets you type each word with prefix
    autocomplete. Both 12 and 24-word mnemonics are supported.
    The checksum is verified before the account is derived.

=== "CLI (today)"

    ```bash
    piwallet vault init                  # only if you don't have a vault yet
    cat <<MNEMO | piwallet vault add --label "primary"
    word1 word2 ... word12
    MNEMO
    ```

A restored wallet produces the **same xpub** and the **same
fingerprint** as the original device. If you had paired the
original with the companion, the new device will pair to the same
companion record — the companion verifies the
`(walletFp, path, xpub)` triple matches.

The companion's local state (receive index, scan cache, label) is
**not** restored along with the wallet — that's companion-side
metadata and is rebuildable from the chain.

## 10. Wipe a wallet / wipe the vault

If you want to retire a wallet:

```bash
piwallet vault list                      # find the wallet id
piwallet vault remove --wallet-id <id>   # removes the encrypted xprv entry
```

To wipe the vault entirely, delete the vault file:

```bash
rm ~/.piwallet/vault.bin
```

Or use **Settings → Maintenance → Factory reset** on the bonnet to securely overwrite
the vault and clear settings and disclaimer state before handing the
device to someone else — see [§15 Settings](#settings).

The Pi will treat that as "no vault yet" on next launch. **This is
irreversible** without your mnemonic — the encrypted xprv and any
on-device-only state are gone.

If you've lost the PIN: there's no recovery mechanism. By design.
The vault will lock for an exponential delay after wrong-PIN
attempts (see [`piwallet/core/vault.py`](https://github.com/example/piwallet/blob/main/piwallet/core/vault.py))
and wipe after a configurable threshold of consecutive failures.
You'll need to restore from the mnemonic.

## 11. Upgrade your device { #upgrade-your-device }

PiWalletSV ships as a **sealed SD-card image**. There is no
over-the-air or in-app update path — by design, a signer that can
pull software updates over the network is not air-gapped. When a newer
firmware release is published, you **re-flash the microSD** and
restore your wallet from backup.

This section is the full end-user workflow. The companion PWA on your
phone or laptop is updated separately (refresh the browser or
re-install from the site); only the Pi device follows the steps below.

!!! warning "Re-flashing wipes the SD card"
    Flashing a new image erases **everything** on the card — vault,
    PIN verifier, disclaimer acceptance, and display settings. Back up
    **before** you flash. Your written-down mnemonic is always the
    canonical recovery path; the encrypted vault file is a convenience
    backup that still requires your PIN.

### What you need

- Your **mnemonic** on paper (or steel), **or** a **USB backup** from
  **Settings → Maintenance → USB backup** → **Backup to USB** (recommended before any re-flash).
- Your **PIN** (required for USB or vault-file restore).
- A **FAT32 or exFAT USB flash drive** (factory formatting is fine) for
  Path A below, **or** a microSD card reader for Path C.
- The new **`.img.xz`** and **`.asc`** signature from
  [Download](download.md), verified the same way as first setup
  ([Flash and first run § Step 1](build-image.md#step-1-verify-the-download)).

### Overview

| Step | What happens |
|------|----------------|
| 1 | Back up to USB (or confirm you have your mnemonic) |
| 2 | Download and verify the new image |
| 3 | Re-flash the microSD (full wipe) |
| 4 | Restore from USB, mnemonic, or vault file |
| 5 | Accept disclaimer, re-verify airgap, TESTNET smoke test |

### Step 1 — Back up before you flash

#### Path A — USB backup (recommended)

On the **current** firmware, before you re-flash:

1. Insert a **FAT32 or exFAT** USB stick into the Pi's **data** micro-USB
   port (the one closer to the SD slot; power stays on **PWR IN**).
2. **Press B** → **Settings** → **Maintenance** → **USB backup** → **Backup to USB**.
3. Pick the drive from the list, confirm your **PIN**, and wait for
   *Backup saved*. Press **A** or **B** to dismiss, then **B** to
   return to Settings.

Backups are stored under `PiWalletSV/backups/<timestamp>/` on the stick
(`vault.bin`, optional `settings.json`, and a manifest). **`terms.json`
is never exported** — you will re-accept the disclaimer after upgrading.

Keep the stick offline with the device. Anyone with the stick **and**
your PIN can sign.

#### Path B — Mnemonic (always works)

If you have the 12- or 24-word seed written down, you do **not** need
a USB or SD backup. After re-flash, restore via the bonnet ([§9](#9-restore-from-mnemonic)).

#### Path C — Copy `vault.bin` off the SD card (fallback)

Copying `vault.bin` lets you skip re-typing every word, but you must
still know the **same PIN** as before. The file is encrypted at rest;
treat the backup like a second copy of the vault — store it securely.

On the **sealed production image**, PiWalletSV state lives in a single
directory (nothing else on the card is user-writable):

```text
/home/pwsv/.piwallet/
├── vault.bin       ← required for vault restore
└── settings.json   ← optional (brightness, sleep timeout)
```

**Disclaimer (`terms.json`) is not backed up** — a firmware upgrade always
re-prompts the disclaimer on first boot after re-flash.

**Physical backup (no SSH on the sealed device):**

1. **Power off** the Pi and remove the microSD.
2. Insert the card into a **USB card reader** on another computer.
3. Mount the **Linux root** partition (ext4). On Linux this is usually
   automatic; on macOS or Windows you may need an ext4 driver or a
   Linux live USB — plan ahead if you do not have Linux handy.
4. Copy the entire `.piwallet/` folder (or at minimum `vault.bin`) to
   encrypted storage — a password-protected archive on a USB stick you
   control, not cloud sync.

Do **not** skip this step and assume you will copy files after
flashing; the new image overwrites the card completely.

### Step 2 — Download and verify the new image

Follow [Download](download.md) and
[Flash and first run § Step 1](build-image.md#step-1-verify-the-download):

1. Fetch `piwalletsv-<VERSION>.img.xz` and its `.asc` signature.
2. Verify the signature with the project release key.
3. Decompress if your flashing tool requires a raw `.img`.

**Do not flash an unverified image.**

### Step 3 — Re-flash the microSD

Flash the verified image with Raspberry Pi Imager or your platform's
equivalent ([Flash and first run § Step 2](build-image.md#step-2-flash-the-image)).

This step **destroys** the old card contents. Confirm your backup from
Step 1 is safe before you proceed.

### Step 4 — Restore your wallet

Pick **one** path below. Import **replaces all wallets** on the device
(and optionally display settings). There is no merge.

#### Path A — Restore from USB (recommended after Step 1 Path A)

1. Power on the flashed Pi, accept the **disclaimer** (always shown
   after a firmware upgrade).
2. On **First setup**, choose **Restore from USB** (or, if you already
   have a vault, **press B** → **Settings** → **Maintenance** → **USB backup** →
   **Restore from USB**).
3. Insert the backup stick, pick the drive, then pick the backup
   timestamp.
4. Review the wallet list — existing wallets on the device (if any)
   are shown as **will be erased**. Confirm twice if replacing a vault.
5. Toggle **Import settings** with **RIGHT** if you want brightness /
   sleep timer restored (optional).
6. Enter the **backup vault PIN** and unlock.

#### Path B — Restore from mnemonic

1. Accept the disclaimer and choose **New vault (set PIN)** on first
   setup, **or** use an empty vault from first-boot PIN setup.
2. On the wallet list, choose **Restore wallet** and enter your seed
   ([§9](#9-restore-from-mnemonic)).

Your xpub and fingerprint match the old device, so the companion
wallet you already paired should continue to work without re-pairing.

#### Path C — Restore from `vault.bin` on the SD card (fallback)

Use this only if you copied `vault.bin` in Step 1 and remember the
**original PIN**.

1. **Before first boot** on the new image (recommended): mount the
   freshly flashed card's root partition on your computer and copy
   your backup files into place:
   ```text
   /home/pwsv/.piwallet/vault.bin
   /home/pwsv/.piwallet/settings.json   (optional)
   ```
2. Ensure the directory is owned by the runtime user. On the sealed
   image that user is `pwsv`. After mounting the root partition on a
   Linux machine, look up its numeric id and fix ownership before
   booting the Pi:
   ```bash
   PWSV=$(grep '^pwsv:' /path/to/mounted/root/etc/passwd | cut -d: -f3-4)
   sudo chown -R "$PWSV" /path/to/mounted/root/home/pwsv/.piwallet
   sudo chmod 700 /path/to/mounted/root/home/pwsv/.piwallet
   sudo chmod 600 /path/to/mounted/root/home/pwsv/.piwallet/vault.bin
   ```
   If you cannot set ownership correctly from your host OS, use
   **Path B** (mnemonic restore) instead.
3. **Power on** the Pi. If `vault.bin` is present and valid, the
   bonnet skips "choose a PIN" and goes straight to **PIN unlock**.
4. Enter your **original PIN** — not a new one from a aborted setup.

If you already completed first-boot PIN setup on an empty vault, you
have created a new vault that does not contain your wallets. Either
restore via **Path B** (mnemonic), or stop the Pi, mount the card
again, replace `vault.bin` with your backup, and boot once more.

### Step 5 — Verify after upgrade

Treat the upgraded device like a new install until you have evidence
it is still sealed:

1. **Press B** → **Settings** → **Maintenance** → **Airgap status** → **A**. Every row
   should read `OK` and the header should say **Air-gapped**. See
   [§14 Airgap status](#airgap-status) if anything shows `!!`.
2. Run a **TESTNET** send round-trip ([Flash and first run § Step 9](build-image.md#step-9-sign-your-first-transaction))
   before returning to mainnet amounts.

### Companion app after a Pi upgrade

- **Mnemonic or vault restore** with the same seed → same xpub → your
  existing companion wallet record should work; hit **Refresh balance**
  to resync UTXOs.
- **Companion version**: if the release notes mention a wire-format
  change, update the PWA on your phone/laptop to match the new Pi
  firmware before signing.

### Developer installs (SSH, not the sealed image)

If you built the signer yourself from source and still have SSH access,
day-to-day software updates are a `git pull` and service restart — see
[Operate § Updating the software](operate.md#updating-the-software).
That path does **not** apply to the downloadable sealed image, which
has no network and no editable app tree under `/opt/piwallet`.

### Common mistakes

| Mistake | Consequence |
|---------|-------------|
| Flash before backing up | Vault gone unless you have the mnemonic |
| Complete first-boot PIN setup, then copy old `vault.bin` | Confusing state — replace `vault.bin` on SD while powered off, or use mnemonic |
| Restore vault file but forget original PIN | Vault file is useless without PIN; restore from mnemonic |
| Skip airgap check after re-flash | You may sign on a mis-provisioned image |
| Assume the companion auto-updates with the Pi | Update both independently when release notes say so |

## 12. USB backup and restore { #usb-backup }

PiWalletSV can export and import the encrypted vault (and optional
display settings) to a **FAT32 or exFAT USB stick**. This is the
recommended path before re-flashing the SD card
([§11 Upgrade your device](#upgrade-your-device)) and works any time
from Settings.

--8<-- "docs/includes/usb-backup-reference.md"

For shell access on a development Pi (or scripted backups), see
[CLI § `piwallet backup`](cli.md#piwallet-backup) and
[Operate § USB vault backup](operate.md#usb-vault-backup).

## 13. Troubleshooting { #troubleshooting }

**Accessing a local debug console (tty2) via HDMI + USB keyboard.**

The sealed image keeps a second virtual terminal on tty2 for local
troubleshooting — it is never accessible over the network. To use it:

1. Plug a USB keyboard and micro-HDMI cable into the Pi.
2. Power on (or reboot) the device.
3. Once the bonnet shows the boot splash or disclaimer, press
   **Ctrl + Alt + F2** on the keyboard. The HDMI output switches to tty2
   and shows a login prompt.
4. Log in as `pisv` with your device password.
5. To return to tty1 (bonnet display output) press **Ctrl + Alt + F1**.

This console has no network access and is intended for reading logs
(`sudo journalctl -u piwallet-bonnet -f`), running the factory smoke
test, or other local diagnostics. It does not interfere with the bonnet
UI running on tty1.

---

**Send says "no spendable UTXOs" or "only confirmed coins can be sent"
but Balance shows a non-zero total.**

- Your wallet may hold only **mempool (unconfirmed)** UTXOs — for
  example change from a send you just broadcast. Refresh Balance,
  check the UTXO list for "mempool" tags, and wait for confirmation.
- SPV requires each input to be anchored in a mined block. Until
  pending coins confirm, they count toward your displayed total but
  cannot be spent. This is by design; see §5 "Confirmed vs. pending."

**The Pi camera doesn't see the companion's animated QR.**

- Confirm `rpicam-hello` shows live preview. If not, the CSI cable
  is the usual culprit — re-seat both ends.
- The kit **OV5647** is fixed-focus (~30 cm / ~1 ft). Hold the bonnet
  at that distance from the companion screen.
- The companion's animation is too fast. Use the **Pause** button to
  hold a frame, then resume. The Pi assembler is happy with frames
  in any order.
- Ambient light. The bonnet's display reflects glare from
  overhead lights into the camera. Tilt one or the other.

**The Pi's verify step fails with "merkle root mismatch."**

- Confirm the companion's chosen block-explorer endpoint is the
  same chain you intend to operate on (mainnet, not testnet — v1
  is mainnet-only).
- Re-run **Refresh balance** in the companion so the UTXO snapshot
  is current. A stale snapshot can point at UTXOs that have since
  been spent; their proofs won't recompute against the current
  chain headers.
- Display the on-bonnet anchor pair on the Pi (height + root) and
  compare against a public block explorer. If they match the
  explorer but the verify still fails, file a bug.

**The Pi's verify step fails with "script does not match
derivation."**

- The companion claimed an input came from `m/0/i`, but the prior
  tx output isn't a P2PKH spend to the address at that derivation.
  This almost always means the companion's UTXO scanner has a bug
  or the wallet was restored without resetting the scan state.
  Force a re-scan and try again.

**The companion's broadcast returns a different txid than the Pi
signed.**

- The most likely cause is tx malleability in the signed transaction.
  This shouldn't happen for the canonical P2PKH spend path the
  signer uses, but it's worth filing a bug with the raw hex if
  you see it consistently.

**The companion is stuck on the disclaimer modal.**

- Check the checkbox. The Continue button is disabled until you
  tick it. This is by design — it forces you to actually
  acknowledge each version of the disclaimer.

**Lost PIN, no mnemonic backup.**

- You have lost your funds. We're sorry. This is the
  non-custodial promise: no party (the project, the device, the
  companion) can recover your wallet without the mnemonic.

**&ldquo;Airgap status&rdquo; shows BREACH or a row with `!!`.**

- See [§14 Airgap status](#airgap-status) for what each indicator
  means and what to do. Do not sign until the report is all-green.

## 14. Airgap status { #airgap-status }

PiWalletSV's security model depends on the signing device having no
network path. The **Airgap status** screen in Settings runs live checks
so you can verify that claim on demand — at first setup, after a
reflash, or any time before signing something sensitive.

From the wallet list:

1. **Press B** to open Settings.
2. Joystick down to **&ldquo;Airgap status&rdquo;**.
3. Press **A**.

--8<-- "docs/includes/airgap-status-reference.md"

For the shell equivalent (recommended periodically, and required for
full host interface verification), see
[Operate — Airgap diagnostic](operate.md#airgap-diagnostic).

## 15. Settings { #settings }

Global device options live under **Settings** on the bonnet (hub with
**Preferences** and **Maintenance**). Open it with a short **B** press
from the wallet list. Press **B** on the hub to return to wallets.

--8<-- "docs/includes/settings-reference.md"

For operator-facing USB steps, see [§12 USB backup](#usb-backup). For
airgap interpretation, see [§14 Airgap status](#airgap-status).

## 16. Factory diagnostics { #factory-diagnostics }

Support and factory workflows can open the **Diagnostics** menu from the
boot splash without unlocking the vault.

--8<-- "docs/includes/diagnostics-reference.md"

For day-to-day service restarts from SSH, see
[Operate § Reading the bonnet log](operate.md#reading-the-bonnet-log).

## Help & support

--8<-- "docs/includes/support-contact.md"
