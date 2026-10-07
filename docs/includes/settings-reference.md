### Opening Settings

=== "Zero"

    From the **wallet list**, press **B** (short press) to open **Settings**.
    The hub offers **Preferences** and **Maintenance**.

    Press **B** on the hub to return to the wallet list. That is the **only**
    way to leave Settings altogether.

    **Navigation:** `B` always moves up one level:

    | You are on | B goes to |
    |------------|-----------|
    | Sub-flow (airgap, about, USB menu, change PIN, …) | **Maintenance** |
    | **Maintenance** or **Preferences** | **Settings** hub |
    | **Settings** hub | **Wallet list** |

=== "Pro"

    On the home screen, tap **Settings** (top row, next to **Add** and
    **Restore**). The hub offers **Preferences** and **Maintenance**.

    **Back** (top right) always moves up one level: from a sub-screen to
    **Maintenance**, from **Maintenance** or **Preferences** to the hub, and
    from the hub to the wallet list.

There is **no button or gesture to exit the signer app** from the UI.
The signer runs under systemd (`Restart=always`); power off externally
when you need the device off.

### Preferences

| Row | What it does |
|-----|----------------|
| **Brightness** | Backlight level (preset percentages). |
| **Sleep timer** | Minutes until the panel blanks when idle (`Off` disables). |

=== "Zero"

    From the hub, select **Preferences**.

    Use **UP/DOWN** to move the cursor. On **Brightness** and **Sleep timer**,
    use **LEFT/RIGHT** to cycle through the allowed values.
    Press **A** on a value row to **save** (you stay on Preferences).
    Press **B** to return to the Settings hub.

=== "Pro"

    From the hub, tap **Preferences**, then a row.

    - **Brightness:** tap **Dim** or **Bright**, then **Save**.
    - **Sleep timer:** tap **Off**, **1 min**, or **5 min**, then **Save**.

    **Cancel** leaves the value unchanged. When the panel blanks, tap the
    screen to wake it; you re-enter your PIN if the wallet was unlocked.

### Maintenance

| Row | What it does |
|-----|----------------|
| **Change PIN** | Re-enter the current PIN, then set a new vault PIN. Zero: **6–16** letters/digits (existing 6-digit PINs remain valid). Pro: **6** digits. |
| **Airgap status** | Live Wi-Fi / Bluetooth / Network check — see [§ Airgap status](#airgap-status). |
| **USB backup** | Export or import the encrypted vault to a USB stick — see [§ USB backup](#usb-backup). |
| **About** | Version, website, wallet count, Pi serial, and hostname. |
| **Factory reset** | Factory wipe for resale or hand-off — see below. |

=== "Zero"

    From the hub, select **Maintenance**. Press **A** on an action row to
    open that sub-screen. Sub-screens use **B** to return to **Maintenance**
    (not the wallet list); **B** on Maintenance returns to the hub.

=== "Pro"

    From the hub, tap **Maintenance**, then a row. **Back** on a sub-screen
    returns to **Maintenance**; **Back** on Maintenance returns to the hub.

### Factory reset

**Maintenance → Factory reset** erases all signer state on the device:

- encrypted vault (`vault.bin`, securely overwritten),
- display settings (`settings.json`),
- disclaimer acceptance (`terms.json`).

Funds remain on the blockchain; only your **seed phrase** can recover
them. The flow asks for **double confirmation**, then your **vault PIN**,
then shows *Factory reset complete* and returns to first-setup (disclaimer → new
PIN) on the next boot loop.

Use this when selling or gifting the hardware. To wipe only one wallet
while keeping others, use **Erase from Pi** on that wallet's menu, or the
CLI (`piwallet vault remove`) — see
[§ Wipe a wallet](#10-wipe-a-wallet-wipe-the-vault).
