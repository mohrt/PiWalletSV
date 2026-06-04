### Header

The title band at the top is the overall verdict:

| Header | Meaning |
|--------|---------|
| **Air-gapped** (green) | Every check that could run passed. Safe to proceed. |
| **BREACH** (red) | At least one check failed conclusively. **Do not sign** until the leak is understood and fixed. |

### Status column

Each row shows a short slug on the left and a three-letter status on
the right:

| Glyph | Meaning |
|-------|---------|
| `OK` | Pass — this check ran and the device looks quiet. |
| `!!` | Fail — this check found a concrete leak. Treat as **BREACH**. |
| `--` | Inconclusive — the check could not run (missing sysfs node, wrong OS, etc.). Unusual on a real Pi; re-run from a shell (below). |

### Check indicators

| Check | What it proves |
|-------|----------------|
| `modules` | No Wi-Fi or Bluetooth driver modules are loaded into the kernel. |
| `rfkill` | Every radio the kernel knows about is soft- or hard-blocked. |
| `interfaces` | Only the loopback (`lo`) network interface is present. |
| `services` | `wpa_supplicant`, NetworkManager, `hciuart`, and `bluetooth` are all inactive. |
| `boot_config` | Firmware-level overlays disable Wi-Fi and Bluetooth at boot (`disable-wifi`, `disable-bt` in `config.txt`). |
| `blacklist` | The radio kernel modules are blacklisted in modprobe so they cannot reload on next boot. |

### `interfaces` and the bonnet sandbox

The bonnet app runs with a network sandbox (`PrivateNetwork=yes`), so
the **`interfaces` row only sees loopback inside the app** — even if
the host Pi had other interfaces. That is still useful: it confirms the
sandbox is intact. The other five rows inspect the host directly.

For a full host-level interface check, run from an SSH or serial shell
(not from inside the bonnet UI):

```bash
piwallet diag airgap
```

The screen footer reminds you of this when all checks are conclusive
(`shell: piwallet diag airgap`).

### Controls

| Button | Action |
|--------|--------|
| **A** | Refresh — re-run all checks. |
| **B** | Back to Settings. |
| **Hold B** | Exit the bonnet app. |

### If you see BREACH

1. **Stop.** Do not sign transactions on this device until the report
   is all-green.
2. Note which rows show `!!` — each maps to a specific leak (loaded
   driver, unblocked radio, active service, missing boot overlay, etc.).
3. If you flashed a prebuilt image, re-verify the download signature
   and re-flash. If the second flash still fails, contact
   [@PiWalletSV on X](https://x.com/PiWalletSV) or file an issue on
   [GitHub](https://github.com/mohrt/PiWalletSV/issues) with the
   failing rows.
4. Re-check after any SD-card reflash, config edit, or software update,
   and before signing anything you would regret.
