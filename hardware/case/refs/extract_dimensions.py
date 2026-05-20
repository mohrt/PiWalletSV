#!/usr/bin/env python3
"""Extract component centres from Adafruit's official 4506 bonnet STEP file.

Output is bonnet-frame (x, y, z) in millimetres, suitable for direct
substitution into the variables at the top of `case.scad`.

Run:  python3 extract_dimensions.py 4506-bonnet.step

The script is deliberately ad-hoc — STEP is verbose and our needs are
narrow. We parse just enough to chase NEXT_ASSEMBLY_USAGE_OCCURRENCE
entries through their CONTEXT_DEPENDENT_SHAPE_REPRESENTATION /
ITEM_DEFINED_TRANSFORMATION / AXIS2_PLACEMENT_3D / CARTESIAN_POINT
chain and read the component placement.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Components we care about. Maps STEP component name (substring match
# on NEXT_ASSEMBLY_USAGE_OCCURRENCE name) to a friendly label.
TARGETS = {
    "RPI1":         "GPIO header (Pi-side)",
    "FPC-connector-24pin": "Bonnet 2x20 socket (Pi-mating)",
    "DISPLAY1":     "LCD module",
    "SW3":          "Joystick (5-way SKQUBAE010)",
    "SW1":          "Tactile switch SW1",
    "SW2":          "Tactile switch SW2",
    "CONN1":        "STEMMA QT (JST-SH 4-pin)",
}


def parse_step(path: Path) -> dict[int, list[tuple[str, str]]]:
    """Return {entity_id: [(entity_type, raw_args_string), ...]}.

    STEP supports two entity declaration forms:

      simple:   #N = TYPE(args);
      complex:  #N = ( TYPE1(args1) TYPE2(args2) ... );

    Both are mapped to a list of (type, args) tuples — simple entities
    have a single-element list. The args strings are kept as raw text
    because chasing comma-separated args inside nested parens is
    fiddly and we'd rather use targeted regex per type.
    """
    text = path.read_text()
    body = text.split("DATA;", 1)[1].split("ENDSEC", 1)[0]
    body = body.replace("\n", " ")

    out: dict[int, list[tuple[str, str]]] = {}

    simple_pat = re.compile(
        r"#(\d+)\s*=\s*([A-Z_0-9]+)\s*\((.*?)\)\s*;", re.DOTALL
    )
    complex_pat = re.compile(r"#(\d+)\s*=\s*\(\s*(.*?)\s*\)\s*;", re.DOTALL)
    inner_pat = re.compile(r"([A-Z_0-9]+)\s*\(([^()]*?)\)", re.DOTALL)

    # First pass: complex entities (which start with `=(`).
    for m in complex_pat.finditer(body):
        eid = int(m.group(1))
        inner = m.group(2)
        # Skip if this is actually a simple entity that happens to
        # have leading parens in args (unlikely but cheap to check).
        if not re.match(r"^[A-Z_]", inner):
            continue
        types_args: list[tuple[str, str]] = []
        for im in inner_pat.finditer(inner):
            types_args.append((im.group(1), im.group(2)))
        if types_args:
            out[eid] = types_args

    # Second pass: simple entities (skipping ones already captured).
    for m in simple_pat.finditer(body):
        eid = int(m.group(1))
        if eid in out:
            continue
        out[eid] = [(m.group(2), m.group(3))]

    return out


def find_naoo(entities, needle: str) -> list[int]:
    """Find NEXT_ASSEMBLY_USAGE_OCCURRENCE ids whose first arg matches needle."""
    hits = []
    for eid, types_args in entities.items():
        for etype, args in types_args:
            if etype != "NEXT_ASSEMBLY_USAGE_OCCURRENCE":
                continue
            m = re.match(r"\s*'([^']+)'", args)
            if not m:
                continue
            if needle in m.group(1):
                hits.append((eid, m.group(1)))
    return hits


def find_referrers(entities, target: int, etype: str) -> list[int]:
    """Find entities that have a sub-type of `etype` and reference #target."""
    out = []
    for eid, types_args in entities.items():
        for et, args in types_args:
            if et != etype:
                continue
            if re.search(rf"#{target}\b", args):
                out.append(eid)
                break
    return out


def entity_args(entities, eid: int, etype: str) -> str | None:
    """Return the args string for a specific sub-type within an entity."""
    for et, args in entities.get(eid, []):
        if et == etype:
            return args
    return None


def extract_refs(args: str) -> list[int]:
    """All #N references inside an args string, in order."""
    return [int(m) for m in re.findall(r"#(\d+)", args)]


def find_transform_for_naoo(entities, naoo_id: int) -> int | None:
    """Walk from a NEXT_ASSEMBLY_USAGE_OCCURRENCE to the
    ITEM_DEFINED_TRANSFORMATION that places it.

    Path: NAOO --(referenced by)--> PRODUCT_DEFINITION_SHAPE
                                         (referenced by)
                            CONTEXT_DEPENDENT_SHAPE_REPRESENTATION
                                         (which references a)
              REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION
                                         (whose transformation is an)
                            ITEM_DEFINED_TRANSFORMATION
    """
    pds = find_referrers(entities, naoo_id, "PRODUCT_DEFINITION_SHAPE")
    if not pds:
        return None
    cdsr = []
    for p in pds:
        cdsr += find_referrers(
            entities, p, "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION"
        )
    if not cdsr:
        return None
    for c in cdsr:
        cdsr_args = entity_args(entities, c, "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION")
        if not cdsr_args:
            continue
        for r in extract_refs(cdsr_args):
            if r not in entities:
                continue
            rwt_args = entity_args(
                entities, r, "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION"
            )
            if rwt_args is None:
                continue
            for q in extract_refs(rwt_args):
                if any(
                    et == "ITEM_DEFINED_TRANSFORMATION"
                    for et, _ in entities.get(q, [])
                ):
                    return q
    return None


def axis_placement_origin(entities, ap_id: int) -> tuple[float, float, float] | None:
    """Read the CARTESIAN_POINT origin out of an AXIS2_PLACEMENT_3D."""
    args = entity_args(entities, ap_id, "AXIS2_PLACEMENT_3D")
    if args is None:
        return None
    refs = extract_refs(args)
    if not refs:
        return None
    cp_args = entity_args(entities, refs[0], "CARTESIAN_POINT")
    if cp_args is None:
        return None
    m = re.search(
        r"\(\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\)", cp_args
    )
    if not m:
        return None
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)))


def main(path: str) -> None:
    p = Path(path)
    entities = parse_step(p)
    print(f"# Parsed {len(entities):,} entities from {p.name}")
    print()

    # Find the PCB placement so we can rebase everything to PCB-frame
    # (i.e. measure from the Board's origin, not the assembly origin).
    pcb_naoo = find_naoo(entities, "PCB Component")
    pcb_origin = (0.0, 0.0, 0.0)
    if pcb_naoo:
        idt = find_transform_for_naoo(entities, pcb_naoo[0][0])
        if idt:
            idt_args = entity_args(entities, idt, "ITEM_DEFINED_TRANSFORMATION")
            ap_refs = extract_refs(idt_args) if idt_args else []
            # ITEM_DEFINED_TRANSFORMATION carries (parent_axis, child_axis).
            # The "child" axis is where the PCB sits in assembly space.
            for ap in ap_refs:
                origin = axis_placement_origin(entities, ap)
                if origin is not None:
                    pcb_origin = origin
                    break

    print(f"# PCB origin in assembly-frame: {pcb_origin}")
    print()

    rows = []
    for needle, label in TARGETS.items():
        hits = find_naoo(entities, needle)
        if not hits:
            rows.append((needle, label, None, "no NAOO match"))
            continue
        for naoo_id, full_name in hits:
            idt = find_transform_for_naoo(entities, naoo_id)
            if not idt:
                rows.append((full_name, label, None, "no transform"))
                continue
            idt_args = entity_args(entities, idt, "ITEM_DEFINED_TRANSFORMATION")
            ap_refs = extract_refs(idt_args) if idt_args else []
            origin = None
            # Prefer the "child" placement (last ref) — that's the
            # transformation FROM parent (PCB) TO child (component).
            for ap in reversed(ap_refs):
                o = axis_placement_origin(entities, ap)
                if o is not None:
                    origin = o
                    break
            rows.append((full_name, label, origin, ""))

    print(f"{'Component':<48} {'Friendly':<35} {'x (mm)':>10} {'y (mm)':>10} {'z (mm)':>10}")
    print("-" * 115)
    for full_name, label, origin, note in rows:
        if origin is None:
            print(f"{full_name:<48} {label:<35} {note}")
            continue
        x, y, z = origin
        # Rebase: subtract PCB origin to get values in PCB-frame
        xr = x - pcb_origin[0]
        yr = y - pcb_origin[1]
        zr = z - pcb_origin[2]
        print(f"{full_name:<48} {label:<35} {xr:>10.3f} {yr:>10.3f} {zr:>10.3f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "4506-bonnet.step")
