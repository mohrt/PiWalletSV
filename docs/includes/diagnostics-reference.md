### Entering diagnostics

On every boot, the bonnet shows the **PiWalletSV logo** splash for a
few seconds. From that screen:

| Input | Result |
|-------|--------|
| **Hold B** for ~5 seconds | Open the **Diagnostics** menu (factory / support entry). |
| **A**, **timeout**, or release B before 5 s | Continue normal boot (disclaimer, vault setup, PIN, wallet list). |

Diagnostics runs **before** the disclaimer and vault unlock, so you can
inspect or test a device even when the vault is missing or locked.

### Diagnostics menu

| Item | Purpose |
|------|---------|
| **Device info** | Version, vault state, unlock tries left, terms version, Pi serial, hostname. |
| **Run all checks** | Automated software checks (vault file, paths, airgap helpers, etc.). |
| **Test joystick** | Interactive direction and press test. |
| **Test buttons** | Interactive A / B / SELECT test. |
| **Test camera** | Live camera preview. |
| **Test screen** | Fill patterns and colour bars. |
| **Restart app** | Exit cleanly so systemd restarts the bonnet service (~3 s). |

Press **A** to open the highlighted item. Press **B** (short press,
release) to leave diagnostics and continue boot.

Sub-screens use **A/B: back** unless noted otherwise.

### Restart app

**Restart app** is for recovering a stuck UI or applying a fresh process
after config changes — it does **not** reboot the whole Raspberry Pi.

1. Select **Restart app** → **A**.
2. Confirm twice (**A** on each prompt; **B** cancels).
3. The screen shows *Continuing boot…*, the backlight turns off, and the
   bonnet process exits with code `0`.
4. systemd restarts `piwallet-bonnet` (`Restart=always`, `RestartSec=3`).
5. The splash runs again; unless you hold **B**, boot continues where it
   left off (disclaimer / unlock / wallet list as appropriate).

To restart from SSH instead:

```bash
sudo systemctl restart piwallet-bonnet
```
