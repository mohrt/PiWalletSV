# PiWallet bonnet logging (journald + libcamera)

The app does **not** write rotating log files under `~/.piwallet` by default.

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

## systemd unit snippet

See `piwallet-bonnet.service.example` — copy/adapt to `/etc/systemd/system/` for production.
