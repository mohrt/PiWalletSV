# HAMTYSAN 5" display case

Two-piece PETG clamshell for the
[HAMTYSAN HCIG050V.CP1](https://www.amazon.com/dp/B0F4DFBVS8) —
5-inch 800×480 IPS capacitive touch display.

## Parts

| Part | What it does |
|---|---|
| `back_shell` | Tray; PCB screws onto 5 mm standoff posts; M3 corner bosses accept heat-set inserts |
| `front_bezel` | Frame; LCD window 109 × 65.8 mm; registration skirt; clamps to shell with M3 screws |

## Print

Open `case.scad` in [OpenSCAD](https://openscad.org/).

| `mode` | Part | Print orientation |
|---|---|---|
| `"shell"` | Back tray | Open face **up**, no supports |
| `"bezel"` | Front frame | Front face **down**, no supports |
| `"all"` | Both on one plate | — |
| `"preview"` | Exploded view | Don't export |

**PETG settings (0.4 mm nozzle):** 0.2 mm layers, 4 walls, 25% gyroid infill.

## Assembly

1. Press **M3 heat-set inserts** into the four corner bosses (soldering iron, 230 °C).
2. Screw PCB onto standoff posts with **4× M2.5 × 8 mm** screws.
3. Route HDMI + USB cables through the side port slot.
4. Drop bezel onto shell (skirt aligns it automatically).
5. Fasten **4× M3 × 10 mm** screws through bezel corners into heat-set inserts.

## Key variables to tune after first fit-test

```scad
// PCB mount hole positions
m25_inset_x = 4.5;
m25_inset_y = 4.5;

// Port slot — slide up/down until cables exit cleanly
port_edge   = "right";   // or "left"
port_slot_y = 42.0;      // centre along PCB y
port_slot_z = 8.5;       // centre height

// Optional features
vesa_enabled = true;     // VESA 50×50 holes on back plate
vent_enabled = true;     // passive cooling slots
```

See [`SPEC.md`](SPEC.md) for full fit-test checklist and fastener BOM.
