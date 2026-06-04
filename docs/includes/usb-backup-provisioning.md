Sealed SD-card images built with `deploy/provision-pi.sh` include USB
backup support automatically (`step_usb_backup`):

| Component | Purpose |
|-----------|---------|
| `dosfstools`, `exfatprogs` | Mount FAT32/exFAT sticks |
| `/opt/piwallet/bin/usb-mount` | Root helper script (mount/unmount) |
| `/mnt/piwallet-usb` | Canonical mount point (`uid=pwsv`) |
| `piwallet-usb-mount.service` | Root Unix socket daemon (`/run/piwallet/usb-mount.sock`) |
| `piwallet-bonnet.service` | `After=piwallet-usb-mount.service`, `ReadWritePaths=/mnt/piwallet-usb` |

The bonnet runs with `NoNewPrivileges=yes`, so it cannot call `sudo`;
the mount daemon performs privileged mounts on its behalf.

**Dev installs** that copy only `piwallet-bonnet.service.example` do
**not** get the mount stack. Either re-run `step_usb_backup` from
`provision-pi.sh` on the Pi, or use the CLI against a manually mounted
directory (`piwallet backup export --stick-root /path/to/stick`).

Verify on a provisioned image:

```bash
systemctl is-active piwallet-usb-mount    # active
systemctl is-active piwallet-bonnet       # active
ls -la /mnt/piwallet-usb                  # exists, mode 755
```
