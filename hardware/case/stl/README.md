# Pre-rendered case STL (round 1)

Fit-tested on round-one kit hardware:

- Raspberry Pi **Zero / Zero W / Zero WH**
- Adafruit **4506** 1.3″ bonnet
- **OV5647** camera (ArduCam / Pi Camera module footprint)

## Download

| File | Contents |
|------|----------|
| **[`piwalletsv-case-round1-all.stl`](piwalletsv-case-round1-all.stl)** | Back tub + front lid + 2× button caps on one plate |

**Variant baked in** (matches current [`../case.scad`](../case.scad)): microSD slot
and mini-HDMI cutouts exposed (`sd_cutout_enabled` + `hdmi_cutout_enabled`).

Source parametric model: [`../case.scad`](../case.scad) · full print profile:
[`../README.md`](../README.md).

## Slicer setup

The plate contains **four bodies**. In your slicer, **split by object** (or
equivalent) and orient each part:

| Body | Orientation |
|------|-------------|
| Back tub | **Open side up** (back wall on bed) |
| Front lid | **Front face down** (LCD window bridged on bed) |
| Button caps (×2) | Flat; use a **brim** if the flange lifts |

**Hardware:** four **M2.5 × 16 mm** screws (corner bosses).

**Material:** PETG recommended (see [`../README.md`](../README.md)).

## Re-export (maintainers)

```bash
cd hardware/case
openscad -o stl/piwalletsv-case-round1-all.stl -D 'mode="all"' case.scad
```

Use **F6** (full render), not preview-only export.
