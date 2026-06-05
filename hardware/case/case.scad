// PiWalletSV reference case — parametric OpenSCAD source.
//
// Two-piece clamshell (skirt + M2 corner screws), SeedSigner-style:
//   back_tub  — deep half: camera + Pi standoffs, lens cone, I/O cutouts.
//   front_lid — flat half: LCD window, joystick + button holes.
//   button_cap — flanged pad; actuates via lid platform pocket (×2).
//
// Render modes: mode = "tub" | "lid" | "cap" | "caps" | "lid_caps" | "all" | "preview"
// Loop 40: M2 × 6 mm pan-head corner screws; 4.8 × 4.8 mm square pillars at corners.
// Loop 41: tighter button lid ports + button centres +0.5 mm Y.
//   tub      — back tub only
//   lid      — front lid only (flipped for print)
//   caps     — 2× button caps (wide spacing — use brim in slicer)
//   cap      — single button cap (reprint one)
//   lid_caps — lid (flipped) + 2 caps nested in LCD window
//   all      — tub + lid side-by-side; caps nested in lid window (export this)
//   preview  — exploded tub + lid for OpenSCAD sanity only (don't print)
//
// Loop 39: bezel inner edge flush with window cutout (23.5 mm); depth still 1.36 mm.
// Loop 38: restore flange ring width (lcd_bezel_border) — Loop 37 only shortens depth.
// Loop 37: inner flange depth 1.36 mm (measured 1.86 − 0.5); not border width.
// Loop 36: remove inner bezel collar + glass clearance pocket — teeter on glass.
// Loop 35: inner bezel depth −1 mm (0.5) — was hitting LCD glass, lid teetered.
// Loop 34: deeper joy skirt pocket + stem bore — silicone nub held lid up.
// Loop 33: bonnet/Pi −1.5 mm in x for CSI ribbon; camera + lens fixed.
// Loop 32: CM3 in same case height — camera posts stay 3.0 mm; ribbon derived.
// Loop 31: removed snap brim + tub grooves — lips peeled off lid, tub split.
// Loop 30: button lid bore chamfers + cap pocket flare — FDM stepped holes.
// Loop 28: removed lid engravings (wordmark + shield) — unreadable on FDM test.
// Loop 25: window nudge, even bezel, PWR LED hole, snap brim, taller caps.
// Loop 24: joystick frustum through full slab — was 8.5 mm straight (bound on tilt).
// Loop 19: LCD from active area; front_slack 0.2; joy skirt +0.7.
// Loop 7–16: prior button/lid/joystick iterations (superseded).
//
// Loop 6: LCD +2.5 x, USB z, HDMI width, Orange Pill caps (face-down)
// Loop 5: tub USB spacing, SD offset, silicone pocket
//
// Hardware targets: Raspberry Pi Zero 2 W + Adafruit 1.3" 240×240
// TFT bonnet (product 4506) + Pi Camera Module 3 / Arducam OV5647
// (standard 25.1×24.2 mm footprint). See SPEC.md for datums.
//
// Every dimension is a named variable. Future hardware swaps (Pi 5,
// different camera, different bonnet) should be a one-line change in the
// "Primitives" section. Derived dimensions live below in "Derived"
// and are computed from primitives only — never edit them directly.
// See SPEC.md for the design rationale and the canonical hardware
// datums this model is built against.
//
// Coordinate convention:
//   x = horizontal (left/right), aligned with bonnet's long edge
//   y = vertical   (up/down on the operator face)
//   z = depth     (front-to-back, LCD-side positive)
//
// Origin sits at the bottom-left rear corner of the back tub.


// =====================================================================
// Primitives
// =====================================================================

// FDM clearance — every internal cavity grows by this amount on each
// side relative to the nominal hardware size. Bumped from a typical
// 0.2 mm because the bonnet's mounting headers are tight and PETG
// shrinks slightly on cooling.
clearance = 0.4;

// Wall thickness for both shells. 2.4 mm is the sweet spot for PETG:
// thick enough not to crack on a drop, thin enough to keep the case
// under 30 mm depth.
wall = 2.4;

// Stack-up depths driving the cavity height (z).
//
// ribbon_under_pi: CSI flex U-turn slot — derived below from cavity_z_budget
//   so a taller camera (CM3) fits without growing case height.
// pi_pcb_to_lcd_top: measured 2026-05-15 with the bonnet fully
//   seated on the Pi GPIO header — Pi PCB BOTTOM face to LCD glass
//   TOP face, header pin protrusion under the Pi excluded.
// front_slack: gap between LCD top and lid inner face (LCD clearance only).
// lid_seat_raise: extra tub height so the press-fit lip sits higher; bonnet
//   stack unchanged on the floor. Loop 17 fit-test: +1 mm clears joystick
//   rubber + button cap preload when lid is fully seated.
// cavity_z_budget: internal stack depth after Loop 17 trims (ov5647 reference
//   stack with 5 mm ribbon). Held constant — taller cameras eat ribbon slack.
cavity_z_budget   = 30.34;
pi_pcb_to_lcd_top = 14.0;
front_slack       = 0.2;
lid_seat_raise    = 1.0;

// Lid retention — registration skirt for alignment + four M2 corner
// screws (Loop 40). Skirt registers the lid; screws clamp it.
lid_skirt_h    = 4.0;
lid_skirt_step = 1.2;

// Long-edge lanes between the cavity and the outer wall. Now that
// there are no screw bosses, the lanes can be zero — the outer wall
// (2.4 mm) is all the rim we need.
//
// FRONT (low y) carries the Pi I/O cutouts; BACK (high y) is sealed.
// Bumping chin_height adds material to the BACK edge only, where a
// desk-stand chin / back-rake will live in a later iteration so the
// device tilts away from the front cables.
chin_height = 0.0;
front_lane  = 0.0;
back_lane   = chin_height;

// The bonnet/Pi PCB outline. Pi Zero 2 W is 65 × 30; the bonnet
// extends slightly past it (Adafruit lists 65.5 × 30.6).
bonnet_pcb_x = 65.5;
bonnet_pcb_y = 30.6;

// Y-axis clearance gaps between the Pi/bonnet PCB and the case walls.
// Using purpose-driven asymmetric gaps (Loop 3) instead of the old
// symmetric formula (+1 mm padding per side) reduces case_y by 1.6 mm
// while keeping the Pi visually centred (0.2 mm off-centre).
//
// pi_io_gap: front (low-y) gap — PCB I/O edge to front wall inner face.
//   0.4 mm = FDM clearance only; USB/HDMI port bodies extend into this
//   gap and through the front wall for the ports-through-wall design.
// pi_back_clearance: rear (high-y) gap — bonnet back edge to back wall.
//   0.8 mm = clearance for GPIO header edge + FDM tolerance.
pi_io_gap         = 0.4;
pi_back_clearance = 0.8;

// Bonnet + Pi stack shift in case-frame x (negative = toward left / low-x wall).
// Decoupled from camera anchor — gives CSI ribbon room at the Pi's right edge.
// LCD window, joystick, buttons, USB/HDMI/LED cutouts move with the bonnet.
bonnet_x_shift    = -1.5;

// Pi corner mounting holes — 58 × 23 mm pitch centred on the PCB.
mount_inset_x = 3.5;
mount_inset_y = 3.5;
mount_pitch_x = 58.0;
mount_pitch_y = 23.0;

// LCD geometry. lcd_module is the glass outline; lcd_active_area is
// the lit-pixel rectangle, smaller than the glass; lcd_active_area_offset
// is the bottom-left of the visible pixels in PCB-frame. All three
// are direct calipered measurements (2026-05-15).
lcd_module             = [26.12, 26.12];
lcd_active_area        = [23.74, 23.74];
lcd_active_area_offset = [19.0,   5.0];
// LCD window through-hole — size + shift from lit-pixel centre in bonnet frame.
// +x = right; +y = toward top (high-y / back edge on bonnet).
lcd_window_eff_x = 23.5;
lcd_window_eff_y = 23.5;
lcd_window_eff_x_offset = 1.5;   // Loop 25: +1 mm right vs Loop 23
lcd_window_eff_y_offset = 0.0;   // Loop 25: +1 mm down (low-y) vs Loop 23

// Joystick + button cutouts. Centres in PCB-frame, pulled from
// Adafruit's official 4506 STEP file (Adafruit_CAD_Parts repo);
// agree with calipers to within 0.5 mm.
//
// The 4506 ships with a SQUARE silicone cap that surrounds the
// SKQUBAE010 joystick switch and presents a tall round stem to the
// user. Measured 2026-05-16:
//   - silicone base:  12.2 × 12.2 × 3.4 mm, sits on the bonnet PCB
//   - stem:           Ø 7.22 mm × ~7 mm tall, rises from the base
// Cap-top sits about 10.4 mm above the bonnet PCB, well above the
// LCD plane, so the stem has to poke through the front lid.
//
// The 5-way switch underneath the cap pivots roughly 2-3 mm above
// the PCB. At ~15° tilt that sweeps the stem laterally by ~0.8 mm
// at the lid inner face and ~1.4 mm at the outer face, so the lid
// hole is widened with a frustum (narrow inside, wider outside) to
// give the cap room to tilt without binding on the hole edge.
//
// joystick_hole_dia_inner — at lid inner face (stem + tilt sweep + clearance).
// joystick_hole_dia_outer — at outer face (~1.4 mm lateral sweep + clearance).
// Frustum through the full slab; shallow outer dish removed (was 0.5 mm only).
joystick_hole_dia_inner = 9.5;
joystick_hole_dia_outer = 11.0;
joystick_centre     = [ 8.128, 13.462];   // STEP: SKQUBAE010:SW3
button_a_centre     = [53.848,  9.271];   // STEP: 6MM_SMT:SW2 (GPIO 5)
button_b_centre     = [61.087, 15.748];   // STEP: 6MMX6MM_TACTILE_SMT:SW1 (GPIO 6)

// Cap alone on the switch clicks; flush lid preloads caps unless platform pocket
// is deep enough (skirt extension + in-wall float). Stepped bore: wide flange
// seat (lower) + narrow pad port (through wall) — flange 7.5 cannot pass 6.3 port.
button_plunger_dia             = 3.0;
button_plunger_h               = 1.2;   // plunger height above switch body — tune
button_switch_travel           = 0.1;
button_lid_squeeze_allowance   = 0.25;  // press-fit lid preload — tune on hardware
button_pocket_into_skirt     = 1.0;    // platform pocket below inner face — tune (~1 mm lift test)
button_cap_pocket_clearance    = 0.2;
button_cap_pocket_dia          = button_plunger_dia + 2 * button_cap_pocket_clearance;
button_cap_pocket_depth        = button_plunger_h
    - button_switch_travel
    - button_lid_squeeze_allowance
    - button_cap_pocket_clearance;
// Per-button overrides — SW1 (B) may differ from SW2 (A); measure on hardware.
button_b_plunger_h             = button_plunger_h;
button_b_pocket_into_skirt   = button_pocket_into_skirt;
button_b_cap_pocket_depth      = button_b_plunger_h
    - button_switch_travel
    - button_lid_squeeze_allowance
    - button_cap_pocket_clearance;
button_cap_pad_dia             = 6.0;
button_cap_pad_h               = 1.7;   // +0.5 with proud — same seat / click travel
button_cap_pad_proud           = 1.0;   // above lid outer face — was 0.5
button_cap_flange_dia          = 7.5;   // retention flange — independent of lid hole
button_cap_seat_h            = wall + button_cap_pad_proud - button_cap_pad_h;
button_cap_lid_float           = wall - button_cap_seat_h;  // in-wall gap above flange when flush
button_lid_recess_extra        = 0.25;   // Loop 41: was 0.4 — tighter flange seat
button_lid_recess_dia          = button_cap_flange_dia + button_lid_recess_extra;
button_lid_recess_depth          = button_cap_seat_h + button_cap_lid_float;  // = wall
button_cap_total_h             = button_cap_seat_h + button_cap_pad_h;
button_cap_print_gap           = 15;    // bed spacing between caps when printing ×2 alone
button_cap_nest_gap            = 3;     // cap spacing when nested in lid LCD window
// Lid cutouts — skirt platform + flange seat + pad port + outer well.
// Sharp Ø steps bridged badly when the lid prints face-down; chamfer_h
// tapers wide↔narrow instead. Extra port clearance absorbs blobbing.
button_lid_port_clearance     = 0.25;   // Loop 41: was 0.45 — tighter pad port
button_lid_y_offset           = 0.25;   // Loop 41: net +Y 0.25 from STEP (+0.5 then −0.25)
button_lid_step_chamfer_h       = 0.8;    // taper at flange→port transition
button_lid_pad_port_dia        = button_cap_pad_dia + button_lid_port_clearance;
button_lid_pad_well_dia        = button_cap_pad_dia + 0.6;
button_lid_pad_well_depth      = button_cap_pad_h - button_cap_pad_proud;
button_cap_pocket_chamfer      = 0.3;    // wider pocket mouth on cap bed face

// Pi I/O cluster cutouts in the back tub's FRONT (low-y) side
// wall. The Pi Zero 2 W has three ports along its bottom long
// edge: mini-HDMI, micro-USB OTG, micro-USB PWR-IN. When stacked
// on the bonnet's GPIO socket (on the bonnet's HIGH-y edge), the
// Pi's I/O edge ends up on the bonnet's LOW-y edge — the same
// long edge as the bonnet's "stemmaQT" silkscreen — so cables
// exit the FRONT of the case. We expose two by default (PWR + OTG)
// and leave HDMI sealed; the production unit is air-gapped and
// never drives an external monitor. Toggle hdmi_cutout_enabled
// if you want HDMI for development.
//
// usb_cutout_w / usb_cutout_h are shared by the two micro-USB
// cutouts (same plug shroud). x_offsets are port centres measured
// in bonnet-frame (same x-axis as the bonnet because the Pi sits
// on the bonnet's GPIO header, long-axis aligned).
// Port-body-sized cutouts (Loop 3 redesign). Pi PCB I/O edge now sits
// only pi_io_gap (0.4 mm) from the front wall inner face, so the
// connector bodies extend INTO the front wall rather than requiring
// large cable-entry slots. Holes are sized to the port body + 0.4 mm
// clearance per side — cables plug directly into the exposed ports.
//
// Standard port body dimensions (micro-USB type B, mini-HDMI type C):
//   micro-USB: 7.2 mm wide × 2.5 mm tall  → cutout 8.0 × 3.3 mm
//   mini-HDMI: 10.7 mm wide × 3.7 mm tall → cutout 11.5 × 4.5 mm
usb_cutout_w            = 9.3;             // Loop 5: +0.65 mm clearance per side (was 8.0)
usb_cutout_h            = 3.3;             // micro-USB body 2.5 + 2×0.4 clearance
usb_pwr_x_offset        = 53.35;      // Loop 5: −0.65 mm (Pi port gap 4.67 vs case 5.97 mm)
usb_data_x_offset       = 41.65;      // Loop 5: +0.65 mm (close 1.3 mm excess spacing)
// PWR LED view hole — front wall, just right (+x) of the power USB cutout.
pwr_led_hole_dia        = 2.5;
pwr_led_hole_x_gap      = 1.2;        // gap from USB cutout edge to hole centre
pwr_led_z_offset        = 0.8;        // above USB jack centre — tune on hardware
hdmi_cutout_enabled     = true;            // enabled for prototype; seal in production
hdmi_cutout_w           = 12.5;            // Loop 5: +0.5 mm clearance per side (was 11.5)
hdmi_cutout_h           = 4.5;             // mini-HDMI body 3.7 + 2×0.4 clearance
hdmi_x_offset           = 12.4;       // mini-HDMI, ESTIMATE — verify

// z position of the micro-USB jack opening centre, measured from
// the Pi PCB top face. Loop 5 fit-test: lower 0.75 mm from 2.0.
pi_pcb_thickness = 1.6;
usb_jack_z_above_pi_top = 1.25;

// microSD-slot cutout. Notch through the LEFT short-edge wall of
// the back tub so the card's edge aligns with the Pi's SD slot.
// Disable in production for tamper resistance; keep enabled for
// prototype + service.
//
// sd_z_above_pi_top: slot centre height above the Pi PCB TOP face.
// The Pi Zero 2W push-push SD holder is on the component (top) side
// of the PCB, with the slot opening ~1.1 mm above the PCB surface.
// Adjusted from the old formula (which referenced PCB bottom and
// landed 5 mm too low) after fit-test on Loop 2 print.
sd_cutout_enabled  = true;
sd_cutout_w        = 14.0;            // along the y axis
sd_cutout_h        = 3.0;             // along the z axis
sd_z_above_pi_top  = 1.1;            // slot centre above Pi PCB top face
// Loop 4 fit-test: +4.0 was too far toward back; move 3 mm toward front.
sd_cutout_y_offset = 1.0;            // mm, positive = toward back wall

// Camera: Arducam UC-346 OV5647 (standard Pi Camera footprint).
// Ships with a 15-pin↔22-pin Pi-Zero ribbon. OV5647 is the same
// sensor SeedSigner uses, so QR-scan compatibility is proven.
//
// Camera target — module height only. Post height stays 3.0 mm (pre–Loop 17).
// CM3 fits the same case_z by shrinking ribbon_under_pi (derived below).
camera_target = "cm3";   // "ov5647" | "cm3"

// Confirmed measurements (2026-05-21, calipers, Arducam UC-346 OV5647):
//   PCB outline:   25.1 × 24.2 mm
//   PCB thickness: 1.55 mm
//   Lens height:   7.14 mm (PCB bottom to top of lens housing)
//
// Confirmed by caliper + visual inspection (2026-05-21):
//   camera_lens_centre — 10 mm from FFC edge, centred perpendicular to FFC.
//   camera_mount_pitch — 21 mm along the non-FFC axis (2 mm inset from
//     each long edge); 12 mm along the FFC axis (near row at 10 mm from
//     FFC edge, far row at 22 mm). Near hole row co-planar with lens.
//     Pattern is NOT centred — offset toward the far end of the board.
//   camera_mount_dia — M2 clearance, verify on Loop 3 print.
//
// FFC orientation: connector exits from the LONG SIDE of the PCB
// (the x=0 edge in case coordinates), running toward the Pi's CSI ZIF
// on the same side of the case. PCB is mounted in landscape:
//   x-axis = 24.2 mm (FFC edge on left)
//   y-axis = 25.1 mm (long dimension, perpendicular to FFC)
camera_module_x    = 24.2;            // PCB x — same for OV5647 + CM3
camera_module_y    = 25.1;            // PCB y — same for OV5647 + CM3
camera_module_z    = camera_target == "cm3" ? 11.5 : 7.14;
// ov5647: 7.14 mm PCB bottom → lens top (Arducam UC-346, calipered)
// cm3:    11.5 mm total module height (Pi product brief, standard variant)
camera_lens_centre = [10.0, 12.55];   // OV5647; re-eyeball if CM3 lens shifts
camera_mount_pitch = [12.0, 21.0];   // same hole pattern as CM2/CM3
camera_mount_dia   = 2.2;             // M2 clearance

// Camera standoffs — 3.0 mm since first revision; never tied to case_z trims.
// M2 × 6 mm screws down through PCB holes into blind pilots.
camera_post_height       = 3.0;
camera_post_outer        = 5.0;   // Ø 5 mm column (1.65 mm wall around pilot)
camera_post_pilot        = 1.7;   // M2 self-tap pilot in PLA
camera_post_pilot_depth  = min(4.5, camera_post_height - 0.5);

// Corner lid screws — M2 × 6 mm pan-head self-tappers. Square pillars
// at each outer corner (footprint = 2× wall); hole centre inset = wall.
lid_screw_enabled      = true;
corner_screw_inset     = wall;              // 2.4 mm — screw centre from outer corner
corner_pillar_size     = 2 * wall;          // 4.8 mm square pillar side
lid_screw_pilot_d      = camera_post_pilot; // 1.7 mm — M2 self-tap
lid_screw_pilot_depth  = 2.5;
lid_screw_clearance_d  = camera_mount_dia;  // 2.2 mm — M2 shank clearance
lid_corner_pocket_pad  = clearance;         // FDM slack around tub corner pillars

// Pi standoffs (back tub). Four posts; Pi PCB rests on flat tops.
// M2.5 × 6 mm pan-head self-tapping screws through Pi holes into pilots.
pi_standoff_outer        = 7.0;         // Ø 7 mm column
pi_standoff_pilot        = 2.1;         // M2.5 self-tap pilot in PETG
pi_standoff_pilot_depth  = 5.0;         // blind bore from post top — tune ±0.5

// Lens cone in the back tub's back wall.
lens_cone_dia     = 8.0;
lens_cone_recess  = 3.0;
lens_cone_chamfer = 60;               // half-angle, degrees

// Lanyard hole (back tub, top-right corner of the back wall).
// Loop 1 print showed the hole as drawn was unusable — keeping it
// disabled until we revisit the geometry (probably wants to be a
// flat tab with a slot, not a round hole through a curved wall).
lanyard_enabled = false;
lanyard_dia     = 4.0;
lanyard_inset   = 4.0;

// Tamper-sticker keep-out box on the back wall. The recess is on the
// OUTER face (z = 0 side) so the sticker sits flush and is visible
// from outside. Previously this was positioned near the inner face,
// which thinned the back wall under camera post 3 and caused that
// post to detach — fixed by anchoring the recess at z = 0.
tamper_box_w     = 12.0;
tamper_box_h     = 6.0;
tamper_box_depth = 0.4;

// Cosmetic detailing — these don't affect fit, only the visual feel.
//
// corner_radius: vertical fillet on the four vertical edges of the
//   case. ~3 mm gives a soft-brick look without eating wall thickness.
// lid_face_chamfer: small bevel on the lid's outer top edge so the
//   lid catches light and doesn't read as a featureless plate.
// Inner flange depth — Loop 37: 1.36 mm (measured 1.86 − 0.5).
// Ring inner edge = window through-hole; outer = window + 2×lcd_bezel_border.
lcd_inner_collar_enabled = true;
lcd_inner_collar_depth   = 1.36;
lcd_glass_relief_depth   = 0;      // off when collar enabled; bump if still tight
lcd_bezel_border  = 1.25;
corner_radius     = 3.0;
lid_face_chamfer  = 0.8;

// Silicone joystick base pocket. The 4506's silicone joystick
// cover has a 12.2 × 12.2 × 3.4 mm square base that sits on the
// bonnet PCB around the joystick.
joystick_silicone_base_h        = 3.4;   // measured square base height
joystick_silicone_overhang      = 1.1;   // base top above LCD plane (calipers)
joystick_base_overlap           = 0.35;  // lid over base rim — was 0.6 (Loop 34)
joystick_pocket_into_skirt      = 2.5;   // Loop 34: +0.8 — seat lid over silicone/stem
joystick_silicone_pocket_w      = 13.2;
joystick_silicone_pocket_h      = 13.2;
joystick_silicone_pocket_depth  = wall + joystick_pocket_into_skirt
    - joystick_base_overlap;

// Cosmetic: how smooth round features are. Bump at print time, not
// while editing.
$fn = 64;


// =====================================================================
// Derived dimensions
// =====================================================================

// Internal cavity (the box that holds the stack).
//
// X (left-right): The LCD active-area centre is NOT at the PCB midline.
// lcd_active_centre.x = 30.87 mm on a 65.5 mm-wide PCB, placing it
// 3.76 mm left of the PCB centreline. To put the lens hole on the
// case's visual centreline we make the left gap wider by that same
// 3.76 mm; the right gap stays at the nominal clearance + 1 mm.
//
//   bonnet_lcd_offset_x = bonnet_pcb_x - 2*lcd_active_centre.x
//                       = 65.5 - 61.74 = 3.76 mm
//
//   left_gap  = (clearance + 1) + bonnet_lcd_offset_x  = 5.16 mm
//   right_gap = (clearance + 1)                         = 1.40 mm
//   cavity_x  = bonnet_pcb_x + left_gap + right_gap     = 72.06 mm
//
bonnet_lcd_offset_x = bonnet_pcb_x - 2 * (lcd_active_area_offset.x + lcd_active_area.x / 2);   // 3.76 mm
cavity_x = bonnet_pcb_x + 2*(clearance + 1) + bonnet_lcd_offset_x;
// cavity_y uses purpose-driven gaps (Loop 3): pi_io_gap front + PCB + pi_back_clearance.
// Was: bonnet_pcb_y + 2*clearance + 2 = 33.4 mm (symmetric, 1 mm extra per side).
// Now: 31.8 mm — saves 1.6 mm off case_y; Pi centre lands 0.2 mm off case centre.
cavity_y = bonnet_pcb_y + pi_io_gap + pi_back_clearance;

// Ribbon slot — whatever remains after camera + Pi stack in the fixed budget.
// ov5647 → 5.0 mm; cm3 → ~0.64 mm (verify cable fold on hardware).
ribbon_under_pi = cavity_z_budget
    - camera_post_height
    - camera_module_z
    - pi_pcb_to_lcd_top
    - front_slack
    - lid_seat_raise;

// Cavity depth — explicit stack-up from camera floor up to LCD top.
cavity_z =
    camera_post_height +
    camera_module_z +
    ribbon_under_pi +
    pi_pcb_to_lcd_top +
    front_slack +
    lid_seat_raise;                    // = cavity_z_budget

// External case dimensions. With no screw lanes the footprint is
// cavity + 2*wall on every axis — much slimmer rim than before.
case_x = cavity_x + 2*wall;
case_y = cavity_y + 2*wall + front_lane + back_lane;
case_z = cavity_z + 2*wall;

cavity_origin_x = wall;
cavity_origin_y = wall + front_lane;

// Bonnet's bottom-left corner in case-frame. Base x centres the lens on the
// case midline; bonnet_x_shift moves the Pi/bonnet stack without moving camera.
_bonnet_origin_x_base = wall + (clearance + 1) + bonnet_lcd_offset_x;
bonnet_origin_x = _bonnet_origin_x_base + bonnet_x_shift;
bonnet_origin_y = cavity_origin_y + pi_io_gap;

// LCD optical centre in PCB-frame.
lcd_active_centre = [
    lcd_active_area_offset.x + lcd_active_area.x / 2,
    lcd_active_area_offset.y + lcd_active_area.y / 2,
];                                    // = (30.87, 16.87)
lcd_window_centre_x = bonnet_origin_x + lcd_active_centre.x + lcd_window_eff_x_offset;
lcd_window_centre_y = bonnet_origin_y + lcd_active_centre.y + lcd_window_eff_y_offset;

// Camera mount pattern offset from the PCB's (0,0) corner (FFC side = x=0).
// x: near hole row is at the same x as the lens (10 mm from FFC edge);
//    far row at camera_lens_centre.x + camera_mount_pitch.x = 22 mm.
//    Pattern is NOT centred in x — offset toward the far (non-FFC) end.
// y: centred on the 25.1 mm dimension.
camera_mount_inset = [
    camera_lens_centre.x,                           // = 10.0 mm from FFC side
    (camera_module_y - camera_mount_pitch.y) / 2,  // = 2.05 mm, centred
];

// Pi standoff height — calculated so the Pi PCB's BOTTOM face lands
// just above the camera with the ribbon U-turn space between.
pi_standoff_height = camera_post_height + camera_module_z + ribbon_under_pi;

// USB jack z position in case-frame. Pi PCB bottom = wall +
// pi_standoff_height; PCB top = + pi_pcb_thickness; jack centre =
// + usb_jack_z_above_pi_top.
usb_jack_z = wall + pi_standoff_height + pi_pcb_thickness
           + usb_jack_z_above_pi_top;

// Seam between tub and lid. The lid's front face sits on top of the
// tub; the lid's skirt drops into the tub's stepped lip below.
tub_top = case_z - wall;             // = 32.74 (case_z 35.14 − wall 2.4)

// Camera anchor — lens axis stays on case midline (ignores bonnet_x_shift).
//   lens_in_case = _bonnet_origin_x_base + lcd_active_centre
//                = camera_anchor + camera_lens_centre
camera_anchor_x = _bonnet_origin_x_base + lcd_active_centre.x - camera_lens_centre.x;
camera_anchor_y = bonnet_origin_y + lcd_active_centre.y - camera_lens_centre.y;
lens_x          = camera_anchor_x + camera_lens_centre.x;
lens_y          = camera_anchor_y + camera_lens_centre.y;


// =====================================================================
// Helpers
// =====================================================================

// Centre-aligned rounded rectangle prism.
module rrect(x, y, z, r=2) {
    hull() {
        for (dx = [-x/2 + r, x/2 - r])
            for (dy = [-y/2 + r, y/2 - r])
                translate([dx, dy, 0])
                    cylinder(h=z, r=r, center=false);
    }
}

// Outer brick of the case with rounded vertical corners. Used for
// both the tub's outer perimeter and the lid's slab outer perimeter
// so the two halves fillet identically along the assembled vertical
// edges. Top and bottom faces stay flat; only the four vertical
// edges are radiused.
module outer_brick(x, y, z, r=corner_radius) {
    hull() {
        for (dx = [r, x - r])
            for (dy = [r, y - r])
                translate([dx, dy, 0])
                    cylinder(h=z, r=r);
    }
}


function pi_standoff_positions() = [
    [bonnet_origin_x + mount_inset_x,
     bonnet_origin_y + mount_inset_y],
    [bonnet_origin_x + mount_inset_x + mount_pitch_x,
     bonnet_origin_y + mount_inset_y],
    [bonnet_origin_x + mount_inset_x,
     bonnet_origin_y + mount_inset_y + mount_pitch_y],
    [bonnet_origin_x + mount_inset_x + mount_pitch_x,
     bonnet_origin_y + mount_inset_y + mount_pitch_y],
];

function camera_post_positions() = [
    [camera_anchor_x + camera_mount_inset.x,
     camera_anchor_y + camera_mount_inset.y],
    [camera_anchor_x + camera_mount_inset.x + camera_mount_pitch.x,
     camera_anchor_y + camera_mount_inset.y],
    [camera_anchor_x + camera_mount_inset.x,
     camera_anchor_y + camera_mount_inset.y + camera_mount_pitch.y],
    [camera_anchor_x + camera_mount_inset.x + camera_mount_pitch.x,
     camera_anchor_y + camera_mount_inset.y + camera_mount_pitch.y],
];

function pi_pcb_keepout() = [
    bonnet_origin_x - clearance,
    bonnet_origin_y - clearance,
    bonnet_origin_x + bonnet_pcb_x + clearance,
    bonnet_origin_y + bonnet_pcb_y + clearance,
];

function _rect_outside_rect(ax0, ay0, ax1, ay1, bx0, by0, bx1, by1) =
    (ax1 <= bx0) || (ax0 >= bx1) || (ay1 <= by0) || (ay0 >= by1);

function corner_pillar_positions() = [
    [corner_screw_inset, corner_screw_inset],
    [case_x - corner_screw_inset, corner_screw_inset],
    [corner_screw_inset, case_y - corner_screw_inset],
    [case_x - corner_screw_inset, case_y - corner_screw_inset],
];

// [x0, y0, x1, y1] axis-aligned footprint for corner index 0..3 (FL..BR).
function corner_pillar_footprint(i) =
    i == 0 ? [0, 0, corner_pillar_size, corner_pillar_size] :
    i == 1 ? [case_x - corner_pillar_size, 0, case_x, corner_pillar_size] :
    i == 2 ? [0, case_y - corner_pillar_size, corner_pillar_size, case_y] :
             [case_x - corner_pillar_size, case_y - corner_pillar_size,
              case_x, case_y];

function _corner_pillar_clear_pi(i) =
    let (
        fp = corner_pillar_footprint(i),
        pk = pi_pcb_keepout()
    )
    _rect_outside_rect(
        fp[0], fp[1], fp[2], fp[3],
        pk[0], pk[1], pk[2], pk[3]
    );

if (lid_screw_enabled) {
    assert(_corner_pillar_clear_pi(0), "FL corner pillar overlaps Pi keepout");
    assert(_corner_pillar_clear_pi(1), "FR corner pillar overlaps Pi keepout");
    assert(_corner_pillar_clear_pi(2), "BL corner pillar overlaps Pi keepout");
    assert(_corner_pillar_clear_pi(3), "BR corner pillar overlaps Pi keepout");
}

module corner_pillars() {
    if (lid_screw_enabled) {
        for (i = [0:3]) {
            _fp = corner_pillar_footprint(i);
            translate([_fp[0], _fp[1], 0])
                cube([corner_pillar_size, corner_pillar_size, tub_top]);
        }
    }
}

// Underside corner pockets + screw bores in the front lid. The tub
// pillars share the outer corner footprint; the lid skirt also wraps
// that XY region, so we relieve the skirt (and bore through slab).
module lid_corner_screw_cutouts() {
    if (lid_screw_enabled) {
        _pocket_h = lid_skirt_h + lid_corner_pocket_pad + 0.001;
        for (i = [0:3]) {
            _fp = corner_pillar_footprint(i);
            translate([
                _fp[0] - lid_corner_pocket_pad,
                _fp[1] - lid_corner_pocket_pad,
                -0.001
            ])
                cube([
                    corner_pillar_size + 2 * lid_corner_pocket_pad,
                    corner_pillar_size + 2 * lid_corner_pocket_pad,
                    _pocket_h
                ]);
        }
        for (p = corner_pillar_positions())
            translate([p.x, p.y, -0.001])
                cylinder(
                    h=lid_skirt_h + wall + 0.002,
                    d=lid_screw_clearance_d
                );
    }
}


// Pocket depth unchanged — only material above pocket grows (seat + pad).
//
module button_cap(pocket_depth = button_cap_pocket_depth) {
    difference() {
        union() {
            cylinder(h=button_cap_seat_h, d=button_cap_flange_dia);
            translate([0, 0, button_cap_seat_h])
                cylinder(h=button_cap_pad_h, d=button_cap_pad_dia);
        }
        // Flared mouth on the bed face — elephant foot + bridging tolerance.
        translate([0, 0, -0.01])
            cylinder(
                h=pocket_depth + 0.01,
                d1=button_cap_pocket_dia + 2 * button_cap_pocket_chamfer,
                d2=button_cap_pocket_dia
            );
    }
}

// Print: wide flange on build plate (not upside down). Pocket is a shallow
// dimple on the bed side — add a brim in the slicer for small parts.
module button_cap_for_print(pocket_depth = button_cap_pocket_depth) {
    button_cap(pocket_depth);
}

// Lid flipped face-down — outer face on build plate (z = 0), footprint in +X/+Y.
module front_lid_for_print(origin_x = 0, origin_y = 0) {
    translate([origin_x, origin_y + case_y, lid_skirt_h + wall])
        rotate([180, 0, 0])
            front_lid();
}

// Two caps on the bed, centred in the lid LCD through-window (batch-print friendly).
module button_caps_in_lid_window(lid_origin_x = 0, lid_origin_y = 0) {
    _bed_cx = lid_origin_x + lcd_window_centre_x;
    _bed_cy = lid_origin_y + case_y - lcd_window_centre_y;
    _half_span = button_cap_flange_dia / 2 + button_cap_nest_gap / 2;
    translate([_bed_cx - _half_span, _bed_cy, 0])
        button_cap_for_print(button_cap_pocket_depth);
    translate([_bed_cx + _half_span, _bed_cy, 0])
        button_cap_for_print(button_b_cap_pocket_depth);
}

module lid_with_caps_for_print(origin_x = 0, origin_y = 0) {
    front_lid_for_print(origin_x, origin_y);
    button_caps_in_lid_window(origin_x, origin_y);
}


// =====================================================================
// Back tub
// =====================================================================
//
// The deep half. Outer brick minus a stepped inner cavity, plus
// internal posts (camera mounts, Pi standoffs), minus the lens cone,
// lanyard, tamper recess, USB cutout, and (in dev variant) SD cutout.
//
// Stepped cavity: from z=wall (back wall inner face) up to
// z=tub_top - lid_skirt_h, the cavity is the full cavity_x × cavity_y
// rectangle. From there up to z=tub_top, the cavity widens by
// lid_skirt_step on every side, leaving a thinner outer shoulder
// that the front lid's skirt drops into.

module back_tub() {
    // CSG structure:
    //   outer difference  — subtracts pilot holes and other wall
    //                       penetrations from the whole solid
    //     union
    //       inner difference — carves the two cavity volumes out of
    //                          the outer brick only
    //         outer_brick
    //         main_cavity
    //         stepped_cavity (lid-registration lip)
    //       camera posts  — added after cavity so they survive inside
    //       pi standoffs  — same
    //
    // The cavity cuts MUST be applied to outer_brick before adding the
    // posts/standoffs; if the posts/standoffs were in the same union as
    // outer_brick and then the cavity was subtracted from the whole,
    // the cavity would eat the posts (they are inside the cavity footprint).

    difference() {
        union() {
            // ---- Shell: outer brick with cavity carved out ----
            difference() {
                // Outer brick with rounded vertical corners.
                outer_brick(case_x, case_y, tub_top);

                // Main cavity — full size from back wall up to the
                // start of the registration step.
                translate([
                    cavity_origin_x,
                    cavity_origin_y,
                    wall
                ])
                    cube([
                        cavity_x,
                        cavity_y,
                        tub_top - wall - lid_skirt_h
                    ]);

                // Stepped cavity — wider rectangle from the step up
                // to the seam, leaving a thin shoulder the lid skirt
                // drops into.
                translate([
                    cavity_origin_x - lid_skirt_step,
                    cavity_origin_y - lid_skirt_step,
                    tub_top - lid_skirt_h
                ])
                    cube([
                        cavity_x + 2*lid_skirt_step,
                        cavity_y + 2*lid_skirt_step,
                        lid_skirt_h + 1
                    ]);
            }

            // ---- Camera standoffs — rise from the cavity floor ----
            for (p = camera_post_positions())
                translate([p.x, p.y, wall])
                    cylinder(h=camera_post_height, d=camera_post_outer);

            // ---- Pi standoffs — rise from the cavity floor ----
            for (p = pi_standoff_positions())
                translate([p.x, p.y, wall])
                    cylinder(h=pi_standoff_height, d=pi_standoff_outer);

            // ---- Corner lid-screw pillars — full height at outer corners ----
            corner_pillars();
        }

        // ---- Post bores — blind from post TOP only ----
        //
        // Pi: M2.5 × 6 mm pan-head self-tap pilots (blind from post top).
        for (p = pi_standoff_positions())
            translate([
                p.x, p.y,
                wall + pi_standoff_height
                    - min(pi_standoff_pilot_depth, pi_standoff_height - 1.0)
                    - 0.001
            ])
                cylinder(
                    h=min(pi_standoff_pilot_depth, pi_standoff_height - 1.0) + 0.01,
                    d=pi_standoff_pilot
                );

        // Camera: M2 self-tap pilots (no inserts).
        for (p = camera_post_positions())
            translate([
                p.x, p.y,
                wall + camera_post_height - camera_post_pilot_depth - 0.001
            ])
                cylinder(
                    h=camera_post_pilot_depth + 0.01,
                    d=camera_post_pilot
                );

        // Corner lid screws: M2 × 6 mm pan-head self-tap pilots.
        if (lid_screw_enabled) {
            for (p = corner_pillar_positions())
                translate([
                    p.x, p.y,
                    tub_top - lid_screw_pilot_depth - 0.001
                ])
                    cylinder(
                        h=lid_screw_pilot_depth + 0.01,
                        d=lid_screw_pilot_d
                    );
        }

        // Lens through-hole.
        translate([lens_x, lens_y, -1])
            cylinder(h=wall + 2, d=lens_cone_dia);

        // Lens cone recess on the OUTSIDE face.
        translate([lens_x, lens_y, -lens_cone_recess + 0.001])
            cylinder(
                h=lens_cone_recess + 0.01,
                d1=lens_cone_dia
                   + 2*lens_cone_recess*tan(lens_cone_chamfer/2),
                d2=lens_cone_dia
            );

        // Lanyard hole, top-right corner of the back wall.
        if (lanyard_enabled) {
            translate([
                case_x - lanyard_inset,
                case_y - lanyard_inset,
                -1
            ])
                cylinder(h=wall + 2, d=lanyard_dia);
        }

        // Tamper-sticker keep-out recess — 0.4 mm deep pocket on the
        // OUTER back face (z = 0). Anchored with -0.001 overlap so
        // the slicer sees a clean coplanar face rather than a 0-height
        // gap. Near the high-y (sealed) edge, away from I/O and lens.
        translate([
            case_x/2 - tamper_box_w/2,
            case_y - wall - tamper_box_h - 1,
            -0.001
        ])
            cube([tamper_box_w, tamper_box_h, tamper_box_depth + 0.001]);

        // Pi I/O cluster cutouts — all pierce the FRONT (low-y) side
        // wall from the cavity outward. Ports-through-wall design
        // (Loop 3): holes are sized to port bodies, not cable shrouds.
        // Cutout depth extends to bonnet_origin_y + 1 so the connector
        // body inside the cavity is fully cleared (Pi I/O edge is at
        // bonnet_origin_y; +1 mm gives a clean through-cut past it).
        for (port = [
            // [x_offset, w, h, enabled]
            [usb_pwr_x_offset,  usb_cutout_w,  usb_cutout_h,  true],
            [usb_data_x_offset, usb_cutout_w,  usb_cutout_h,  true],
            [hdmi_x_offset,     hdmi_cutout_w, hdmi_cutout_h, hdmi_cutout_enabled]
        ]) if (port[3]) {
            translate([
                bonnet_origin_x + port[0] - port[1]/2,
                -1,
                usb_jack_z - port[2]/2
            ])
                cube([
                    port[1],
                    bonnet_origin_y + 1,
                    port[2]
                ]);
        }

        // microSD-slot cutout — pierces the LEFT short-edge wall,
        // spans from outer wall inward to the cavity so the card
        // edge can be reached for swap/service.
        // z: Pi PCB top + sd_z_above_pi_top (slot centre on the
        //    component/top face of the Pi PCB).
        if (sd_cutout_enabled) {
            translate([
                -1,
                cavity_origin_y + cavity_y/2 + sd_cutout_y_offset - sd_cutout_w/2,
                wall + pi_standoff_height + pi_pcb_thickness
                    + sd_z_above_pi_top - sd_cutout_h/2
            ])
                cube([
                    cavity_origin_x + 1,
                    sd_cutout_w,
                    sd_cutout_h
                ]);
        }

        // Pi power LED view hole — front wall, right of PWR USB.
        translate([
            bonnet_origin_x + usb_pwr_x_offset + usb_cutout_w / 2
                + pwr_led_hole_x_gap + pwr_led_hole_dia / 2,
            -1,
            usb_jack_z + pwr_led_z_offset - pwr_led_hole_dia / 2
        ])
            cube([
                pwr_led_hole_dia,
                bonnet_origin_y + 1,
                pwr_led_hole_dia
            ]);
    }
}


module lcd_inner_bezel_collar() {
    if (lcd_inner_collar_enabled && lcd_inner_collar_depth > 0) {
        _d = lcd_inner_collar_depth;
        _ix = lcd_window_eff_x;
        _iy = lcd_window_eff_y;
        _ox = lcd_window_eff_x + 2 * lcd_bezel_border;
        _oy = lcd_window_eff_y + 2 * lcd_bezel_border;
        translate([0, 0, lid_skirt_h - _d])
            difference() {
                translate([lcd_window_centre_x, lcd_window_centre_y, _d / 2])
                    cube([_ox, _oy, _d], center=true);
                translate([
                    lcd_window_centre_x - _ix / 2,
                    lcd_window_centre_y - _iy / 2,
                    -0.001
                ])
                    cube([_ix, _iy, _d + 0.002]);
            }
    }
}


module lcd_glass_clearance_relie() {
    if (lcd_glass_relief_depth > 0) {
        _gx = lcd_module[0] + 2 * clearance;
        _gy = lcd_module[1] + 2 * clearance;
        translate([
            lcd_window_centre_x - _gx / 2,
            lcd_window_centre_y - _gy / 2,
            lid_skirt_h - lcd_glass_relief_depth - 0.001
        ])
            cube([_gx, _gy, lcd_glass_relief_depth + 0.002]);
    }
}


module button_lid_cutouts(centre, pocket_into_skirt) {
    _cx = bonnet_origin_x + centre.x;
    _cy = bonnet_origin_y + centre.y + button_lid_y_offset;
    _z_skirt = lid_skirt_h - pocket_into_skirt;
    _z_seat_top = lid_skirt_h + button_cap_seat_h;
    _z_well_floor = lid_skirt_h + wall - button_lid_pad_well_depth;

    // Skirt platform + flange seat — one continuous wide bore.
    translate([_cx, _cy, _z_skirt - 0.001])
        cylinder(
            h=_z_seat_top - _z_skirt + 0.002,
            d=button_lid_recess_dia
        );

    // Tapered transition (recess → pad port) — replaces sharp step for FDM.
    translate([_cx, _cy, _z_seat_top - button_lid_step_chamfer_h - 0.001])
        cylinder(
            h=button_lid_step_chamfer_h + 0.002,
            d1=button_lid_pad_port_dia,
            d2=button_lid_recess_dia
        );

    // Narrow pad port through the wall slab.
    translate([_cx, _cy, _z_seat_top - 0.001])
        cylinder(
            h=_z_well_floor - _z_seat_top + 0.002,
            d=button_lid_pad_port_dia
        );

    // Outer-face cosmetic well — pad sits slightly proud.
    translate([_cx, _cy, _z_well_floor - 0.001])
        cylinder(
            h=button_lid_pad_well_depth + 0.02,
            d1=button_lid_pad_port_dia,
            d2=button_lid_pad_well_dia
        );
}


// =====================================================================
// Front lid
// =====================================================================
//
// The shallow half. A flat slab the size of the case footprint plus
// a short skirt that drops into the back tub's registration step.
// The lid is built with z=0 at the skirt's bottom face and
// z=lid_skirt_h+wall at the front face's outer surface, so it can be
// rendered in place over the tub without any negative-z geometry.

module front_lid() {
    difference() {
        union() {
            // Front face slab — same rounded outline as the tub so
            // the assembled case has matching vertical fillets.
            translate([0, 0, lid_skirt_h])
                outer_brick(case_x, case_y, wall);

            // Inner underside flange — off Loop 36; see lcd_glass_clearance_relie().
            lcd_inner_bezel_collar();

            // Skirt: thin rim hanging off the bottom of the slab,
            // sized to fit inside the back tub's stepped lip. Stays
            // rectangular (it has to mate with the tub's rectangular
            // step); hidden inside the case so the visual seam is
            // along the rounded outer edge.
            difference() {
                translate([
                    cavity_origin_x - lid_skirt_step,
                    cavity_origin_y - lid_skirt_step,
                    0
                ])
                    cube([
                        cavity_x + 2*lid_skirt_step,
                        cavity_y + 2*lid_skirt_step,
                        lid_skirt_h
                    ]);
                translate([
                    cavity_origin_x,
                    cavity_origin_y,
                    -0.5
                ])
                    cube([
                        cavity_x,
                        cavity_y,
                        lid_skirt_h + 1
                    ]);
            }
        }

        // LCD window — plain square through-hole (vertical walls, print-safe).
        translate([
            lcd_window_centre_x,
            lcd_window_centre_y,
            lid_skirt_h + wall / 2
        ])
            cube(
                [lcd_window_eff_x, lcd_window_eff_y, wall + 0.002],
                center=true
            );

        // Shallow inner-face relief over glass outline — no contact/teeter.
        lcd_glass_clearance_relie();

        // Joystick cutout. Two-stage:
        //   1. Frustum through skirt + wall — stem clears below inner face
        //   2. SQUARE pocket on the INNER face for the silicone base
        translate([
            bonnet_origin_x + joystick_centre.x,
            bonnet_origin_y + joystick_centre.y,
            lid_skirt_h - joystick_pocket_into_skirt - 0.001
        ])
            cylinder(
                h=joystick_pocket_into_skirt + wall + 1.002,
                d1=joystick_hole_dia_inner,
                d2=joystick_hole_dia_outer
            );
        translate([
            bonnet_origin_x + joystick_centre.x
                - joystick_silicone_pocket_w/2,
            bonnet_origin_y + joystick_centre.y
                - joystick_silicone_pocket_h/2,
            lid_skirt_h - joystick_pocket_into_skirt - 0.001
        ])
            cube([
                joystick_silicone_pocket_w,
                joystick_silicone_pocket_h,
                joystick_silicone_pocket_depth + 0.001
            ]);

        // Button cutouts — stepped bore retains flange; pad passes narrow port.
        button_lid_cutouts(button_a_centre, button_pocket_into_skirt);
        button_lid_cutouts(button_b_centre, button_b_pocket_into_skirt);

        // Corner tub pillars — skirt pockets + M2 through-holes (full stack).
        lid_corner_screw_cutouts();

        // Outer top-face chamfer — bevel where the rounded slab
        // meets the front face. Built by subtracting the difference
        // between an oversized brick and a chamfered (smaller-top)
        // brick. Subtle: ~0.8 mm visible bevel.
        chamfer_z_top = lid_skirt_h + wall;
        chamfer_z_bot = chamfer_z_top - lid_face_chamfer;
        translate([0, 0, chamfer_z_bot])
            difference() {
                translate([0, 0, 0])
                    outer_brick(case_x, case_y, lid_face_chamfer + 0.01);
                hull() {
                    outer_brick(
                        case_x, case_y, 0.001,
                        r=corner_radius
                    );
                    translate([
                        lid_face_chamfer,
                        lid_face_chamfer,
                        lid_face_chamfer
                    ])
                        outer_brick(
                            case_x - 2*lid_face_chamfer,
                            case_y - 2*lid_face_chamfer,
                            0.001,
                            r=corner_radius - lid_face_chamfer
                        );
                }
            }
    }
}


// =====================================================================
// Render mode switch
// =====================================================================

mode = "lid";

if (mode == "tub") {
    back_tub();
} else if (mode == "lid") {
    front_lid_for_print();
} else if (mode == "cap") {
    button_cap_for_print();
} else if (mode == "caps") {
    translate([0, button_cap_flange_dia / 2, 0])
        button_cap_for_print();
    translate([0, button_cap_flange_dia / 2 + button_cap_flange_dia
                 + button_cap_print_gap, 0])
        button_cap_for_print();
} else if (mode == "lid_caps") {
    lid_with_caps_for_print();
} else if (mode == "all") {
    // Tub + lid side-by-side on the bed; caps move with the lid window.
    print_plate_gap = 5;
    back_tub();
    lid_with_caps_for_print(case_x + print_plate_gap, 0);
} else if (mode == "preview") {
    // Exploded preview: lid floats above tub. Useful for visual
    // sanity in OpenSCAD's preview window; do NOT export this.
    preview_gap = 20;
    color("LightSteelBlue")
        back_tub();
    translate([0, 0, tub_top - lid_skirt_h + preview_gap])
        color("Wheat", 0.85)
            front_lid();
}