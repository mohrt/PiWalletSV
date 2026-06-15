# HAMTYSAN 5" case — mechanical spec

Two-piece clamshell for the **HAMTYSAN HCIG050V.CP1**
([Amazon B0F4DFBVS8](https://www.amazon.com/dp/B0F4DFBVS8)).

## Confirmed hardware dimensions

| Dimension | Value | Notes |
|---|---|---|
| PCB outline | 121.11 × 77.93 mm | Correct 5-inch dimensions |
| Active area | 108.00 × 64.80 mm | Pixel area |
| PCB depth | ~5.7 mm glass + PCB; ~12 mm w/ rear components | Minimum 12 mm internal depth |
| Ports | HDMI + 2× micro-USB on right side | No audio jack; top→bottom: HDMI, USB TOUCH, +5V_IN |
| Mount holes | M2.5, four corner tabs | |

## Assembly

```
  ┌──────────────┐
  │ front_bezel  │  ↑ same 4× M2.5 × 12 mm screws go through bezel + PCB + standoff
  ├──────────────┤
  │    display   │  M2.5 mounting holes align with standoff posts
  ├──────────────┤
  │  back_shell  │  4× M2.5 standoff posts with blind holes
  └──────────────┘
```

**Screw path:** M2.5 × 12 mm pan-head screw from bezel front face → through bezel clearance hole → through PCB M2.5 mounting hole → threads into standoff blind hole. The bezel front face has a 5.2 mm × 1.5 mm circular recess so the screw head sits flush. Exterior corners are fully solid — no holes visible anywhere outside.

## Internal cavity

| Axis | Value | Notes |
|---|---|---|
| Width | 122.11 mm | PCB + 0.5 mm clearance per side |
| Height | 78.93 mm | PCB + 0.5 mm clearance per side |
| Depth | 12.0 mm | Clears rear components |

## Back plate

| Property | Value |
|---|---|
| Thickness | 5.0 mm (`back_plate`) |
| Side walls | 2.4 mm (`wall`) |
| Front rim | 2.4 mm (`wall`) |
| Total shell depth (z) | 19.4 mm |

The back plate is thicker than the side walls specifically to provide enough material for the M3 hex-nut pockets (2.4 mm nut + 0.3 mm clearance + 2.3 mm solid floor).

## LCD window

| Dimension | Value |
|---|---|
| Width | 109.0 mm | Active area + 0.5 mm clearance per side |
| Height | 65.8 mm | Active area + 0.5 mm clearance per side |

## Port cutouts (right side wall)

From PCB photo, top→bottom on the left edge of the PCB (= right side of the front):

| Port | along_edge (Y) | depth (Z) | Centre Y from PCB bottom | Centre Z from back plate |
|---|---|---|---|---|
| HDMI_IN | 18.0 mm | 12.5 mm | 57.0 mm | 7.5 mm |
| USB_TOUCH | 11.5 mm | 6.5 mm | 36.0 mm | 7.5 mm |
| +5V_IN | 11.5 mm | 6.5 mm | 16.0 mm | 7.5 mm |

HDMI opening spans y ≈ 50–68 mm in shell coords; the nearest M2.5 standoff boss is at y ≈ 73 mm — 5 mm clearance.

**Tune `_y` values after first fit-test.** Plug a cable in and mark where it exits.

## Fasteners

| Qty | Part | Purpose |
|---|---|---|
| 4 | M2.5 × 12 mm pan-head screw | Bezel + PCB → shell standoffs — one screw does both |

## Back plate features

- **VESA 50 × 50 mm** pattern: four M3 clearance holes for a separate desk stand
  (set `vesa_enabled = false` to omit)
- **Vent slots**: two rows of 4 × 20 mm slots for passive cooling of the driver IC
  (set `vent_enabled = false` to omit)

## Fit-test checklist

1. Print `back_shell` (open face up, no supports needed).
2. Drop bare PCB onto the 4 standoff posts; confirm it sits flat and the
   M2.5 holes line up. Adjust `m25_inset_x/y` if not.
3. Plug HDMI and USB cables. Confirm they exit cleanly.
   Adjust `hdmi_y`, `usb_touch_y`, `usb_pwr_y` if needed.
4. Print `front_bezel` (face down, no supports needed).
5. Confirm LCD window fully reveals the active area (no pixel clipping).
   Adjust `lcd_win_x0/y0` or `lcd_offset_*` if needed.
6. Drop bezel skirt into shell rim (self-registering).
7. Drive 4× M2.5 × 12 mm screws through the recessed bezel holes, through the PCB
   mounting holes, and into the standoff blind holes.
