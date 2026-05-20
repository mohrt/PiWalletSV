# Case design — prior-art survey

> Loop 1.5 deliverable. The world has been 3D-printing Pi Zero
> + display + camera enclosures for years; we should not invent
> anything we can borrow. This note records the survey, the bits
> worth stealing, and the bits worth deliberately not stealing.

## Reference projects

### SeedSigner (the closest analogue)

[SeedSigner](https://github.com/SeedSigner/seedsigner) is an
open-source, MIT-licensed, air-gapped Bitcoin signing device on a
Raspberry Pi Zero with a Waveshare 1.3" 240×240 LCD HAT and an
OV5647-based camera. They reach Bitcoin via animated QR exchange,
exactly the same threat model as PiWalletSV. Three case lineages
ship from their repo:

| Case | Style | Hardware | Print time | Notes |
|---|---|---|---|---|
| [Open Pill](https://github.com/SeedSigner/seedsigner/tree/main/enclosures/open_pill) | 2-piece, no screws, press-fit | none | ~2 h, no supports | Bare-bones quick-print. Optimised for "I want one tonight." |
| [Orange Pill](https://github.com/SeedSigner/seedsigner/tree/main/enclosures/orange_pill) | 2-piece + button covers + joystick topper | 4× M2.5 F-F 10 mm spacers, 4× M2.5×6 screws, 4× M2.5×12 screws | longer; SLA recommended for buttons | "Polished" variant. Buttons + joystick are SLA-printed for clean tactile features. |
| [Push Case](https://github.com/SeedSigner/seedsigner/pull/548) (PR #548, merged Jul 2024) | Newer community contribution | similar M2.5 hardware | FDM-printed, supports needed | Adds dedicated push-button caps and a refreshed silhouette. |

Community variants on Cults3D / Printables: Lil Pill, OrangeSurf,
PS4 SeedSigner, Open Pill faceplate. Orange Pill is sold pre-printed
by third parties for ~$15.

The most actionable signals from the SeedSigner Push Case PR
review thread (the youngest case in the project, so its problems
are the freshest):

- **"Camera cut-out slightly enlarged"** — they had to expand the
  camera lens cutout *after* the first fit-test. We should expect
  the same and budget for a second print pass.
- **"Models rendered in intended print orientation"** — STLs should
  be exported lying down in the orientation they print in, not the
  orientation they assemble in. Saves users from rotating in the
  slicer and avoids accidental supports.
- **"Bambu Slicer issue"** — some slicers reject hand-authored STLs
  with non-manifold geometry. Worth running our STLs through
  Meshmixer or Bambu's repair before publishing.

### Pi Zero 2 W + Camera v3 cases (same hardware as us, sans bonnet)

| Project | Source | Notable feature |
|---|---|---|
| TD's "Pi Zero 2 W with Camera Module v3 Case" | [Printables 753906](https://www.printables.com/model/753906-raspberry-pi-zero-2-w-with-camera-module-v-3-case) | Compact, optimised for v3 autofocus. Two back-cover variants (LED, plain). Tripod / wall mount. |
| Veksi154 "Pi Zero 2W Camera Case" | [Printables 1143782](https://www.printables.com/model/1143782) | Integrated GoPro-style mount. M2 heated inserts optional. |
| Ficik "Pi Zero 2 W with Pi Camera + tripod mount" | [Printables 750948](https://www.printables.com/model/750948-raspberry-pi-zero-2-w-with-pi-camera-and-tripod-mo) | Designed for the short 38 mm camera ribbon (we don't use this; we need ~150 mm for the U-turn). |
| Itzner "One-Piece Pi Zero 2 W + Pi Camera case + articulating wall mount" | [Printables 139626](https://www.printables.com/model/139626-one-piece-raspberry-pi-zero-2-w-pi-camera-case-and) | Print-in-place (PiP) hinge. M2 nut pockets. |
| NoobInventor "Pi Zero 2W camera and headers case" | [Printables 1551318](https://www.printables.com/model/1551318-raspberry-pi-zero-2w-camera-and-headers-case/user-gcodes) | Multi-version: accepts v1, v2, or v3 cameras. |

None of these stack a bonnet on top of the Pi *and* mount a camera
on the rear with a CSI U-turn — that's the gap PiWalletSV's case
fills.

### Parametric Pi Zero cases

| Project | Source | Notable pattern |
|---|---|---|
| paul1522 "Raspberry Pi Zero Case" (OpenSCAD) | [GitHub](https://github.com/paulgeneres/OpenSCAD-Projects/blob/master/Raspberry%20Pi%20Zero%20Case.scad) | Encodes Pi port locations as data (`hdmi = [[12.4, ...], [15.0, 3.3]]`). Confirms our Pi-Zero hole pattern (3.5 mm inset, 58×23 pitch). |
| asciipip "slim-raspberry-pi-case" | [Codeberg](https://codeberg.org/asciipip/slim-raspberry-pi-case) | Press-fit, no fasteners. Parametric wall thickness + tolerance. |
| Ultimate Box Maker | [Hackaday](https://hackaday.com/2018/03/02/printed-it-custom-enclosure-generator/) | General-purpose enclosure generator with PCB-import support. Overkill for us but a good reference for naming conventions. |
| scross01 "ST7789 TFT Display Screen Case" | [Printables 1068697](https://www.printables.com/model/1068697-st7789-tft-display-screen-case) | Parametric Fusion model for ST7789 displays with very tight LCD-window tolerances. Confirms our 0.5 mm overshoot per side is on the looser side of the convention. |

## What we'll steal

| From | Into our design | Why |
|---|---|---|
| **SeedSigner two-tier strategy** (Open Pill / Orange Pill) | Our `case.scad` already toggles `sd_cutout_enabled`; we'll add a second toggle for `button_covers_enabled` later so a polished variant can be a one-line edit. | Lets us ship a "fast print, no extras" variant alongside a "polished SLA-button" variant from one source. |
| **Push Case lesson: expect to enlarge cutouts after fit-test** | `clearance` already raised from a typical 0.2 mm to 0.4 mm. Loop 3 will likely push it to 0.5 mm. | Cheap correction; expensive surprise. |
| **Push Case lesson: render STLs in print orientation** | Add a `print_orientation` mode to `case.scad` that lays each part flat-side-down for export. | UX for downstream printers. |
| **paul1522: encode port locations as data** | Already done — bonnet button positions, camera hole positions, and lens centre are all named vectors. | Future hardware swaps stay one-line. |
| **NoobInventor: multi-camera support** | Plan a `camera_variant = "v3" \| "v2" \| "v1"` switch later; for now the SCAD only supports v3 per the user's choice. | Cheap to add, expensive to retrofit. |
| **Itzner: M2 nut pockets** | Worth considering for the camera mount as a v0.2 tweak: instead of self-tapping into PETG bosses, embed an M2 brass nut. | Brass nut survives multiple disassembly cycles. PETG self-tap doesn't. |

## What we'll deliberately *not* steal

| From | Why we're skipping |
|---|---|
| **SeedSigner Open Pill 2-piece press-fit** | Press-fit is brittle on FDM and impossible to re-open cleanly. We chose 4× M2.5 screws on purpose; not revisiting. |
| **SeedSigner Orange Pill SLA buttons + joystick topper** | Adds an SLA printer to the bill of materials. Alpha is FDM-only. Revisit once the geometry stabilises. |
| **Itzner one-piece print-in-place hinge** | Cute, but no good way to integrate a camera with a CSI U-turn into a hinged shell. |
| **Veksi154 GoPro mount** | Adds a feature the threat model doesn't need (mounted surveillance). Lanyard hole + desk-stand chin already cover the placement scenarios we care about. |
| **paul1522 rubber band grooves / port labels** | We don't have port labels worth engraving (only PWR), and rubber bands aren't the security story we're telling. |

## Critical corrections applied to `case.scad` from this survey

The Raspberry Pi Camera Module 3 mechanical drawing
([RP-008153](https://pip.raspberrypi.com/documents/RP-008153-DS-camera-module-3-standard-mechanical-drawing.pdf))
contradicted the from-memory numbers I'd put in the first SCAD pass.
Already fixed:

| Field | Old (wrong) | New (per datasheet) |
|---|---|---|
| `camera_mount_pitch` | `[21.0, 12.5]` | `[10.8, 10.8]` |
| `camera_mount_inset` | `[2.0, 5.75]` (hard-coded) | derived: `(module - pitch) / 2` = `[7.1, 6.6]` |
| `camera_lens_centre` | `[12.5, 11.5]` | `[14.4, 12.5]` |
| Bonnet outline | `65.0 × 30.0` | `65.5 × 30.6` (Adafruit's stated overall) |

The bonnet button + joystick coordinates (`joystick_centre`,
`button_a_centre`, `button_b_centre`) are still best-effort. The
authoritative source is the Adafruit EagleCAD PCB file at
[adafruit/Adafruit-1.3in-Color-TFT-Bonnet-PCB](https://github.com/adafruit/Adafruit-1.3in-Color-TFT-Bonnet-PCB);
opening that and reading the silkscreen positions is a Loop 3
nice-to-have. Until then: hold the printed front-shell against the
real bonnet under good light before trusting the cuts.

## Open questions for Loop 3

1. **Brass M2 inserts vs PETG self-tap for the camera mount.** Self-
   tap is fine for ~5 disassembly cycles in PETG; beyond that, threads
   strip. If we expect users to ever take the camera off, we should
   switch.
2. **Translucent PETG window over the LCD?** Currently a through-cut
   with a 1 mm bezel margin. A 0.6 mm-thick translucent insert would
   protect the LCD from impact at the cost of a slight haze. Probably
   not worth the complexity for v0.1.
3. **Heat dissipation.** None of the surveyed cases vent the Pi
   Zero, and the Zero 2 W's quad-A53 runs warm under sustained
   camera workloads. We should monitor `vcgencmd measure_temp` on
   the assembled prototype before committing to the sealed shell.
4. **EMI shielding.** A conductive paint coating inside the back
   shell would be a defence-in-depth signal alignment with our
   "no radios, ever" stance. Not on the v0.1 path; flag for v0.2.
