### Opening Settings

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

There is **no button or gesture to exit the bonnet app** from the UI.
The signer runs under systemd (`Restart=always`); power off externally
when you need the device off.

### Preferences

From the hub, select **Preferences**.

Use **UP/DOWN** to move the cursor. On **Brightness** and **Sleep timer**,
use **LEFT/RIGHT** to cycle through the allowed values.
Press **A** on a value row to **save** (you stay on Preferences).
Press **B** to return to the Settings hub.

| Row | What it does |
|-----|----------------|
| **Brightness** | Backlight level (preset percentages). |
| **Sleep timer** | Minutes until the panel blanks when idle (`Off` disables). |

### Maintenance

From the hub, select **Maintenance**.

Press **A** on an action row to open that sub-screen.
Press **B** to return to the Settings hub.

| Row | What it does |
|-----|----------------|
| **Change PIN** | Re-enter the current PIN, then set a new vault PIN. |
| **Airgap status** | Live Wi-Fi / Bluetooth / Network check — see [§ Airgap status](#airgap-status). |
| **USB backup** | Export or import the encrypted vault to a USB stick — see [§ USB backup](#usb-backup). |
| **About** | Version, website, wallet count, Pi serial, and hostname. |
| **Factory reset** | Factory wipe for resale or hand-off — see below. |

Sub-screens use **B** to return to **Maintenance** (not the wallet list).

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
while keeping others, use the CLI (`piwallet vault remove`) — see
[§ Wipe a wallet](#10-wipe-a-wallet--wipe-the-vault).
