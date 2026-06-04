# `hardware/case/`

The PiWalletSV reference 3D-printable case — a 2-piece clamshell
PETG enclosure. Holds a Raspberry Pi Zero 2 W, an Adafruit 1.3"
240×240 TFT bonnet (product 4506), and an Arducam UC-346 OV5647, with
the LCD facing the operator and the camera lens facing the back of
the unit on the same optical axis.

**Use of the case design:** Printing a case for your own PiWalletSV
device is fine. Commercial sale of printed shells or the case design
files requires prior permission from the project — contact
[@PiWalletSV on X](https://x.com/PiWalletSV). The project software
remains MIT-licensed; this restriction applies to physical case goods
only (see [Disclaimer §12](../../DISCLAIMER.md#12-kits-and-case--no-unauthorized-resale)).

## Files

| File | Purpose |
|---|---|
| [`SPEC.md`](SPEC.md) | Design spec — dimensions, port locations, decision log, fit-test plan. The single source of truth for what `case.scad` is built against. |
| [`CASE-RESEARCH.md`](CASE-RESEARCH.md) | Survey of prior-art enclosures (Pi signer cases, Pi Zero + Camera v3 cases on Printables, parametric Pi Zero SCADs). What we're stealing, what we're skipping, what we corrected against datasheets. |
| [`case.scad`](case.scad) | Parametric OpenSCAD source for the two shell parts (`back_tub`, `front_lid`). All dimensions are named variables; future hardware swaps are one-line changes. |
| `refs/` | Authoritative CAD files — Adafruit's official 4506 STEP, plus a parser that extracts component centres from it. |
| `photos/` | Empirical reference photos from fit-tests (front, back, edge, exploded), plus the parts-layout photo that locks the orientation convention. |
| `stl/` | Pre-rendered STLs for users without OpenSCAD. Re-rendered when `case.scad` changes; check the commit message for the source revision. |

## Render an STL

You'll need [OpenSCAD](https://openscad.org/downloads.html) (free,
cross-platform). Open `case.scad`, then:

1. Edit the `mode` variable near the bottom of the file:
 - `mode = "tub"` — render the back tub (camera mount, Pi standoffs, lens cone, side walls, screw bosses).
 - `mode = "lid"` — render the front lid (LCD window, joystick + button cutouts, registration skirt).
 - `mode = "all"` — exploded preview for visual sanity. **Don't print this.**
2. **Render** with `F6` (a real render, not the `F5` preview — preview
 is fine for visual checks but doesn't capture all geometry).
3. **Export → STL** from the File menu.

A typical print profile for PETG on a 0.4 mm nozzle:

| Setting | Value |
|---|---|
| Layer height | 0.2 mm |
| Walls / perimeters | 4 |
| Top/bottom layers | 5 |
| Infill | 25% gyroid |
| Print speed | 40 mm/s outer perimeter, 60 mm/s inner |
| Nozzle | 240 °C |
| Bed | 75 °C |
| Cooling | 50% (PETG dislikes too much fan) |

Print orientation:

- **Back tub: open-side up.** The back wall sits on the bed; the
 side walls rise vertically; the lid-skirt step is the topmost
 feature. No supports needed for the lens cone (shallow enough for
 a single-line bridge), the screw bosses, or the standoff posts.
- **Front lid: front face down.** The LCD window's bridge across
 the bed is short enough to print without supports; the skirt
 prints upward and is self-supporting.

## Iterating the fit

3D-printed parts are never right on the first try. The process:

1. **Print the back tub first.** Drop the actual Pi (no power, no
 ribbon) onto the standoff posts and confirm the four corner
 holes align. Drop the camera onto its 4 posts and confirm the
 lens lands centred on the lens cone. Measure slack with feeler
 gauges; bump `clearance` in `case.scad` and re-render if any
 axis is tight or sloppy.
2. **Print the front lid second.** Drop it onto the tub (no screws
 yet) and confirm the skirt drops into the step with no daylight.
 Hold the lid against the actual bonnet (independently of the
 tub) and verify the LCD window, joystick, and buttons line up
 under good light. If a cutout is off, edit `lcd_active_*`,
 `joystick_centre`, or `button_*_centre` and reprint.
3. **Assemble fully** with M2.5 × 16 mm screws. Power up. Confirm
 the LCD is fully visible (no plastic intruding on the active
 area), the joystick clicks freely, both buttons are reachable,
 and the USB power plug seats fully through the top cutout.

Capture each delta in `case.scad`'s named variables, never inline
magic numbers — git blame on the SCAD file becomes the change history
for the physical revisions.

After the fit-test stabilises:

- Drop reference photos into `photos/` named `vX.Y-front.jpg`
 (etc.).
- Update `SPEC.md`'s "Confirmed dimensions" section.
- Re-render the STLs and check them into `stl/`.

## Toggling the dev vs production variant

Two flags at the top of `case.scad` change which Pi I/O ports are
exposed. The default (current) values are tuned for prototype +
service convenience:

```scad
sd_cutout_enabled = true; // microSD slot on left short edge
hdmi_cutout_enabled = false; // mini-HDMI on front edge
```

| Variant | `sd_cutout_enabled` | `hdmi_cutout_enabled` | Exposed | Sealed |
|---|---|---|---|---|
| dev (default) | `true` | `false` | PWR + OTG + microSD | HDMI |
| dev + HDMI | `true` | `true` | PWR + OTG + microSD + HDMI | — |
| production | `false` | `false` | PWR + OTG only | microSD + HDMI |

micro-USB PWR-IN and micro-USB OTG (data) are exposed in every
variant because the device needs power and the OTG cutout is the
recovery / re-flash path of last resort. Render once per variant
and ship the matching STL. The companion `stl/` directory will
hold `piwalletsv-case-prod-vX.Y.stl` and `piwalletsv-case-dev-vX.Y.stl`.

## Re-using the design for other hardware

`case.scad` is parametric. Common swaps and where to change them:

| Swap | Variables to edit |
|---|---|
| Different camera (v2, v4, future) | `camera_module_x/y/z`, `camera_lens_centre`, `camera_mount_pitch/inset`, `lens_cone_dia` |
| Different Pi model (Pi 5, Pi 4) | `mount_inset_x/y`, `mount_pitch_x/y`, plus the cavity dimensions to match the new board outline |
| Different bonnet | `lcd_window_*`, `joystick_centre`, `button_*_centre` |
| Looser/tighter fit (different printer) | `clearance` |
| Smaller travel form factor | `chin_height`, optionally drop the desk-stand chin |

If a swap is too invasive for one-line edits (e.g. a board that
isn't a 65×30 mm rectangle), copy `case.scad` to a new variant file
in this directory and only diverge on what's necessary, so the
common modules (`screw_boss`, `through_hole_at`) stay shared.

## See also

- `SPEC.md` — the canonical hardware datums and the assembly diagram.
- [`docs/build-image.md`](../../docs/build-image.md) — Step 3
 ("Assemble the hardware") in the user-facing flash-and-first-run
 guide. When the case lands, that step gets a "use the reference
 case" callout.
