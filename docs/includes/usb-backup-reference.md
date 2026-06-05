### Bonnet navigation

From the **wallet list**:

1. Press **B** to open **Settings**.
2. Select **USB backup** → **A**.
3. Pick **Backup to USB** or **Restore from USB**.

**B** at the USB backup submenu returns to **Settings**. **B** from
Settings returns to the wallet list.

On **first boot** (empty vault), choose **Restore from USB** from the
**First setup** screen instead.

### USB port

Use the Pi's **data** micro-USB port (the one **closer to the SD
slot**). Keep **PWR IN** connected for power.

### Stick requirements

- **FAT32 or exFAT** only (typical factory formatting is fine).
- Any capacity; backups are small (encrypted vault + manifest).

### On-stick layout

```text
PiWalletSV/backups/<YYYYMMDD-HHMMSSZ>/
├── manifest.json    wallet labels + fingerprints (public metadata)
├── vault.bin        encrypted vault (same format as on the SD card)
└── settings.json    optional (brightness, sleep timer, camera type)
```

**`terms.json` is never exported** — you re-accept the disclaimer
after a firmware upgrade.

Import **replaces the entire vault** on the device (all wallets).
When replacing an existing vault, the bonnet shows a preview and asks
for **double confirmation** before writing.

### Hot-plug

Inserting or removing a stick is safe **except during an active
backup or restore** (while data is being read or written). When
waiting to pick a drive, the bonnet rescans about once per second;
press **A** to rescan immediately.

### Security

The stick holds an encrypted vault. Anyone with **both** the stick
**and** your vault PIN can sign. Store the stick like a second copy
of the vault file — offline, under your control. The mnemonic remains
the canonical recovery path if you lose the stick or forget the PIN.
