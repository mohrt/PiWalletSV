### Why verify?

Full kits ship with a **pre-flashed, factory-tested card**. That diagnostic
boot writes to the microSD, so the card no longer byte-matches the pristine
release image and cannot be checked with a whole-image checksum.

For cold-wallet assurance, **re-flash a signed release yourself** before
creating a wallet or receiving funds. Raspberry Pi has **no secure boot**,
and the device cannot show a trustworthy checksum of the whole card — do
not boot the Pi “to verify.”

| | Option | Best for |
|---|--------|----------|
| **A** | **Re-flash from a verified image** | **Recommended** |
| **B** | **Light checks** | Weaker paperwork / forensic record only |

### Option A — Re-flash (recommended)

Same path as a DIY first install: follow
**[Flash and first run](build-image.md)** end-to-end.

!!! warning "Re-flashing erases the card"
    On a new kit that is expected. If you already created a wallet, back up
    first ([Upgrade your device § Step 1](#step-1-back-up-before-you-flash)).

If you already verified and flashed before first boot, you are done —
continue at [First boot](#1-first-boot).

### Option B — Light checks (optional)

Use only if you are **not** re-flashing yet. These do **not** prove the
microSD matches an official image.

**Paperwork:** Compare **Image ID** and firmware version on the kit insert
to the matching
[GitHub release](https://github.com/mohrt/PiWalletSV/releases).
Mismatch → do not use; re-flash (Option A).

**Forensic hash (optional):** Power off, remove the microSD, and hash the
whole card on your computer (e.g. `dd … | shasum -a 256`). Keep the
digest as a record of what arrived — it will **not** match the pristine
release image after factory testing. Use Option A for real trust.
