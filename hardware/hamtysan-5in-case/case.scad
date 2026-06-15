// HAMTYSAN HCIG050V.CP1 — two-piece clamshell enclosure
//
// Correct physical dimensions (5-inch, NOT the 7-inch specs):
//   PCB outline:   121.11 × 77.93 mm
//   Active area:   108.00 × 64.80 mm
//   PCB depth:     ~12 mm internal minimum (components on back)
//   Ports:         HDMI + micro-USB on one side, no audio jack
//   Mount holes:   M2.5, four corners
//
//   back_shell  — tray; PCB screws onto M2.5 standoff posts
//   front_bezel — frame; SAME 4 × M2.5 × 12 mm screws clamp both
//                 the PCB and the bezel in one pass
//
// Bezel attachment:
//   The 4 M2.5 screws go front-to-back: bezel clearance hole → PCB M2.5
//   mounting hole → standoff blind hole.  No extra hardware.
//   Corners are fully solid — no holes visible from any exterior face.
//
// Render modes: mode = "shell" | "bezel" | "all" | "preview"
//
// Coordinate convention:
//   origin = bottom-left-rear corner (outside back plate)
//   +x = right
//   +y = up
//   +z = toward operator / LCD face (shell open at max-z)


// =====================================================================
// Primitives — verify with calipers before final print
// =====================================================================

wall       = 2.4;
back_plate = 5.0;  // thicker back plate — VESA rigidity, 2.6 mm floor below standoffs
port_wall  = 1.6;  // port-side wall — 1.6 mm so cable shrouds seat fully
clearance  = 0.5;  // PETG expansion buffer per side

// --- PCB ---
pcb_x = 121.11;
pcb_y = 77.93;

// Minimum internal depth: PCB (5.7 mm glass+board) + rear components
// User spec: 12.0 mm minimum
cavity_depth = 12.0;

// --- LCD active area (pixel area, not glass) ---
lcd_active_x = 108.0;
lcd_active_y = 64.8;

// Active area offset from PCB bottom-left corner
lcd_offset_x = (pcb_x - lcd_active_x) / 2;   // ~6.56 mm
lcd_offset_y = (pcb_y - lcd_active_y) / 2;   // ~6.57 mm

// --- LCD window in bezel: active area + 0.5 mm clearance per side ---
lcd_win_x = lcd_active_x + 1.0;   // 109.0 mm
lcd_win_y = lcd_active_y + 1.0;   // 65.8 mm

// --- PCB M2.5 standoff posts (inside shell cavity) ---
// Distance of hole centres from PCB edges — measure your board.
// These are conservative estimates for the standard corner-tab layout.
m25_inset_x = 4.5;
m25_inset_y = 4.5;
m25_dia     = 2.7;   // M2.5 clearance through-hole
standoff_h  = 5.0;   // lifts PCB off back plate
standoff_od = 6.0;

// M2.5 pan-head screw recess on bezel front face (keeps heads flush/recessed)
m25_head_d = 5.2;   // M2.5 pan head OD ≈ 5.0 mm + 0.2 mm clearance
m25_head_z = 1.5;   // recess depth — head sits flush or slightly below surface

// --- Bezel glass-retention lip ---
bezel_lip_depth = 1.4;
bezel_lip_inset = 1.5;   // plastic overlaps glass perimeter by this much

// --- Bezel registration skirt drops into shell rim ---
rim_skirt_h   = 3.0;
rim_skirt_gap = 0.4;   // FDM clearance per side

// --- Side-wall port cutouts ---
// Ports on the right side (+x wall) when display faces front.
// From PCB back photo (PHA050-B04-V01): ports on left edge of back =
// right edge of front. Order top→bottom: HDMI_IN, USB_TOUCH, +5V_IN.
//
// _y = centre distance from bottom of PCB (= from pcb_oy inside shell).
// _cz = centre height above back-plate inner face (~7.5 mm = mid-depth).
// along_edge = opening dimension up/down the side wall (Y axis).
// depth      = opening dimension front-to-back through the wall (Z axis).
// *** Tune _y values after first fit-test — estimated from PCB photo ***
port_edge = "right";

// +5V_IN — bottom micro-USB (power)
usb_pwr_y          = 16.0;   // ~16 mm from PCB bottom edge
usb_pwr_cz         =  7.5;
usb_pwr_along_edge = 11.5;   // 11.5 mm up/down
usb_pwr_depth      =  6.5;   // 6.5 mm front-to-back

// USB_TOUCH — middle micro-USB (capacitive touch data)
usb_touch_y          = 36.0;   // ~36 mm from PCB bottom edge (revised from photo)
usb_touch_cz         =  7.5;
usb_touch_along_edge = 11.5;
usb_touch_depth      =  6.5;

// HDMI_IN — full-size HDMI (top port, above the two USBs)
// Moved to 57 mm (down from 62) so the 18 mm opening clears the M2.5 standoff
// at y ≈ 73.3 mm.  along_edge reduced to 18 mm (was 22) to gain that clearance.
hdmi_y          = 57.0;   // ~57 mm from PCB bottom edge
hdmi_cz         =  7.5;
hdmi_along_edge = 18.0;   // 18 mm up/down — clears standoff boss above it
hdmi_depth      = 12.5;   // 12.5 mm front-to-back

// --- Passive vent slots on back plate ---
vent_enabled  = true;
vent_slot_len = 20.0;
vent_slot_w   = 2.0;
vent_count    = 4;
vent_spacing  = 6.0;

// --- Optional VESA 50 × 50 mm back-plate pattern ---
vesa_enabled = true;
vesa_pitch   = 50.0;
vesa_hole_d  = 3.2;   // M3 clearance; user installs heat-set inserts

corner_radius = 2.5;


// =====================================================================
// Derived
// =====================================================================

cavity_x = pcb_x + 2 * clearance;   // 122.11 mm
cavity_y = pcb_y + 2 * clearance;   // 78.93 mm

// Port side wall is thinner (1.6 mm) than the other three walls (2.4 mm)
shell_x = (port_edge == "right")
    ? cavity_x + wall + port_wall
    : cavity_x + port_wall + wall;
shell_y = cavity_y + 2 * wall;
shell_z = back_plate + cavity_depth + wall;   // back plate + cavity + front rim

pcb_ox = wall + clearance;   // PCB origin x inside shell
pcb_oy = wall + clearance;   // PCB origin y inside shell

lcd_win_x0 = pcb_ox + lcd_offset_x - 0.5;
lcd_win_y0 = pcb_oy + lcd_offset_y - 0.5;

bezel_t = wall + bezel_lip_depth;   // total bezel plate thickness

// PCB M2.5 standoff centres (inside cavity)
m25_positions = [
    [pcb_ox + m25_inset_x,              pcb_oy + m25_inset_y],
    [pcb_ox + pcb_x - m25_inset_x,      pcb_oy + m25_inset_y],
    [pcb_ox + m25_inset_x,              pcb_oy + pcb_y - m25_inset_y],
    [pcb_ox + pcb_x - m25_inset_x,      pcb_oy + pcb_y - m25_inset_y]
];

// VESA hole centres on back-plate exterior
vesa_cx = shell_x / 2;
vesa_cy = shell_y / 2;
vesa_positions = [
    [vesa_cx - vesa_pitch/2, vesa_cy - vesa_pitch/2],
    [vesa_cx + vesa_pitch/2, vesa_cy - vesa_pitch/2],
    [vesa_cx - vesa_pitch/2, vesa_cy + vesa_pitch/2],
    [vesa_cx + vesa_pitch/2, vesa_cy + vesa_pitch/2]
];


// =====================================================================
// Helpers
// =====================================================================

module rounded_box(size, r, fn = 36) {
    sx = size[0]; sy = size[1]; sz = size[2];
    if (r <= 0) {
        cube(size);
    } else {
        hull()
            for (dx = [0, sx - 2*r], dy = [0, sy - 2*r])
                translate([r + dx, r + dy, 0])
                    cylinder(h = sz, r = r, $fn = fn);
    }
}

module cyl_at(cx, cy, z0, z1, d) {
    translate([cx, cy, z0 - 0.01])
        cylinder(h = z1 - z0 + 0.02, d = d, $fn = 32);
}

module standoff(cx, cy) {
    // Post rises from z = 0 through the back plate and up into the cavity.
    // The PCB face lands at z = back_plate + standoff_h.
    // Blind hole at the top accepts an M2.5 self-tapping screw from the front.
    blind_depth = 4.5;
    total_h = back_plate + standoff_h;
    translate([cx, cy, 0]) {
        difference() {
            cylinder(h = total_h, d = standoff_od, $fn = 48);
            translate([0, 0, total_h - blind_depth])
                cylinder(h = blind_depth + 0.01, d = m25_dia, $fn = 32);
        }
    }
}

// along_edge = dimension up/down the side wall (Y axis)
// depth      = dimension front-to-back through the wall (Z axis)
// centre_z   = height above the cavity floor (= back_plate inner face)
module one_port(centre_y, centre_z, along_edge, depth) {
    y0 = pcb_oy + centre_y - along_edge / 2;
    z0 = back_plate + centre_z - depth / 2;
    if (port_edge == "right") {
        translate([shell_x - port_wall - 0.01, y0, z0])
            cube([port_wall + 0.02, along_edge, depth]);
    } else {
        translate([-0.01, y0, z0])
            cube([port_wall + 0.02, along_edge, depth]);
    }
}

module port_cutouts() {
    one_port(usb_pwr_y,   usb_pwr_cz,   usb_pwr_along_edge,   usb_pwr_depth);   // +5V_IN (bottom)
    one_port(usb_touch_y, usb_touch_cz, usb_touch_along_edge, usb_touch_depth); // USB_TOUCH (middle)
    one_port(hdmi_y,      hdmi_cz,      hdmi_along_edge,       hdmi_depth);      // HDMI_IN (top)
}

module vent_slots() {
    if (vent_enabled) {
        total_w = (vent_count - 1) * vent_spacing + vent_slot_len;
        x0 = (shell_x - total_w) / 2;

        // Top-edge row
        for (i = [0 : vent_count - 1]) {
            translate([x0 + i * vent_spacing, shell_y * 0.7, -0.01])
                cube([vent_slot_len, vent_slot_w, back_plate + 0.02]);
        }
        // Bottom-edge row
        for (i = [0 : vent_count - 1]) {
            translate([x0 + i * vent_spacing, shell_y * 0.3 - vent_slot_w, -0.01])
                cube([vent_slot_len, vent_slot_w, back_plate + 0.02]);
        }
    }
}

module vesa_holes() {
    if (vesa_enabled) {
        for (pos = vesa_positions)
            cyl_at(pos[0], pos[1], 0, back_plate + 0.01, vesa_hole_d);
    }
}


// =====================================================================
// Back shell
// =====================================================================

module back_shell() {
    difference() {
        // Main tray — no separate boss cylinders needed; the outer corner
        // wall material (1.5 mm from edges) is solid all the way through.
        rounded_box([shell_x, shell_y, shell_z], corner_radius);

        // PCB cavity — starts at back_plate (5 mm) so the thicker floor is
        // preserved; cut through the front rim so the shell is open at the top.
        translate([wall, wall, back_plate])
            cube([cavity_x, cavity_y, cavity_depth + wall + 1]);

        // Three separate port cutouts
        port_cutouts();

        // Back-plate vent slots
        vent_slots();

        // VESA holes
        vesa_holes();
    }

    // Standoff posts — added outside the difference so the cavity
    // subtraction doesn't remove them
    for (pos = m25_positions)
        standoff(pos[0], pos[1]);
}


// =====================================================================
// Front bezel
// =====================================================================

module front_bezel() {
    // Retention lip geometry
    lip_x  = pcb_x - 2 * bezel_lip_inset;
    lip_y  = pcb_y - 2 * bezel_lip_inset;
    lip_x0 = pcb_ox + bezel_lip_inset;
    lip_y0 = pcb_oy + bezel_lip_inset;

    // Registration skirt fits into shell rim cavity
    skirt_x  = cavity_x - 2 * rim_skirt_gap;
    skirt_y  = cavity_y - 2 * rim_skirt_gap;
    skirt_x0 = wall + rim_skirt_gap;
    skirt_y0 = wall + rim_skirt_gap;

    difference() {
        union() {
            // Front plate
            rounded_box([shell_x, shell_y, bezel_t], corner_radius);

            // Glass-retention lip (inward projection, behind front face)
            translate([lip_x0, lip_y0, -bezel_lip_depth])
                cube([lip_x, lip_y, bezel_lip_depth + 0.01]);

            // Registration skirt
            translate([skirt_x0, skirt_y0, -rim_skirt_h])
                cube([skirt_x, skirt_y, rim_skirt_h + 0.01]);
        }

        // LCD window
        translate([lcd_win_x0, lcd_win_y0, -(bezel_lip_depth + rim_skirt_h) - 0.01])
            cube([lcd_win_x, lcd_win_y, bezel_t + bezel_lip_depth + rim_skirt_h + 0.02]);

        // M2.5 screw clearance holes — same positions as PCB standoffs.
        // Each hole passes through the full bezel depth (plate + lip + skirt) so
        // the screw can reach: bezel face → PCB M2.5 hole → standoff blind hole.
        for (pos = m25_positions) {
            cyl_at(pos[0], pos[1],
                   -(bezel_lip_depth + rim_skirt_h), bezel_t + 0.01,
                   m25_dia);
            // Pan-head recess on the front face — head sits flush
            cyl_at(pos[0], pos[1],
                   bezel_t - m25_head_z, bezel_t + 0.01,
                   m25_head_d);
        }
    }
}


// =====================================================================
// Print layouts
// =====================================================================

module front_bezel_for_print() {
    // Flip face-down for printing
    translate([0, 0, bezel_t + rim_skirt_h])
        rotate([180, 0, 0])
            front_bezel();
}

module print_plate(gap = 10) {
    back_shell();
    translate([shell_x + gap, 0, 0])
        front_bezel_for_print();
}


// =====================================================================
// Render mode
// =====================================================================

mode = "all";

if (mode == "shell") {
    back_shell();
} else if (mode == "bezel") {
    front_bezel_for_print();
} else if (mode == "all") {
    print_plate();
} else if (mode == "preview") {
    color("SteelBlue")
        back_shell();
    translate([0, 0, shell_z + 8])
        color("Wheat", 0.85)
            front_bezel();
} else {
    echo("Unknown mode — use shell, bezel, all, or preview");
}
