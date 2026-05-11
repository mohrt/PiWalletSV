# User manual

This chapter is the user-facing journey: from "I have an unflashed
SD card" to "I just signed and broadcast a transaction." It assumes
you've already done the hardware bring-up in
[Getting started](getting-started.md). The bonnet-driven UI for
some of these steps is part of Phase 2 and is noted in each section;
until it ships, the CLI on the Pi (and the companion PWA on the
phone) provides the same workflows.

!!! warning "Alpha software"
    PiWalletSV is alpha-quality. Until v1.0, exercise these flows
    with **testnet-scale amounts only**. The [Disclaimer](disclaimer.md)
    and [Security policy](security.md) describe the risks and your
    responsibilities.

## 1. First boot

When you first boot the Pi with PiWalletSV installed, the bonnet
will (Phase 2 onwards) walk you through a three-page disclaimer:

1. **Alpha software.** A short statement that this is pre-release
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

## 6. Send (Build a proposal)

On `/#/wallets/<id>` find the **Send** card.

1. Enter the **Recipient address**. Any valid BSV mainnet P2PKH
   address is accepted. The companion validates the checksum
   client-side; bad addresses are rejected before anything is built.
2. Enter the **Amount (sats)**.
3. Optional: under **Advanced**, change the fee rate (sats per kB).
   Default is 500 sats/kB; the Pi rejects rates above 10000
   sats/kB by default.
4. Click **Build proposal**.

What happens next, in order:

1. Greedy coin selection picks UTXOs largest-first until the target
   + estimated fee is covered.
2. For each selected UTXO, the proof fetcher calls the
   block-explorer endpoint to get the prior tx hex, its TSC Merkle
   proof, and the containing block's header.
3. The TSC proof is translated into the `@bsv/sdk` `MerklePath`
   format, then re-checked against the header's Merkle root. If
   the computed root doesn't match the header, the build aborts
   with a clear error — that's the companion's last-mile sanity
   check before it relies on the proof.
4. A BEEF blob is assembled from the prior tx + path.
5. The change address is derived at `m/1/<lastChangeUsed + 1>`.
   If the residue after fees is below the 546-sat dust threshold,
   change is folded into the fee instead.
6. An `unsigned_proposal` envelope is built per the
   [Envelope spec](protocol/envelopes.md) §4.
7. The envelope is gzipped + CBORed + split into PW1 multipart
   frames and animated on the canvas.

The card now shows:

- The proposal frame counter (`Frame X / Y · Z bytes total`).
- A **Pause** / **Resume** button.
- A **New send** button to discard the proposal and start over.

## 7. Verify and sign (Pi)

Take the Pi to wherever the companion's screen is. Point the camera
at the QR canvas.

=== "Bonnet (Phase 2)"

    The bonnet shows "Scanning..." until the PW1 assembler
    completes. Then it walks through the verification checks in
    real time, painting a one-line status per check. If anything
    fails, the bonnet stops at that line and shows the reason; you
    can either retry the scan (if it was a fragment-corruption
    issue) or abort.

    On success, the bonnet shows a **review** screen:

    - Recipient address (full, line-wrapped).
    - Amount (sats and BSV).
    - Fee (sats).
    - Per-input `(height, root-prefix)` anchor pairs.

    Hold **A** to confirm. The Pi derives the per-input keys,
    signs the transaction, and emits a `signed_tx` envelope as an
    animated QR for the companion to scan.

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

Lost a vault, replaced a SD card, switching devices?

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

The Pi will treat that as "no vault yet" on next launch. **This is
irreversible** without your mnemonic — the encrypted xprv and any
on-device-only state are gone.

If you've lost the PIN: there's no recovery mechanism. By design.
The vault will lock for an exponential delay after wrong-PIN
attempts (see [`piwallet/core/vault.py`](https://github.com/example/piwallet/blob/main/piwallet/core/vault.py))
and wipe after a configurable threshold of consecutive failures.
You'll need to restore from the mnemonic.

## 11. Troubleshooting

**The Pi camera doesn't see the companion's animated QR.**

- Confirm `rpicam-hello` shows live preview. If not, the CSI cable
  is the usual culprit — re-seat both ends.
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
