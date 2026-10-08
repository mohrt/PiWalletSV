### Navigation

=== "Zero"

    From the **wallet list**:

    1. Press **B** to open **Settings**.
    2. Select **Maintenance** → **A**.
    3. Select **USB backup** → **A**.
    4. Pick **Backup to USB** or **Restore from USB**.

    **B** at the USB backup submenu returns to **Maintenance**. **B** from
    Maintenance returns to the Settings hub. **B** on the hub returns to the
    wallet list.

    On **first boot** (empty vault), choose **Restore from USB** from the
    **First setup** screen instead.

=== "Pro"

    From the home screen:

    1. Tap **Settings** → **Maintenance** → **USB backup**.
    2. Tap **Backup to USB** or **Restore from USB**.

    **Back** (top right) moves up one level at a time.

    On **first boot**, the Pro asks you to create a PIN first. Then restore
    from **Settings → Maintenance → USB backup → Restore from USB**; the
    import replaces the new, empty vault.

### USB port

=== "Zero"

    Use the Pi's **left** micro-USB port with **your own** micro-USB OTG adapter
    and a **USB flash drive**. Keep **PWR IN** (right port) connected for power.

=== "Pro"

    Plug the **USB flash drive** straight into any of the Pi's four full-size
    USB ports. No adapter is needed. Power stays on the micro-USB port.

### Stick requirements

- **FAT32 or exFAT** only (typical factory formatting is fine).
- Any capacity; backups are small (encrypted vault + manifest).

### On-stick layout

```text
PiWalletSV/backups/<YYYYMMDD-HHMMSSZ>/
├── manifest.json    wallet labels + fingerprints (public metadata)
├── vault.bin        encrypted vault (same format as on the SD card)
└── settings.json    optional (brightness, sleep timer, QR background)
```

**`terms.json` is never exported** — you re-accept the disclaimer
after a firmware upgrade.

Import **replaces the entire vault** on the device (all wallets).
When replacing an existing vault, the device shows a preview and asks
you to confirm before writing.

A backup made on a Zero restores on a Pro, and the other way round: the
vault format is the same. The Pro keypad only takes **6 digits**, so if
your Zero PIN has letters or is longer, change it to 6 digits on the Zero
before you back up, or restore on the Pro from your seed phrase instead.

### Hot-plug

Inserting or removing a stick is safe **except during an active
backup or restore** (while data is being read or written). When
waiting to pick a drive, the device rescans about once per second
(on the Zero, press **A** to rescan immediately).

### Security

The stick holds an encrypted vault. Anyone with **both** the stick
**and** your vault PIN can sign. Store the stick like a second copy
of the vault file — offline, under your control. The mnemonic remains
the canonical recovery path if you lose the stick or forget the PIN.
