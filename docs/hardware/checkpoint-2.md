# Hardware test checkpoint #2: on-device wallet create + restore

**Goal.** Verify the BIP39 word-entry UX and the new wallet-list action
rows on a real bonnet. After this checkpoint passes, the Pi is a
self-contained signing device: you can both generate a wallet and
restore an existing one without ever attaching the CLI.

Everything below is exercised by 316 host-side tests, but only the Pi
can prove that:

- the joystick repeat rate is comfortable for spelling 12-24 words,
- the candidate-letter highlight is legible at arm's length,
- a long-B during word entry actually escapes the flow,
- "+ New wallet" / "+ Restore wallet" rows show up after a vault unlock,
- vault writes persist across a reboot.

!!! note "SSH target placeholders"
    Replace `<user>@<host>` and `<repo-path>` with the SSH target and
    remote checkout path for your device.

## 1. Push the new code

From the dev machine:

```sh
rsync -av --delete \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='node_modules/' \
    --exclude='site/' \
    --exclude='companion/dist/' \
    ./ <user>@<host>:<repo-path>/
```

On the Pi:

```sh
ssh <user>@<host>
cd <repo-path>
bash scripts/install-piwallet-deps.sh
```

## 2. Run the bonnet against a clean vault

If you want a true "fresh device" walkthrough, move your existing
vault out of the way first:

```sh
mv ~/.piwallet/vault.bin ~/.piwallet/vault.bin.bak 2>/dev/null || true
.venv/bin/piwallet vault init
.venv/bin/piwallet bonnet
```

Otherwise (recommended for the first run-through):

```sh
.venv/bin/piwallet bonnet
```

You may need to unlock with the PIN you chose during initial setup.

## 3. Walk through "+ New wallet"

Inside the wallet list:

1. Joystick `DOWN` until the cursor lands on `+ New wallet`.
2. Press `A`.
3. You should see `WRITE THIS DOWN  page 1 of 3` with four numbered
   words. Verify all 12 words are legible by paging through with
   `RIGHT`. Pages 1-3 show words 1-4, 5-8, 9-12. Press `LEFT` to go
   back and confirm you really wrote the right words.
4. On page 3, press `A` to advance to confirmation. The screen
   becomes `Word 1 of 12` with an `a` slot highlighted.
5. Re-type each word using the documented controls:
    - `UP` / `DOWN` cycles the highlighted letter (down = a -> b -> ...).
    - `RIGHT` commits the candidate and opens a new `a` slot.
    - `LEFT` backspaces (re-opens the last committed letter).
    - `A` confirms when a single BIP39 word matches the typed stem.
    - `B` short-press clears the in-progress word entirely.
    - `B` long-press cancels the *whole* create flow.
6. If you fat-finger a word, the screen sets `done=true, error=...`
   and the bonnet shows a red `Failed` modal for ~2s. Try again.
7. On success, a green `Wallet saved` modal shows the label
   (`wallet-1`) and the first 4 bytes of the fingerprint, then drops
   back to the wallet list.
8. Drill into the new wallet to confirm a receive address renders
   correctly and the QR is scannable.

## 4. Walk through "+ Restore wallet"

1. From the wallet list, navigate to `+ Restore wallet`. Press `A`.
2. You see a `Phrase length` chooser. Pick `12 words` (or `24` if
   that's what you have).
3. The word-entry screen now reads `Word 1 of 12`. Type each word in
   your real 12-word backup phrase using the same controls.
4. On `Word 12 of 12 -> A`, the bonnet runs a BIP39 checksum on the
   full phrase. A bad checksum returns to the wallet list with a red
   `Failed: BIP39 checksum...` modal; a good one shows a green
   `Wallet saved` modal with label `restored-1`.

## 5. Restart and re-unlock

```sh
sudo reboot
ssh <user>@<host>
cd <repo-path>
.venv/bin/piwallet bonnet
```

Both wallets should still be in the vault after the reboot. Unlock
with your PIN and confirm the list now shows the wallets you created
plus the two action rows.

## Known gaps (call them out if you hit them)

- The bonnet does not yet expose label entry; new wallets get a
  default name and must be renamed via the CLI (`piwallet vault
  rename`, future). For v1 alpha this is acceptable.
- The `time.sleep(2.0)` "wallet saved / failed" banner is blocking;
  the bonnet appears frozen during the hold. Acceptable, but worth a
  thumbs-up that the timing feels right.
- The candidate-letter box is the *only* visual cue for which letter
  you are currently editing. If it's too subtle on the real panel
  (vs the previews), open an issue.

## Per-screen fix points

If something looks off:

* Word-entry layout (font size, candidate box width, footer): edit
  `piwallet/ui/word_entry.py` and re-render PNGs with
  `scripts/preview_bonnet_screens.py` before pushing.
* Show-phrase pagination (per-page count, font size): edit
  `piwallet/ui/show_phrase.py`.
* Word-count chooser appearance: it reuses `ListView`; tweak via
  `piwallet/bonnet/restore_wallet.py::_WordCountChooser`.
* Action row labels in the wallet list:
  `piwallet/bonnet/wallet_list.py::__post_init__`.

When this all works on hardware, mark the checkpoint passed in your
notes and consider it the v1 baseline for word entry.
