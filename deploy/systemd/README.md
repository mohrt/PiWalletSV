# PiWallet bonnet — systemd units & logging

This directory ships **two** unit files for two deployment modes:

| File | Use it when | User | App location | Hardening |
| ---- | ----------- | ---- | ------------ | --------- |
| `piwallet-bonnet.service` | SD-card image (`provision-pi.sh` installs this) | `pwsv` | `/opt/piwallet` | Full (`ProtectSystem=strict`, `MemoryDenyWriteExecute`, capability set emptied, `PrivateNetwork=yes`, `ReadWritePaths=/home/pwsv/.piwallet /mnt/piwallet-usb`) |
| `piwallet-usb-mount.service` | SD-card image (`provision-pi.sh` → `step_usb_backup`) | `root` | `/opt/piwallet/.venv/bin/python -m piwallet.backup.usb_mount_socket` | Root-only Unix socket at `/run/piwallet/usb-mount.sock` (group `pwsv`) so the bonnet can mount FAT/exFAT sticks under `/mnt/piwallet-usb` despite `NoNewPrivileges=yes` |
| `piwallet-bonnet.service.example` | Developer Pi where the source tree lives in `$HOME` and you run as your own user | dev's user (`pi` etc.) | `$HOME/PiWallet` | Minimal (just `Restart=always` + log-level env vars) |

The production unit is the one that ships on the SD-card image. The example is the one you adapt by hand on a Pi you log into yourself.

The app does **not** write rotating log files under `~/.piwallet` by default — everything goes through journald.

## What uses disk?

- **`systemd` journal** — stderr/stdout from `piwallet bonnet` (and the CLI camera scan path).
- **libcamera** — many INFO lines unless `LIBCAMERA_LOG_LEVELS` is set.

At process entry, **`piwallet bonnet`** and **`piwallet qr scan-camera`** tighten defaults (`LIBCAMERA_LOG_LEVELS=*:WARN`, `PICAMERA2_LOG_LEVEL=0`). Override:

```bash
export LIBCAMERA_LOG_LEVELS=*:INFO    # louder libcamera stderr
export PICAMERA2_LOG_LEVEL=2          # louder Picamera2 console (numeric)
export PIWALLET_LOG_LEVEL=DEBUG       # Python libraries allow DEBUG
```

## Bound journal growth (recommended on SD cards)

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
sudo cp deploy/systemd/journald-piwallet.conf.example \
    /etc/systemd/journald.conf.d/piwallet.conf
sudo systemctl restart systemd-journald
```

`provision-pi.sh` installs the journald drop-in automatically when building an SD-card image.
