# Next release ideas

Backlog under consideration for a future PiWalletSV release. Not a commitment or schedule.

## PIN

- [ ] Allow longer PIN, up to **16 characters** (minimum remains **6**)
- [ ] Allow letters and numbers; in the PIN picker, show **digits first, then letters**
- [ ] Allow **upper-case letters**; press **joystick center** to toggle upper/lower

### PIN entry UI (bonnet)

Follow the wallet naming pattern (`piwallet/ui/label_entry.py`): editable cells on top, **full PIN as plain text underneath** so the value stays readable even when boxes are small or only a window of cells is visible.

- Start with **6 empty cells** (today’s default).
- **RIGHT on the last cell** appends another empty `_` slot (cap **16**).
- **B**: if length **> 6**, delete the current cell (shrink by one, floor at 6). If length is **6**, clear the digit in the current slot (today’s backspace — do not remove the cell).
- **A** confirms only when every cell is filled and length ≥ 6.
- Cell row: keep current-ish cell size for the focused digit; when the row would overflow (~7+ at 30px cells), **window/scroll** so the cursor stays on-screen (same as label entry) — do not require wrapping.
- **Preview line** under the cells: the entire PIN in plain text (empty slots as `_`), always showing the full value. If boxes are hard to read at length, the preview is the source of truth for “what did I type?”
- 16 chars at ~12px fits one centered preview line on 240px width with room to spare.

## Signing / UX

- [ ] After reading an unsigned tx, show the **send (destination) address** on the Pi screen before the user accepts/signs

## Diagnostics

- [ ] On network checks, show **`disabled`** instead of **`-`** (airgap / no interface expected)

## Notes for implementers

- PIN policy today: exactly **6 digits** in `piwallet/core/vault.py` (`_validate_pin`). Bonnet PIN UI (`piwallet/ui/pin_entry.py`) and first-boot flows need matching charset, order, case toggle, growable slots, and a plain-text preview line. UI already allows length 4–12 but vault enforces 6.
- Closest pattern: `piwallet/ui/label_entry.py` (RIGHT past end grows, windowed cell row, preview line under the cells).
- Offline brute-force cost grows with charset/length (security upside of alphanumeric + longer PINs).
- Send-address confirm: after proposal decode in the bonnet sign flow, show the recipient before confirm.
- Diagnostics: docs already explain that `-` for Wi-Fi/Network is expected (`docs/includes/diagnostics-reference.md`); update the display string and that reference together.
