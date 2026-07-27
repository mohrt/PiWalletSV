# Operate

Day-to-day operation of a deployed PiWalletSV signer: where logs live,
what each exit code means, factory diagnostics and reset, how to wipe
and restore the vault, and how to recover when something doesn't behave.

This chapter assumes the device is installed per [Build & deploy](build.md).
For the user-facing journey (pairing, sending, receiving) see the
[User manual](user-manual.md). To interpret the bonnet's airgap
indicators see [User manual § Airgap status](user-manual.md#airgap-status).
For wire-format troubleshooting see the user manual's
[Troubleshooting](user-manual.md#troubleshooting)
section, which is intentionally not duplicated here.

## Logs

Everything the bonnet writes goes to the system journal via systemd.
There are no rotating files inside `~/.piwallet`; the journald
drop-in (`deploy/systemd/journald-piwallet.conf.example`) caps the
journal at 32 MB total with 8 MB per file, which is what makes this
safe on an SD card.

### Reading the bonnet log

```bash
# Last 100 lines, no pager:
journalctl -u piwallet-bonnet -n 100 --no-pager

# Live tail:
journalctl -u piwallet-bonnet -f

# Just this boot:
journalctl -u piwallet-bonnet -b 0

# Previous boot (after a crash + auto-restart):
journalctl -u piwallet-bonnet -b -1
```

The signer's Python logger is named `piwallet`; the noisy
dependencies it tames are `picamera2` and `libcamera`. By default
PiWalletSV clamps both to `WARNING` and silences libcamera's INFO
chatter (which is otherwise the bulk of the volume).

### Adjusting verbosity

Set environment variables in the systemd unit (or export before
running `piwallet bonnet` interactively):

| Variable | Default | Meaning |
|----------|---------|---------|
| `PIWALLET_LOG_LEVEL` | `WARNING` | Python `logging` level. `DEBUG` is loud; use sparingly. |
| `LIBCAMERA_LOG_LEVELS` | `*:WARN` | libcamera severity. `*:INFO` brings back vendor INFO. |
| `PICAMERA2_LOG_LEVEL` | `0` | Picamera2 console verbosity (numeric, higher = more). |

After editing the unit:

```bash
sudo systemctl daemon-reload
sudo systemctl restart piwallet-bonnet
```

### What "normal" looks like

A healthy boot of `piwallet bonnet` writes only a handful of lines:

- one `INFO` from the disclaimer flow (skipped after first acceptance),
- one `INFO` from the vault-unlock screen,
- nothing per frame.

If you see `WARNING` or `ERROR` lines, those are real — the bonnet
deliberately suppresses everything else.

## Exit codes

`piwallet bonnet` returns a Unix-style exit code so systemd can
distinguish "user asked to leave" from "device is unusable until you
do something." The values match the docstring on `run_bonnet()` in
`piwallet/bonnet/app.py`:

| Code | Meaning | Typical systemd response |
|------|---------|--------------------------|
| `0` | Normal exit. The process finished cleanly — for example after **Restart app** in factory diagnostics, or `systemctl stop piwallet-bonnet`. There is no operator gesture to quit the bonnet from the UI. | Restart by `Restart=always`; bonnet comes back up (splash → unlock or setup). |
| `1` | Vault is missing or empty. The operator hasn't run `piwallet vault init` yet. | Same as 0 — the bonnet shows a "No vault" message before exiting; the next start hits the same state. Fix it from the CLI. |
| `2` | Disclaimer cancelled. | Same as 0. The bonnet will re-show the disclaimer on next start. |
| `3` | The vault wiped itself during unlock (consecutive PIN failures exceeded the threshold). | Same as 0. The next start finds an empty vault and reports code 1. Restore from mnemonic. |

The example unit uses `Restart=always` with `RestartSec=3`, which
gives systemd a 3-second cooldown between restarts. That's enough to
let the panel blank cleanly (the backlight is turned off in the
`finally` block of `run_bonnet`) before the next process starts.

If you want a hard "wipe → halt" policy instead of "wipe → reboot to
empty-vault state", change the unit to:

```ini
Restart=on-success
RestartPreventExitStatus=3
```

…and add a follow-up unit that opens a console message. Most
operators are better served by the default — exit 3 is rare in
normal use.

## Vault stewardship

The encrypted vault is a single file (typically
`~/.piwallet/vault.bin`). Treat it as the source of truth for
what wallets exist on the device. The mnemonic is the source of
truth for the *funds* — the vault is destroyed by a wipe; the
mnemonic is not.

### Listing wallets without unlocking

`vault list` does not require the PIN; it reads the public metadata
only:

```bash
piwallet vault --vault-path ~/.piwallet/vault.bin list
```

This is safe to run from a script (a backup-monitoring job, for
example) and emits one line per wallet: `<id> <label>`.

### USB vault backup { #usb-vault-backup }

The recommended backup path for sealed devices is the bonnet:
**press B** → **Settings** → **Maintenance** → **USB backup**. Full operator steps,
stick layout, and hot-plug notes are in
[User manual § USB backup and restore](user-manual.md#usb-backup).

On images built with `deploy/provision-pi.sh`, the mount stack is
installed automatically:

--8<-- "docs/includes/usb-backup-provisioning.md"

#### CLI (dev Pi or automation)

When the stick is already mounted (or you're writing to a directory
tree for testing):

```bash
piwallet backup list-devices
piwallet backup export --stick-root /mnt/piwallet-usb
piwallet backup list-backups --stick-root /mnt/piwallet-usb
piwallet backup import \
  --backup-dir /mnt/piwallet-usb/PiWalletSV/backups/20260527-120000Z/ \
  --import-settings
```

Import **replaces** the entire vault. The CLI prompts for the backup
vault PIN unless you pass `--pin`. See [CLI § `piwallet backup`](cli.md#piwallet-backup).

### Backing up the vault file (manual copy)

Copying `vault.bin` is fine; the file is encrypted at rest. A copy
on a USB stick is acceptable — the bonnet **USB backup** flow writes
a timestamped bundle under `PiWalletSV/backups/` with a manifest for
easier restore. Keep in mind:

- Restoring from a backup is **not the same** as restoring from the
  mnemonic. The backup includes the same scrypt parameters and PIN
  verifier; its security is only as strong as the PIN.
- The mnemonic is always the canonical recovery path. If you have
  the mnemonic, you don't need the vault file. If you have only the
  vault file, you also need the PIN.

For the full re-flash upgrade workflow (sealed SD-card image), see
[User manual § Upgrade your device](user-manual.md#upgrade-your-device).

### Wiping the vault

Two ways:

1. **Wrong-PIN wipe.** Hit the configurable consecutive-fail
   threshold and the vault wipes itself. This is what `outcome.kind
   == "wiped"` exit code `3` reports.
2. **Manual wipe.** Stop the service and remove the file:

```bash
sudo systemctl stop piwallet-bonnet
shred -uz ~/.piwallet/vault.bin
sudo systemctl start piwallet-bonnet
```

The bonnet will then report "No vault" (exit code 1) until you run
`piwallet vault init` again.

### Factory reset

A "factory reset" wipes the vault, removes disclaimer acceptance, and
returns the device to first-setup condition.

#### Bonnet (sealed device)

**Settings → Maintenance → Factory reset** → double confirm → vault **PIN**. The vault
file is securely overwritten; `settings.json` and `terms.json` are
removed. The bonnet then shows *Factory reset complete* and loops into disclaimer
and new PIN setup. See [User manual § Settings](user-manual.md#settings).

#### CLI (dev Pi or automation)

```bash
sudo systemctl stop piwallet-bonnet
shred -uz ~/.piwallet/vault.bin
rm -f ~/.piwallet/terms.json ~/.piwallet/settings.json
piwallet vault --vault-path ~/.piwallet/vault.bin init
piwallet firstboot run --headless
sudo systemctl start piwallet-bonnet
```

Removing `terms.json` makes the disclaimer flow re-prompt on next
boot. This is what you want when handing the device to a different
operator.

A factory reset does **not** wipe the SD card — only the signer's
state. To dispose of the device entirely, re-flash the SD card with a
zeroed image. There is no other persistent state.

### Restoring from a mnemonic

Use either the bonnet UI (`+ Restore wallet` from the wallet list)
or the CLI:

```bash
echo "various crime subway february cradle runway symptom snap muffin deny first pole" \
    | piwallet vault --vault-path ~/.piwallet/vault.bin add --label "Restored"
```

Both paths run the same checksum check and produce the same encrypted
record.

## Updating the software

```bash
ssh pi@piwallet-1.local
cd /home/pi/PiWallet
git pull
source .venv/bin/activate
bash scripts/install-piwallet-deps.sh
sudo systemctl restart piwallet-bonnet
```

If the update touches a wire format, the [Protocol spec](protocol/README.md)
notes the version bump and the companion needs a matching update. The
PWA's first-load disclaimer modal will re-prompt on a `termsVersion`
bump, so users always see explicit notice of major changes.

For an offline/air-gapped Pi (no `git pull` reachable), build a
release tarball on a workstation and `scp` it over:

```bash
# On the workstation:
git archive --format=tar.gz HEAD -o /tmp/piwallet.tgz

# On the Pi:
scp workstation:/tmp/piwallet.tgz /tmp/
sudo systemctl stop piwallet-bonnet
cd /home/pi/PiWallet
tar xzf /tmp/piwallet.tgz
source .venv/bin/activate
bash scripts/install-piwallet-deps.sh
sudo systemctl start piwallet-bonnet
```

A signed-tarball workflow ships with v0.1; until then you're trusting
your own copy.

### Upgrading from a pre-rename dev install

Earlier developer builds stored state under `~/.piwallet-dev/`. The
bonnet's boot loop now performs a one-shot rename to `~/.piwallet/`
on first start after an update — provided the canonical directory
doesn't already exist. The rename is logged at `WARNING` level so it
shows up in `journalctl -u piwallet-bonnet`. Custom `--vault-path`
arguments pointing at `~/.piwallet-dev/...` will need to be updated
to the new path; the bonnet's defaults already follow the rename.

## Time stewardship

The signer doesn't run NTP and doesn't accept network traffic. The
RTC time after first boot is whatever the OS image (and battery-backed
RTC, if present — the Pi Zero / Zero W doesn't have one) said.

The verifier doesn't depend on the wall clock for correctness: BEEF
proofs anchor against block headers that carry their own timestamps,
and the user-displayed anchor on the bonnet is what the operator
sanity-checks against a public block explorer. So a stale RTC is a
log-readability issue, not a security issue.

If you want correct timestamps in the journal, point the OS at an
NTP server *during install* (the imager's network connectivity is the
only window you'd want this) and let `systemd-timesyncd` set the time
once. Then disable it before unplugging from Wi-Fi.

## Airgap diagnostic { #airgap-diagnostic }

The bonnet **Settings → Maintenance → Airgap status** screen shows three summary rows
(**Wi-Fi**, **Bluetooth**, **Network**) that roll up the same underlying
checks as `piwallet diag airgap`. Inside the bonnet app the **Network**
row only sees the app's network sandbox (`PrivateNetwork=yes`). From a
shell on the Pi you get the full six-row host report — use this
periodically and whenever the on-screen check looks wrong.

```bash
# Human-readable table; exits non-zero on conclusive failure:
piwallet diag airgap

# JSON for scripts / support tickets:
piwallet diag airgap --json
```

What each bonnet row and shell row means, and how to read `OK` / `!!` /
`--`, is documented in
[User manual § Airgap status](user-manual.md#airgap-status).

## Factory diagnostics { #factory-diagnostics }

Operators and support can open the diagnostics menu from the boot splash
(hold **B** for ~5 seconds on the logo). Menu items, hardware tests,
and **Restart app** (systemd service restart, not a full Pi reboot) are
documented in
[User manual § Factory diagnostics](user-manual.md#factory-diagnostics).

## Troubleshooting

For wire-format failures (verify mismatch, broadcast txid mismatch,
etc.) see the [User manual § Troubleshooting](user-manual.md#troubleshooting).
This section covers operational issues with the deployment itself.

### The bonnet doesn't come up after reboot

```bash
sudo systemctl status piwallet-bonnet
```

If status is `failed` or `activating (auto-restart)` in a tight loop:

1. Read the journal for the failing boot:
   ```bash
   journalctl -u piwallet-bonnet -b 0 --no-pager | tail -80
   ```
2. Common causes:
    - **`ModuleNotFoundError: piwallet`** — the venv is missing.
      Run `bash scripts/install-piwallet-deps.sh` again.
    - **`Permission denied` on the vault path** — the unit's `User=`
      doesn't match the owner of the vault file. Either chown the
      vault or update the unit.
    - **`spidev: bufsiz too small`** — the kernel cmdline tweak in
      [Build § 4](build.md#4-enable-spi-tune-the-kernel-buffer)
      didn't take. Confirm `cat /sys/module/spidev/parameters/bufsiz`
      is `131072`.

### The screen is bright but blank / frozen

Almost always an SPI handshake issue:

1. Power-cycle the Pi (cleaner than a soft reboot for SPI state).
2. Re-seat the bonnet on the GPIO header.
3. Run the bonnet bring-up demo manually:
   ```bash
   python /home/pi/PiWallet/scripts/rgb_display_pillow_bonnet_buttons.py
   ```
   If the demo is also blank, the bonnet itself or the `spidev`
   tuning is the culprit, not the PiWalletSV code.

### The bonnet shows the disclaimer every boot

`firstboot status` should report `accepted` after a successful
acceptance. If it doesn't, the `terms.json` file isn't writable:

```bash
ls -la ~/.piwallet/
piwallet firstboot status
```

If the file is owned by `root` (because you ran `firstboot run` as
root once), `chown pi:pi` it.

### Camera stops decoding mid-pairing

Pairing involves an animated multipart-QR sequence on the companion
that the Pi camera reassembles. If the assembler stalls:

1. Use the companion's **Pause** button to hold a single frame.
2. Confirm the frame counter on the Pi is advancing — if it is,
   ambient light or focus is the issue. Tilt the bonnet or move the
   phone.
3. If the frame counter is frozen at the same number, the assembler
   has decided that frame is full. Use **Reset** on the companion to
   start over.

### "No vault" on every boot after a wipe

The bonnet refuses to do anything until a vault exists. Run
`piwallet vault init` from SSH (it's an interactive PIN setup) and
the next reboot will present the unlock screen. Don't try to run
`vault init` while `piwallet-bonnet.service` is active — the SPI bus
ownership won't conflict, but the user experience is confusing
(panel will flash between two processes).

```bash
sudo systemctl stop piwallet-bonnet
piwallet vault --vault-path ~/.piwallet/vault.bin init
sudo systemctl start piwallet-bonnet
```

## Safe shutdown

Pulling the power on a Pi is mostly fine for the SD card these days
(F2FS / ext4 + journaled), and the signer holds no in-memory state
that loses meaning across a power cycle (the PIN cache is in process
memory, never written to disk). The cleaner path is:

```bash
sudo systemctl poweroff
```

…which stops `piwallet-bonnet.service` first (so the backlight goes
off cleanly), then halts.

## What we don't ship (yet)

- A tamper-evidence indicator on the bonnet (planned with phase 8
  hardening).
- An on-device update path. Updates today require SSH; the Pi has no
  inbound channel besides the camera and no outbound channel
  besides the panel.
- Multi-user separation. The signer assumes a single operator. If
  you need multi-operator separation, run a separate signer per
  operator.
