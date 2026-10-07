// PiWalletSV pro-unit tub — Pi 3 Model B v1.2 + Waveshare 3.5" LCD (F).
//
// Open this file in OpenSCAD.
// mode = "preview" — tub plus a ghost of the glass and the stack
// mode = "case"    — tub only (F6 render, then export STL)
//
// Origin: outer corner of the tub floor, where the microSD end
// meets the GPIO edge. z = 0 is the outside of the floor.
// x runs toward USB/Ethernet. y runs toward power, HDMI, and audio.
// The hat is on the solder side, so those jacks are the far long edge.

// =====================================================================
// Primitives
// =====================================================================

glass_x = 92.5; // measured; wiki drawing is 92.44 ± 0.20
glass_y = 61.00; // measured; wiki drawing is 61.00 ± 0.20
glass_r = 4.0;

// Border outside the glass. The side wall is rim minus the seat gap.
// 1.5 flexed when the long sides were squeezed.
rim = 2.5;
// Extra pocket around the glass so it can drop in.
seat_gap = 0.3;
// Lip overlaps the black bezel. Active-area margin is 5.82 mm.
lip_overlap = 1.2;
// Measured glass thickness. The screen drops this far into the top.
screen_t = 0.8;
// Rim stands this far above the glass face so a squeeze does not
// pop the glass over the edge.
lip_rise = 0.5;
// Flat shelf under the glass, then a 45° print slope.
lip_land = 1.0;

floor_t = 3.0;
// Measured: screen face to the bottom of the USB connectors.
stack_h = 31.2;
// Extra cavity so the stack fits. Slack ends up at the floor.
depth_slack = 1.0;
// Standoffs sit on the top of the Pi board and screw into the hat.
// The screw opening is this far from that face, toward the floor.
standoff_h = 11.0;

// Pi 3 Model B mechanical drawing. Board origin is the microSD end
// at the power/HDMI edge. x runs toward USB. y runs toward GPIO.
// Z-height runs from the top of the board (bottom of the component)
// to the top of the component. Corner radius of the
// board is 3.0 mm. The four holes are M2.5, drilled 2.75 ± 0.05;
// that diameter is the Pi, not the case bore.
pi_x = 85.0;
pi_y = 56.0;
pi_pcb_t = 1.6; // not on the drawing; shifts the SD window only
hole_inset = 3.5;
hole_pitch_x = 58.0; // 23.5 mm remains to the USB edge
hole_pitch_y = 49.0;
power_x = 10.6;
power_w = 8.0;  // shell on the drawing, 6.58 to 14.62
hdmi_x = 32.0;
hdmi_w = 14.5;  // shell 24.75 to 39.25
hdmi_over = 1.5; // shell past the board edge
audio_x = 53.5;
audio_d = 6.0;  // barrel
eth_y = 10.25;
usb_y = [29, 47];
// MicroSD shell on the drawing is 22.51 to 33.51, centered on the board.
// The card itself sits on the solder face, toward the screen.
sd_y0 = 22.5;
sd_y1 = 33.5;
// Red PWR LED on the component face at the microSD end, just inboard
// of the standoff at the power-edge corner (seen on a fit print).
// The drawing only places its label.
pwr_led_y = 7.25;
// ACT LED is next to it, farther from the power edge.
led_pitch = 3.6;
pwr_led_hole_d = 2.5;
power_z = 5.5; // drawing: board face to the top of the part
hdmi_z = 6.5;
audio_z = 6.0;
// The plug that passes the wall is shorter than power_z. A 6 mm
// opening left the jack on the board edge and a gap toward the floor.
power_hole_z = 3.6;
// Measured against the jacks on the print. Positive is toward the floor.
power_drop = 0.5;
hdmi_drop = 1.25;
audio_drop = 0.5;
// Barrel is 6 mm. 0.4 mm of fit made the hole loose.
audio_fit = 0.2;
// SD window was high of the card, toward the screen.
sd_drop = 1.0;
// Wider than the shell so tweezers can pinch the card. The card has
// to come out before the stack does.
sd_slot_w = 18.0;
// Slot centre is the drawing's card centre plus this, from three fit
// prints. Negative is toward the GPIO edge, the side with no openings.
sd_shift = -0.25;
eth_z = 13.5;
usb_z = 16.0;
gpio_z = 8.5;

// Bosses were about 1 mm tall of the glass seat. Shorten them so the
// screen can drop flush, and the standoff meets the boss as it does.
boss_trim = 1.0;
// Overall length, including the head. A 3.8 mm head is about 1.6 mm
// thick, so 4.4 mm of thread remains under it.
screw_len = 6.0;
head_h = 1.6;
thread_in = 2.0;
mount_od = 8.0;
screw_head_d = 3.8;
// Threads measure 2.4. Holes print about 0.2 small: 2.5 still had to be
// screwed in. At 3.8 (the head width) the head pulled through the boss.
screw_bore = 2.7;
screw_cbore_d = 5.2;

// Camera hold — same numbers as the Zero tub.
camera_post_h = 3.0;
camera_post_od = 5.0;
camera_post_pilot = 1.7;
camera_post_pilot_h = 2.5;
camera_pitch_x = 12.0; // along the FFC axis
camera_pitch_y = 21.0;
lens_d = 8.0;
// The screwed-down lens sat off the hole. Positive is toward the
// power/HDMI edge. The posts do not move.
lens_hole_dy = 0.8;
lens_cone_h = 3.0;
lens_cone_ang = 60;

$fn = 48;

// =====================================================================
// Derived
// =====================================================================

case_x = glass_x + 2 * rim;
case_y = glass_y + 2 * rim;
outer_r = glass_r + rim;

// Screen face is at tub_top. The rim stands lip_rise above it.
cavity_h = stack_h + depth_slack;
tub_top = floor_t + cavity_h;
case_top = tub_top + lip_rise;
// 45° underside spans the seat gap plus the lip overlap.
lip_chamfer = seat_gap + lip_overlap;
seat_z = tub_top - screen_t;

pocket_x0 = rim - seat_gap;
pocket_y0 = rim - seat_gap;
pocket_x = glass_x + 2 * seat_gap;
pocket_y = glass_y + 2 * seat_gap;
pocket_r = glass_r + seat_gap;

open_x0 = rim + lip_overlap;
open_y0 = rim + lip_overlap;
open_x = glass_x - 2 * lip_overlap;
open_y = glass_y - 2 * lip_overlap;
open_r = glass_r - lip_overlap;

// Wiki dimension drawing. Glass around the hat PCB, which matches the Pi.
// Short sides: 2.5 mm of glass past the PCB, then 3.5 mm to the hole.
// microSD end: 1.0 mm of glass past the PCB, then 3.5 mm to the hole.
// USB end takes the rest of the glass (about 6.5 mm).
// Case bores sit on those four holes, not on the glass centre.
sd_overhang = 1.0;
pi_x0 = rim + sd_overhang;
pi_y0 = rim + (glass_y - pi_y) / 2;
// Gap around a jack so the opening fits the shell.
jack_fit = 0.4;
// USB and Ethernet shell faces. The USB-end wall is flush with these,
// then slants out to the screen lip.
shell_x = 87.0;
// Room past the shell faces so the stack can slip in.
usb_wall_out = 1.0;
// Wall at the jack faces. Plugs have to reach the jacks through it.
wall_t = 1.2;
// Wall around the glass pocket.
lip_wall_t = rim - seat_gap;

// Screen face is flush with the top. USB bottoms are stack_h back from that face.
usb_bottom_z = tub_top - stack_h;
component_z = usb_bottom_z + usb_z;
solder_z = component_z + pi_pcb_t;
// Boss top is 1 mm short of the standoff so the glass can seat.
mount_reach = component_z - standoff_h - floor_t - boss_trim;
// Head recess leaves thread_in of the shank inside the Pi standoff.
screw_cbore_h = floor_t + mount_reach - (screw_len - head_h - thread_in);
usb_face = pi_x0 + shell_x + usb_wall_out;
// Power edge wall rests on the HDMI shell face (power is 1.22 mm,
// HDMI 1.50 mm past the board). Closer than this, the stack would
// not slide in. Only the audio barrel reaches into the wall.
port_face = pi_y0 + pi_y + hdmi_over + wall_t;
// Bottom slopes run from the top of the floor plate up to the wall
// face and stop at the lowest opening on that side.
usb_slope_z = usb_bottom_z - jack_fit;
port_slope_z = min(
  component_z - hdmi_z - jack_fit - hdmi_drop,
  component_z - power_hole_z - power_drop,
  component_z - audio_z / 2 - audio_drop - audio_d / 2 - audio_fit
);

lens_x = rim + glass_x / 2;
lens_y = rim + glass_y / 2;

echo(case_x=case_x, case_y=case_y, tub_top=tub_top, case_top=case_top);
echo(wall_t=wall_t, mount_reach=mount_reach, screw_cbore_h=screw_cbore_h);
echo(usb_face=usb_face, port_face=port_face);
echo(usb_slope_z=usb_slope_z, port_slope_z=port_slope_z);

// =====================================================================
// Helpers
// =====================================================================

module rounded_box(x, y, z, r) {
  hull()
    for (px = [r, x - r], py = [r, y - r])
      translate([px, py, 0])
        cylinder(h=z, r=r);
}

module placed_box(x0, y0, x, y, z, h, r) {
  translate([x0, y0, z])
    rounded_box(x, y, h, r);
}

// Corner holes of the camera board (the row 12 mm off the lens) face
// the microSD end, low x. The 21 mm pair runs across that end.
// Lens stays on the glass centre.
module camera_posts() {
  for (dx = [0, -camera_pitch_x])
    for (dy = [-camera_pitch_y / 2, camera_pitch_y / 2])
      translate([lens_x + dx, lens_y + dy, floor_t])
        cylinder(h=camera_post_h, d=camera_post_od);
}

module camera_pilots() {
  for (dx = [0, -camera_pitch_x])
    for (dy = [-camera_pitch_y / 2, camera_pitch_y / 2])
      translate([
        lens_x + dx,
        lens_y + dy,
        floor_t + camera_post_h - camera_post_pilot_h
      ])
        cylinder(h=camera_post_pilot_h + 0.02, d=camera_post_pilot);
}

module foot_bosses() {
  for (hx = [hole_inset, hole_inset + hole_pitch_x])
    for (hy = [hole_inset, hole_inset + hole_pitch_y])
      translate([pi_x0 + hx, pi_y0 + hy, floor_t])
        cylinder(h=mount_reach, d=mount_od);
}

module foot_bores() {
  for (hx = [hole_inset, hole_inset + hole_pitch_x])
    for (hy = [hole_inset, hole_inset + hole_pitch_y]) {
      translate([pi_x0 + hx, pi_y0 + hy, -0.1])
        cylinder(h=floor_t + mount_reach + 0.4, d=screw_bore);
      // Head recess with a flat ceiling for the flat underside of the pan
      // head. Any bridge skin over the pilot is pierced by the screw.
      translate([pi_x0 + hx, pi_y0 + hy, -0.1])
        cylinder(h=screw_cbore_h + 0.1, d=screw_cbore_d);
      // Open the first layer so it does not pinch shut and leave lint.
      translate([pi_x0 + hx, pi_y0 + hy, -0.01])
        cylinder(h=0.8, d1=screw_bore + 1.4, d2=screw_bore);
    }
}

// The Pi drawing is the component side. This stack is solder-side up,
// so a drawing y lands at (pi_y - y).
module port_windows() {
  // Power, HDMI, and audio. Openings match the shells, with jack_fit
  // all around. They stop short of the bosses.
  translate([
    pi_x0 + power_x - power_w / 2 - jack_fit,
    port_face - wall_t - 1,
    component_z - power_hole_z - power_drop
  ])
    cube([power_w + 2 * jack_fit, wall_t + 3, power_hole_z]);
  translate([
    pi_x0 + hdmi_x - hdmi_w / 2 - jack_fit,
    port_face - wall_t - 1,
    component_z - hdmi_z - jack_fit - hdmi_drop
  ])
    cube([hdmi_w + 2 * jack_fit, wall_t + 3, hdmi_z + 2 * jack_fit]);
  translate([
    pi_x0 + audio_x,
    port_face + 2,
    component_z - audio_z / 2 - audio_drop
  ])
    rotate([90, 0, 0])
      cylinder(h=wall_t + 3, d=audio_d + 2 * audio_fit);

  // USB end wall sits at the shell face. Cut through that wall.
  eth_case_y = pi_y - eth_y;
  translate([
    usb_face - wall_t - 1,
    pi_y0 + eth_case_y - 8,
    component_z - eth_z - jack_fit
  ])
    cube([wall_t + 3, 16, eth_z + 2 * jack_fit]);
  for (uy = usb_y)
    translate([
      usb_face - wall_t - 1,
      pi_y0 + (pi_y - uy) - 8,
      usb_bottom_z - jack_fit
    ])
      cube([wall_t + 3, 16, usb_z + 2 * jack_fit]);

  // PWR and ACT LEDs face the floor, so the holes sit just under the board.
  for (led_y = [pwr_led_y, pwr_led_y + led_pitch])
    translate([-1, pi_y0 + (pi_y - led_y), component_z - 0.8])
      rotate([0, 90, 0])
        cylinder(h=pocket_x0 + 2, d=pwr_led_hole_d);

  // Card shell is centered on the edge at y = 28. The opening is
  // wider than the shell so the card can be pinched out.
  translate([
    -2,
    pi_y0 + (sd_y0 + sd_y1) / 2 + sd_shift - sd_slot_w / 2,
    solder_z - 0.4 - sd_drop
  ])
    cube([
      pocket_x0 + 6,
      sd_slot_w,
      3.0
    ]);
}

// Outer profile of a beveled side, as (distance, z) pairs: the floor
// plate edge at full thickness, up the bottom slope to the wall face,
// up the wall, then out to the lip. The cut is everything outside it.
function bevel_cut_profile(edge, face, slope_z) = [
  [edge, -1],
  [edge, floor_t],
  [face, slope_z],
  [face, component_z],
  [edge, seat_z],
  [edge + 2, seat_z],
  [edge + 2, -1]
];

// Vertical wall at the USB shell face, with slopes out to the floor
// edge and to the lip. The upper slope thickens to the lip wall.
module usb_end_wall() {
  intersection() {
    union() {
      translate([usb_face - wall_t, 0, floor_t])
        cube([wall_t, case_y, component_z - floor_t]);
      hull() {
        translate([usb_face - wall_t, 0, component_z - 0.2])
          cube([wall_t, case_y, 0.2]);
        translate([case_x - lip_wall_t, 0, seat_z - 0.2])
          cube([lip_wall_t, case_y, 0.2]);
      }
      hull() {
        translate([usb_face - wall_t, 0, usb_slope_z - 0.2])
          cube([wall_t, case_y, 0.2]);
        translate([usb_face - wall_t, 0, floor_t - 0.2])
          cube([case_x - usb_face + wall_t, case_y, 0.2]);
      }
    }
    rounded_box(case_x, case_y, case_top, outer_r);
  }
}

// Plastic of the original outer wall that the bevels replace.
module usb_bevel_cut() {
  translate([0, case_y + 1, 0])
    rotate([90, 0, 0])
      linear_extrude(case_y + 2)
        polygon(bevel_cut_profile(case_x, usb_face, usb_slope_z));
}

// Power edge. The wall rests on the HDMI and power shell faces.
// The upper slope thickens to the lip wall.
module port_edge_wall() {
  intersection() {
    union() {
      translate([0, port_face - wall_t, floor_t])
        cube([case_x, wall_t, component_z - floor_t]);
      hull() {
        translate([0, port_face - wall_t, component_z - 0.2])
          cube([case_x, wall_t, 0.2]);
        translate([0, case_y - lip_wall_t, seat_z - 0.2])
          cube([case_x, lip_wall_t, 0.2]);
      }
      hull() {
        translate([0, port_face - wall_t, port_slope_z - 0.2])
          cube([case_x, wall_t, 0.2]);
        translate([0, port_face - wall_t, floor_t - 0.2])
          cube([case_x, case_y - port_face + wall_t, 0.2]);
      }
    }
    rounded_box(case_x, case_y, case_top, outer_r);
  }
}

module port_bevel_cut() {
  translate([-1, 0, 0])
    rotate([90, 0, 90])
      linear_extrude(case_x + 2)
        polygon(bevel_cut_profile(case_y, port_face, port_slope_z));
}

module tub() {
  difference() {
    union() {
      difference() {
        rounded_box(case_x, case_y, case_top, outer_r);

        // Main cavity, up to the underside of the lip.
        placed_box(pocket_x0, pocket_y0, pocket_x, pocket_y,
          floor_t, seat_z - lip_land - lip_chamfer - floor_t + 0.02, pocket_r);

        // 45° slope up to the lip shelf.
        hull() {
          placed_box(pocket_x0, pocket_y0, pocket_x, pocket_y,
            seat_z - lip_land - lip_chamfer, 0.02, pocket_r);
          placed_box(open_x0, open_y0, open_x, open_y,
            seat_z - lip_land, 0.02, open_r);
        }

        // Shelf opening. The glass perimeter sits on the ring around this.
        placed_box(open_x0, open_y0, open_x, open_y,
          seat_z - lip_land, lip_land + 0.02, open_r);

        // Well the screen drops into, plus the raised rim. Slightly
        // larger than the glass.
        placed_box(pocket_x0, pocket_y0, pocket_x, pocket_y,
          seat_z, screen_t + lip_rise + 0.1, pocket_r);

        translate([lens_x, lens_y + lens_hole_dy, -1])
          cylinder(h=floor_t + 2, d=lens_d);
        translate([lens_x, lens_y + lens_hole_dy, -0.01])
          cylinder(
            h=lens_cone_h,
            d1=lens_d + 2 * lens_cone_h * tan(lens_cone_ang / 2),
            d2=lens_d
          );
      }
      usb_end_wall();
      port_edge_wall();
      foot_bosses();
      camera_posts();
    }
    usb_bevel_cut();
    port_bevel_cut();
    port_windows();
    foot_bores();
    camera_pilots();
  }
}

// Ghost of the measured stack, for fit checks. Not included in an STL export.
module stack_ghost() {
  %translate([rim, rim, seat_z])
    cube([glass_x, glass_y, screen_t]);
  %translate([pi_x0, pi_y0, usb_bottom_z])
    cube([pi_x, pi_y, solder_z - usb_bottom_z]);
}

// =====================================================================
// Render
// =====================================================================

mode = "preview"; // "preview" | "case"

tub();
if (mode == "preview")
  stack_ghost();
