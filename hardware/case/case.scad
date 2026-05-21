// PiWalletSV reference case — parametric OpenSCAD source.
//
// Two-piece press-fit clamshell, :
// back_tub — deep half with full side walls, integrated camera
// mount, Pi standoffs, lens cone, lanyard hole.
// front_lid — flat half with the LCD window, joystick + button
// cutouts, and a short skirt that press-fits into a
// registration step on the back tub. No screws needed.
//
// Render with `mode = "tub"`, `"lid"`, or `"all"` at the bottom of
// this file, then File → Render (F6) → Export → STL. `"all"` shows
// an exploded preview for visual sanity checks; do NOT export it.
//
// Hardware targets: Raspberry Pi Zero 2 W + Adafruit 1.3" 240×240
// TFT bonnet (product 4506) + Arducam OV5647 Mini camera (Arducam
// product B0033 / Amazon ASIN B01LY05LOE), with the LCD facing the
// operator and the camera lens facing the back of the unit on the
// same optical axis. Camera dimensions in the "Camera" datum block
// below are PENDING caliper verification on arrival.
//
// Every dimension is a named variable. Future hardware swaps (Pi 5,
// different camera, different bonnet) should be a one-line change in the
// "Primitives" section. Derived dimensions live below in "Derived"
// and are computed from primitives only — never edit them directly.
// See SPEC.md for the design rationale and the canonical hardware
// datums this model is built against.
//
// Coordinate convention:
// x = horizontal (left/right), aligned with bonnet's long edge
// y = vertical (up/down on the operator face)
// z = depth (front-to-back, LCD-side positive)
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
// ribbon_under_pi: vertical slot between the camera module's top
// and the Pi PCB's bottom for the CSI flex's U-turn. The 22→15-pin
// adapter cable can be coaxed into a ~3 mm radius bend; 6 mm gives
// that with a little slack for the connector tabs. Verify on
// hardware before committing the final depth.
// pi_pcb_to_lcd_top: measured 2026-05-15 with the bonnet fully
// seated on the Pi GPIO header — Pi PCB BOTTOM face to LCD glass
// TOP face, header pin protrusion under the Pi excluded.
// front_slack: clamp budget between the LCD top and the front lid's
// inner face. The silicone joystick base used to be the constraint
// here (it's ~1.1 mm TALLER than the LCD plane) — Loop 2 moved
// that constraint into a dedicated pocket on the lid's inner face
// (see joystick_silicone_pocket_*), so front_slack is now bounded
// only by the LCD top. Pulled tight to 0.5 mm so the LCD glass
// sits as close to flush with the lid surface as possible.
ribbon_under_pi = 6.0;
pi_pcb_to_lcd_top = 14.0;
front_slack = 0.5;

// Lid retention — press-fit only, no screws. The back tub's top
// edge steps inward by `lid_skirt_step` for the last `lid_skirt_h`
// mm; the front lid carries a matching skirt that presses into that
// step and is held by friction alone. The user confirmed in Loop 1
// ("the lid and tub fit together very nice and tight") that the
// existing clearance value gives a snug press-fit.
lid_skirt_h = 4.0;
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
front_lane = 0.0;
back_lane = chin_height;

// The bonnet/Pi PCB outline. Pi Zero 2 W is 65 × 30; the bonnet
// extends slightly past it (Adafruit lists 65.5 × 30.6).
bonnet_pcb_x = 65.5;
bonnet_pcb_y = 30.6;

// Pi corner mounting holes — 58 × 23 mm pitch centred on the PCB.
mount_inset_x = 3.5;
mount_inset_y = 3.5;
mount_pitch_x = 58.0;
mount_pitch_y = 23.0;

// LCD geometry. lcd_module is the glass outline; lcd_active_area is
// the lit-pixel rectangle, smaller than the glass; lcd_active_area_offset
// is the bottom-left of the visible pixels in PCB-frame. All three
// are direct calipered measurements (2026-05-15).
lcd_module = [26.12, 26.12];
lcd_active_area = [23.74, 23.74];
lcd_active_area_offset = [19.0, 5.0];
lcd_window_clearance = 0.4;

// Joystick + button cutouts. Centres in PCB-frame, pulled from
// Adafruit's official 4506 STEP file (Adafruit_CAD_Parts repo);
// agree with calipers to within 0.5 mm.
//
// The 4506 ships with a SQUARE silicone cap that surrounds the
// SKQUBAE010 joystick switch and presents a tall round stem to the
// user. Measured 2026-05-16:
// - silicone base: 12.2 × 12.2 × 3.4 mm, sits on the bonnet PCB
// - stem: Ø 7.22 mm × ~7 mm tall, rises from the base
// Cap-top sits about 10.4 mm above the bonnet PCB, well above the
// LCD plane, so the stem has to poke through the front lid.
//
// The 5-way switch underneath the cap pivots roughly 2-3 mm above
// the PCB. At ~15° tilt that sweeps the stem laterally by ~0.8 mm
// at the lid inner face and ~1.4 mm at the outer face, so the lid
// hole is widened with a frustum (narrow inside, wider outside) to
// give the cap room to tilt without binding on the hole edge.
//
// joystick_dia — through-hole diameter at the lid INNER face
// (stem OD + 2×tilt + FDM clearance)
// joystick_well_dia — outer-face dish diameter (stem OD + 2×tilt
// at outer face + FDM clearance + a touch of
// visual breathing room)
// joystick_well_depth— how deep the outer dish recesses into the
// lid; the dish reads as a small "joystick
// pocket" on the front of the case.
joystick_dia = 9.5;
joystick_well_dia = 11.0;
// Reduced from 1.5 to 1.0 mm so the well's z-range and the
// silicone pocket's z-range together don't leave a sub-mm "ceiling"
// of plastic floating in the lid. With pocket_depth = 1.5 and
// well_depth = 1.0, the two recesses overlap by 0.1 mm inside the
// Ø 11 well footprint — that overlap area becomes a clean
// through-hole, giving the joystick stem unrestricted clearance.
joystick_well_depth = 1.0;
button_dia = 4.0;
joystick_centre = [ 8.128, 13.462]; // STEP: SKQUBAE010:SW3
button_a_centre = [53.848, 9.271]; // STEP: 6MM_SMT:SW2 (GPIO 5)
button_b_centre = [61.087, 15.748]; // STEP: 6MMX6MM_TACTILE_SMT:SW1 (GPIO 6)

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
usb_cutout_w = 8.0;
usb_cutout_h = 3.5;
usb_pwr_x_offset = 54.0; // micro-USB PWR-IN, measured 2026-05-15
usb_data_x_offset = 41.0; // micro-USB OTG, ESTIMATE — verify
hdmi_cutout_enabled = false;
hdmi_cutout_w = 11.5;
hdmi_cutout_h = 4.5;
hdmi_x_offset = 12.4; // mini-HDMI, ESTIMATE — verify

// z position of the micro-USB jack opening centre, measured from
// the back tub's interior floor. Pi PCB top sits at
// (camera_post_height + camera_module_z + ribbon_under_pi +
// pi_pcb_thickness ~ 1.6); the jack opening is ~2.5 mm above PCB top.
pi_pcb_thickness = 1.6;
usb_jack_z_above_pi_top = 2.5;

// microSD-slot cutout. Notch through the LEFT short-edge wall of
// the back tub, centred vertically on the Pi PCB level so the
// card's edge aligns with the Pi's SD slot. Disable in production
// for tamper resistance; keep enabled for prototype + service.
sd_cutout_enabled = true;
sd_cutout_w = 14.0; // along the y axis
sd_cutout_h = 3.0; // along the z axis

// Camera: Arducam UC-346 OV5647 (standard Pi Camera footprint).
// Ships with a 15-pin↔22-pin Pi-Zero ribbon. OV5647 is the same
// sensor for phone-screen QR scans at held-up distance.
//
// Confirmed measurements (2026-05-21, calipers):
// PCB outline: 25.1 × 24.2 mm
// PCB thickness: 1.55 mm
// Lens height: 7.14 mm (PCB bottom to top of lens housing)
//
// Remaining estimates (Loop 3 fit-test will confirm):
// camera_lens_centre — sensor array centre is within 0.35 mm of
// die centre per OV5647 datasheet; lens assumed centred on PCB.
// camera_mount_pitch — standard Pi Camera module corner pattern:
// 21 mm × 12.5 mm (2 mm inset from each edge). Verify post
// alignment on first tub print; adjust if posts miss holes.
// camera_mount_dia — M2 clearance, standard for this class.
//
// FFC orientation: connector exits from the SHORT bottom edge of the
// PCB (the edge nearest the Pi's CSI ZIF). The ribbon folds under
// the Pi toward the CSI connector. The PCB is nearly square so
// portrait/landscape distinction is minor, but x is the slightly
// longer dimension (25.1 mm).
camera_module_x = 25.1; // confirmed: PCB edge along x (FFC on bottom/near edge)
camera_module_y = 24.2; // confirmed: PCB edge along y
camera_module_z = 7.14; // confirmed: PCB bottom to top of lens housing
camera_lens_centre = [12.55, 12.1]; // estimated: centred on PCB; verify lens-cone alignment on print
camera_mount_pitch = [12.5, 21.0]; // estimated: standard Pi Camera corner pattern; verify on print
camera_mount_dia = 2.2; // estimated: M2 clearance

// Back-tub posts the camera screws onto. Each post rises from the
// tub's inner floor and pilots an M2 self-tap.
camera_post_height = 3.0;
camera_post_outer = 4.0;
camera_post_pilot = 1.7;

// Pi standoff posts (in the back tub). Pi sits on these by its 4
// corner mount holes. Height calculated from the stack-up below.
pi_standoff_outer = 5.0;
pi_standoff_pilot = 2.0; // M2.5 self-tap (optional)

// Lens cone in the back tub's back wall.
lens_cone_dia = 8.0;
lens_cone_recess = 3.0;
lens_cone_chamfer = 60; // half-angle, degrees

// Lanyard hole (back tub, top-right corner of the back wall).
// Loop 1 print showed the hole as drawn was unusable — keeping it
// disabled until we revisit the geometry (probably wants to be a
// flat tab with a slot, not a round hole through a curved wall).
lanyard_enabled = false;
lanyard_dia = 4.0;
lanyard_inset = 4.0;

// Tamper-sticker keep-out box on the back wall.
tamper_box_w = 12.0;
tamper_box_h = 6.0;
tamper_box_depth = 0.4;

// Cosmetic detailing — these don't affect fit, only the visual feel.
//
// corner_radius: vertical fillet on the four vertical edges of the
// case. ~3 mm gives a soft-brick look without eating wall thickness.
// lid_face_chamfer: small bevel on the lid's outer top edge so the
// lid catches light and doesn't read as a featureless plate.
// lcd_bezel_*: a shallow recess around the LCD window so the screen
// looks framed rather than punched through.
corner_radius = 3.0;
lid_face_chamfer = 0.8;
lcd_bezel_border = 2.0;
// Loop 1 feedback: the LCD looked deep below the lid surface. Two
// fixes stacked: drop front_slack from 1.0 to 0.5 (LCD nudged
// closer to the lid inner face) and deepen this bezel recess from
// 0.5 to 1.0 (lid is locally thinner around the screen). Wall
// thickness inside the bezel ring is wall - lcd_bezel_depth =
// 1.4 mm, still printable.
lcd_bezel_depth = 1.0;

// Silicone joystick base pocket. The 4506's silicone joystick
// cover has a 12.2 × 12.2 × 3.4 mm square base that sits on the
// bonnet PCB around the joystick. The base is ~1.1 mm taller than
// the LCD plane, which forced the lid to sit 1.1 mm above the LCD
// and made the screen look deep below the lid surface. Fix: cut
// a square pocket into the lid's INNER face for the silicone base
// to nest into, so the lid can come down to LCD-flush.
//
// Pocket size: silicone base + 0.5 mm clearance per side.
// Pocket depth: enough that the silicone has ~0.9 mm headroom inside
// the pocket (pocket_depth - silicone_overhang).
// Combined with joystick_well_depth, the pocket and well overlap in
// z by 0.1 mm — the well merges with the pocket inside the well's
// circular footprint, giving the joystick stem a clean Ø 11 opening
// without leaving a fragile 0.1 mm "ceiling" of plastic.
joystick_silicone_pocket_w = 13.2;
joystick_silicone_pocket_h = 13.2;
joystick_silicone_pocket_depth = 1.5;

// Cosmetic: how smooth round features are. Bump at print time, not
// while editing.
$fn = 64;

// =====================================================================
// Derived dimensions
// =====================================================================

// Internal cavity (the box that holds the stack).
cavity_x = bonnet_pcb_x + 2*clearance + 2;
cavity_y = bonnet_pcb_y + 2*clearance + 2;

// Cavity depth — explicit stack-up from camera floor up to LCD top.
// Every term is a primitive above; a single component swap (taller
// camera, thicker bonnet, different ribbon) propagates here.
cavity_z =
 camera_post_height + // 3.0 posts lifting camera off back floor
 camera_module_z + // 11.5 camera body
 ribbon_under_pi + // 6.0 CSI U-turn slot below Pi
 pi_pcb_to_lcd_top + // 14.0 measured (Pi PCB bottom → LCD top)
 front_slack; // 1.0
 // = 35.5 mm internal

// External case dimensions. With no screw lanes the footprint is
// cavity + 2*wall on every axis — much slimmer rim than before.
case_x = cavity_x + 2*wall;
case_y = cavity_y + 2*wall + front_lane + back_lane;
case_z = cavity_z + 2*wall;

cavity_origin_x = wall;
cavity_origin_y = wall + front_lane;

// Bonnet's bottom-left corner in case-frame. The cavity is bigger
// than the PCB by 2*clearance + 2 mm on each axis; we centre the
// PCB in the cavity so clearance is symmetric on all four sides.
bonnet_origin_x = cavity_origin_x + (cavity_x - bonnet_pcb_x) / 2;
bonnet_origin_y = cavity_origin_y + (cavity_y - bonnet_pcb_y) / 2;

// LCD optical centre in PCB-frame.
lcd_active_centre = [
 lcd_active_area_offset.x + lcd_active_area.x / 2,
 lcd_active_area_offset.y + lcd_active_area.y / 2,
]; // = (30.87, 16.87)
lcd_window_x = lcd_module.x + 2*lcd_window_clearance;
lcd_window_y = lcd_module.y + 2*lcd_window_clearance;
lcd_bezel_x = lcd_window_x + 2*lcd_bezel_border;
lcd_bezel_y = lcd_window_y + 2*lcd_bezel_border;

// Camera mount pattern offset (centring the 10.8×10.8 hole pattern
// inside the 25×24 board).
camera_mount_inset = [
 (camera_module_x - camera_mount_pitch.x) / 2,
 (camera_module_y - camera_mount_pitch.y) / 2,
]; // = (7.1, 6.6)

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
tub_top = case_z - wall; // = 37.9

// (No screw boss positions — press-fit only.)

// Camera anchor in case-coords. We position the camera so its lens
// optical axis lands directly behind the LCD's optical centre.
//
// lens_in_case = bonnet_origin + lcd_active_centre
// = camera_anchor + camera_lens_centre
// ⇒ camera_anchor = bonnet_origin + lcd_active_centre - camera_lens_centre
camera_anchor_x = bonnet_origin_x + lcd_active_centre.x - camera_lens_centre.x;
camera_anchor_y = bonnet_origin_y + lcd_active_centre.y - camera_lens_centre.y;
lens_x = camera_anchor_x + camera_lens_centre.x;
lens_y = camera_anchor_y + camera_lens_centre.y;

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
 difference() {
 union() {
 // Outer brick with rounded vertical corners. No front
 // face — the lid provides it.
 outer_brick(case_x, case_y, tub_top);

 // Camera mount posts.
 for (p = camera_post_positions())
 translate([p.x, p.y, wall])
 cylinder(h=camera_post_height, d=camera_post_outer);

 // Pi standoff posts.
 for (p = pi_standoff_positions())
 translate([p.x, p.y, wall])
 cylinder(h=pi_standoff_height, d=pi_standoff_outer);
 }

 // Main cavity — full size from back wall up to the start of
 // the registration step.
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

 // Stepped cavity — wider rectangle from the start of the
 // step up to the seam, eating into the side walls' inner
 // half so a lip is formed for the lid skirt to drop into.
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

 // Pi standoff pilot holes (M2.5 self-tap, optional).
 for (p = pi_standoff_positions())
 translate([p.x, p.y, -1])
 cylinder(
 h=wall + pi_standoff_height + 2,
 d=pi_standoff_pilot
 );

 // Camera mount pilot holes (M2 self-tap, drilled through
 // the post + back wall so screws can be inserted from
 // behind).
 for (p = camera_post_positions())
 translate([p.x, p.y, -1])
 cylinder(
 h=wall + camera_post_height + 2,
 d=camera_post_pilot
 );

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

 // Tamper-sticker keep-out recess.
 translate([
 case_x/2 - tamper_box_w/2,
 case_y - wall - tamper_box_h - 1,
 wall - tamper_box_depth + 0.001
 ])
 cube([tamper_box_w, tamper_box_h, tamper_box_depth + 0.01]);

 // Pi I/O cluster cutouts — all pierce the FRONT (low-y) side
 // wall from the cavity outward. The Pi's bottom long edge
 // (HDMI + 2× micro-USB) faces this edge in our orientation:
 // bonnet's stemmaQT label and Pi's I/O cluster sit on the
 // same long edge of the assembly. x in bonnet-frame, z
 // centred at the jack opening height.
 for (port = [
 // [x_offset, w, h, enabled]
 [usb_pwr_x_offset, usb_cutout_w, usb_cutout_h, true],
 [usb_data_x_offset, usb_cutout_w, usb_cutout_h, true],
 [hdmi_x_offset, hdmi_cutout_w, hdmi_cutout_h, hdmi_cutout_enabled]
 ]) if (port[3]) {
 translate([
 bonnet_origin_x + port[0] - port[1]/2,
 -1,
 usb_jack_z - port[2]/2
 ])
 cube([
 port[1],
 cavity_origin_y + 1,
 port[2]
 ]);
 }

 // microSD-slot cutout — pierces the LEFT short-edge wall,
 // sits at Pi PCB level, spans from outer wall inward to the
 // cavity. The Pi's SD slot lip protrudes a couple mm beyond
 // the PCB so the card edge can be reached for swap/service.
 if (sd_cutout_enabled) {
 translate([
 -1,
 cavity_origin_y + cavity_y/2 - sd_cutout_w/2,
 wall + pi_standoff_height
 - pi_pcb_thickness/2 - sd_cutout_h/2
 ])
 cube([
 cavity_origin_x + 1,
 sd_cutout_w,
 sd_cutout_h
 ]);
 }
 }
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

 // LCD bezel recess — shallow rectangular dish on the OUTER
 // face, slightly larger than the LCD window. Makes the
 // screen look framed rather than punched through.
 translate([
 bonnet_origin_x + lcd_active_centre.x,
 bonnet_origin_y + lcd_active_centre.y,
 lid_skirt_h + wall - lcd_bezel_depth + 0.001
 ])
 rrect(lcd_bezel_x, lcd_bezel_y,
 lcd_bezel_depth + 0.01, r=2);

 // LCD window — punched through the slab (and through the
 // bottom of the bezel) at the active area centre.
 translate([
 bonnet_origin_x + lcd_active_centre.x,
 bonnet_origin_y + lcd_active_centre.y,
 lid_skirt_h - 1
 ])
 rrect(lcd_window_x, lcd_window_y, wall + 2, r=1.5);

 // Joystick cutout. Three-stage:
 // 1. through-hole sized for the rubber cap stem
 // 2. conical well on the OUTER face (joystick "dish")
 // 3. SQUARE pocket on the INNER face for the silicone
 // base to nest into — lets the lid drop close to the
 // LCD without crushing the silicone.
 translate([
 bonnet_origin_x + joystick_centre.x,
 bonnet_origin_y + joystick_centre.y,
 lid_skirt_h - 1
 ])
 cylinder(h=wall + 2, d=joystick_dia);
 translate([
 bonnet_origin_x + joystick_centre.x
 - joystick_silicone_pocket_w/2,
 bonnet_origin_y + joystick_centre.y
 - joystick_silicone_pocket_h/2,
 lid_skirt_h - 0.001
 ])
 cube([
 joystick_silicone_pocket_w,
 joystick_silicone_pocket_h,
 joystick_silicone_pocket_depth + 0.001
 ]);
 translate([
 bonnet_origin_x + joystick_centre.x,
 bonnet_origin_y + joystick_centre.y,
 lid_skirt_h + wall - joystick_well_depth
 ])
 cylinder(
 h=joystick_well_depth + 0.01,
 d1=joystick_dia,
 d2=joystick_well_dia
 );

 // Plain button through-holes.
 for (p = [button_a_centre, button_b_centre])
 translate([
 bonnet_origin_x + p.x,
 bonnet_origin_y + p.y,
 lid_skirt_h - 1
 ])
 cylinder(h=wall + 2, d=button_dia);

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

// "tub" | "lid" | "all"
mode = "all";

if (mode == "tub") {
 back_tub();
} else if (mode == "lid") {
 front_lid();
} else if (mode == "all") {
 // Exploded preview: lid floats above tub. Useful for visual
 // sanity in OpenSCAD's preview window; do NOT export this — it
 // isn't a printable body. The gap is purely cosmetic; in the
 // assembled state the lid skirt drops into the tub's step with
 // no air between the two parts.
 preview_gap = 20;
 color("LightSteelBlue")
 back_tub();
 translate([0, 0, tub_top - lid_skirt_h + preview_gap])
 color("Wheat", 0.85)
 front_lid();
}
