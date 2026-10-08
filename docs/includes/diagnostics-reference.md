### Entering diagnostics

On every boot, the device shows the **PiWalletSV logo** splash for a
few seconds. From that screen:

=== "Zero"

    | Input | Result |
    |-------|--------|
    | **Hold B** for ~5 seconds | Open the **Diagnostics** menu (factory / support entry). |
    | **A**, **timeout**, or release B before 5 s | Continue normal boot (disclaimer, vault setup, PIN, wallet list). |

=== "Pro"

    | Input | Result |
    |-------|--------|
    | **Hold a finger** on the screen for ~5 seconds | Open the **Diagnostics** menu (factory / support entry). |
    | **Timeout**, or lift your finger before 5 s | Continue normal boot (disclaimer, PIN, wallet list). |

Diagnostics runs **before** the disclaimer and vault unlock, so you can
inspect or test a device even when the vault is missing or locked.

### Diagnostics menu

| Item | Purpose |
|------|---------|
| **Device info** | Version, vault state, unlock tries left, terms version, Pi serial, hostname. |
| **Run all checks** | Automated software checks (vault file, paths, airgap helpers, etc.). |
| **Test joystick** | Zero only. Interactive direction and press test. |
| **Test buttons** | Zero only. Interactive A / B / SELECT test. |
| **Test camera** | Live camera preview. |
| **Test screen** | Fill patterns and colour bars. |
| **Restart app** | Exit cleanly so systemd restarts the signer service (~3 s). |

=== "Zero"

    Press **A** to open the highlighted item. Press **B** (short press,
    release) to leave diagnostics and continue boot.

    Sub-screens use **A/B: back** unless noted otherwise.

=== "Pro"

    Tap an item to open it. Sub-screens have **Back** at the top right
    (**Test screen** has **Back** and **Next** at the bottom).

    To leave diagnostics and continue boot, tap **Restart app**.

### Reading "Run all checks"

Each row ends with a status glyph:

| Glyph | Colour | Meaning |
|-------|--------|---------|
| **OK** | green | Check passed. |
| **!!** | red | Check failed — investigate. |
| **&ndash;** (a dash) | grey | Nothing to test / could not be verified — **not** a failure. |

A **`-` (dash) next to Wi-Fi or Network is expected and correct** on a
sealed device: the image disables the radios and network at boot, so
there is no Wi-Fi or network interface for the check to exercise. Only a
red **`!!`** indicates a real problem. For the full air-gap breakdown
(and the shell report that sees the host directly), see
[§14 Airgap status](#airgap-status).

### Restart app

**Restart app** is for recovering a stuck UI or applying a fresh process
after config changes — it does **not** reboot the whole Raspberry Pi.

=== "Zero"

    1. Select **Restart app** → **A**.
    2. Confirm twice (**A** on each prompt; **B** cancels).
    3. The screen shows *Continuing boot…*, the backlight turns off, and the
       signer process exits with code `0`.
    4. systemd restarts `piwallet-bonnet` (`Restart=always`, `RestartSec=3`).
    5. The splash runs again; unless you hold **B**, boot continues where it
       left off (disclaimer / unlock / wallet list as appropriate).

=== "Pro"

    1. Tap **Restart app**, then tap **Restart** to confirm (**Back** cancels).
    2. The signer process exits and systemd restarts `piwallet-touch`.
    3. The splash runs again; unless you hold the screen, boot continues
       where it left off (disclaimer / unlock / wallet list as appropriate).

To restart from SSH instead (developer installs only; the sealed image
has no SSH):

```bash
sudo systemctl restart piwallet-bonnet   # Zero
sudo systemctl restart piwallet-touch    # Pro
```
