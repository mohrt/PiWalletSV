### Header

The title band at the top is the overall verdict:

| Header | Meaning |
|--------|---------|
| **Air-gapped** (green) | Every check that could run passed. Safe to proceed. |
| **BREACH** (red) | At least one check failed conclusively. **Do not sign** until the leak is understood and fixed. |

### Status column (bonnet)

Each row shows a friendly label on the left and a plain-English status on
the right:

| Status | Meaning |
|--------|---------|
| **Disabled** (green) | That radio or network path looks off — no leak found. |
| **Active** (red) | Something is live — treat as **BREACH**. |
| **Unknown** (grey) | Could not verify from the bonnet app alone. Re-flash or run the shell diagnostic below. |

On a healthy sealed device you should see **Disabled** on all three rows
and a green **Air-gapped** header.

The CLI still uses compact glyphs (`OK`, `!!`, `--`) in
``piwallet diag airgap`` output.

### Check rows (bonnet UI)

The Settings screen shows **three summary rows**. Each rolls up several
technical checks so you do not need to read kernel module names:

| Row | What it covers |
|-----|----------------|
| **Wi-Fi** | No Wi-Fi driver loaded; radios blocked; Wi-Fi services off; firmware disables Wi-Fi at boot; modules blacklisted. |
| **Bluetooth** | Same checks for Bluetooth (`hciuart`, `bluetooth`, etc.). |
| **Network** | Only the loopback interface is present **inside the bonnet app's network sandbox** (`PrivateNetwork=yes`). |

A green **Network** row confirms the bonnet sandbox is intact. It does
**not** by itself prove the host Pi has no other interfaces — for that,
run the full six-check report from a shell (below).

On some older images, **Wi-Fi** and **Bluetooth** could show **Unknown**
when rfkill sysfs was unreadable inside the bonnet sandbox even though
radios were actually disabled. Current firmware shows **Disabled** when
every conclusive sub-check passes.

### Full report from a shell

`piwallet diag airgap` lists six technical rows (`modules`, `rfkill`,
`interfaces`, `services`, `boot_config`, `blacklist`) and sees the host
directly. Use it periodically and whenever the on-screen result looks
wrong:

```bash
piwallet diag airgap              # table; exit 1 on BREACH
piwallet diag airgap --json       # machine-readable
```

See [Operate § Airgap diagnostic](operate.md#airgap-diagnostic) and
[CLI § `piwallet diag airgap`](cli.md#piwallet-diag-airgap).

### Controls

| Button | Action |
|--------|--------|
| **A** | Refresh — re-run all checks. |
| **B** | Back to Maintenance. |

### If you see BREACH

1. **Stop.** Do not sign transactions on this device until the report
   is all-green.
2. Note which rows show **Active** — **Wi-Fi** or **Bluetooth** failures map
   to drivers, radios, services, boot overlays, or blacklists;
   **Network** failures usually mean the bonnet sandbox is broken.
3. If you flashed a prebuilt image, re-verify the download signature
   and re-flash. If the second flash still fails, contact
   [@PiWalletSV on X](https://x.com/PiWalletSV) or file an issue on
   [GitHub](https://github.com/mohrt/PiWalletSV/issues) with the
   failing rows (or `piwallet diag airgap --json` output).
4. Re-check after any SD-card reflash, config edit, or software update,
   and before signing anything you would regret.
