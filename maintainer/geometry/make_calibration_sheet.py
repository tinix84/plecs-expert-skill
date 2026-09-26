#!/usr/bin/env python3
"""Generate a PLECS model that shows every calibrated block in every orientation.

Print the model once to a vector PDF from PLECS; `extract_geometry.py` then reads
symbol boxes and terminal points from the PDF into `geometry.json`.

Each block type gets one row:
  - 8 orientation cells: Direction right/down/left/up x Flipped off/on, nothing connected.
  - one numbering cell per terminal (Direction right, not flipped) where only that
    terminal is wired to a small partner block, so the wire identifies the terminal.

Block templates (parameter sets) are copied from the Plexim demos of the local PLECS
install, so no Plexim content is stored in this repository.

Usage:
    python make_calibration_sheet.py --plecs-dir "C:/.../PLECS 4.9 (64 bit)" --out build/
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "skills/plecs-layout/scripts"))
import plecs_file as pf  # noqa: E402

DIRECTIONS = ("right", "down", "left", "up")
PITCH_X = 140  # cell spacing; larger than any calibrated symbol
PITCH_Y = 160
PARTNER_OFFSET = 70  # partner block sits this far from the calibrated block
FIDUCIAL = 60        # length of the fiducial top edge

# Types to calibrate, with parameter variants for blocks whose size depends on them.
# (type, variant label, {parameter: value}); a key starting with "@" is a top-level field.
TYPES = [
    ("Resistor", "", {}), ("Inductor", "", {}), ("Capacitor", "", {}), ("Diode", "", {}),
    ("Switch", "", {}), ("Switch2", "", {}), ("ManualSwitch", "", {}),
    ("Igbt", "", {}), ("IgbtWithDiode", "", {}), ("Mosfet", "", {}), ("MosfetWithDiode", "", {}),
    ("VoltageSource", "", {}), ("CurrentSource", "", {}), ("DCVoltageSource", "", {}),
    ("ACVoltageSource", "", {}), ("Ammeter", "", {}), ("Voltmeter", "", {}), ("Ground", "", {}),
    ("ThreePhaseMeter", "", {}), ("Label", "", {}), ("Port", "", {}),
    ("Goto", "", {}), ("From", "", {}), ("Input", "", {}), ("Output", "", {}), ("PlecsProbe", "", {}),
    ("Constant", "", {}), ("Step", "", {}), ("SineGenerator", "", {}), ("PulseGenerator", "", {}),
    ("TriangleGenerator", "", {}), ("Gain", "", {}), ("Offset", "", {}), ("Saturation", "", {}),
    ("Abs", "", {}), ("Integrator", "", {}), ("TransferFunction", "", {}), ("ZeroOrderHold", "", {}),
    ("Delay", "", {}), ("PeriodicAverage", "", {}), ("Function", "", {}), ("ToFile", "", {}),
    ("RelationalOperator", "", {}), ("ConstantRelationalOperator", "", {}), ("LogicalOperator", "", {}),
    ("SignalSwitch", "", {}), ("MinMax", "", {}), ("Relay", "", {}), ("Display", "", {}),
    ("Sum", "2in", {"Inputs": "|+-"}), ("Sum", "3in", {"Inputs": "|++-"}), ("Sum", "4in", {"Inputs": "|+++-"}),
    ("Product", "2in", {"Inputs": "2"}), ("Product", "3in", {"Inputs": "3"}),
    ("SignalMux", "w2", {"Width": "2"}), ("SignalMux", "w3", {"Width": "3"}), ("SignalMux", "w4", {"Width": "4"}),
    ("SignalDemux", "w2", {"Width": "2"}), ("SignalDemux", "w3", {"Width": "3"}), ("SignalDemux", "w4", {"Width": "4"}),
    ("Scope", "1in", {"@Axes": "1"}), ("Scope", "2in", {"@Axes": "2"}),
    ("Scope", "3in", {"@Axes": "3"}), ("Scope", "4in", {"@Axes": "4"}),
    ("CScript", "1in1out", {"NumInputs": "1", "NumOutputs": "1"}),
    ("CScript", "2in2out", {"NumInputs": "[1 1]", "NumOutputs": "[1 1]"}),
    ("CScript", "4in2out", {"NumInputs": "[1 1 1 1]", "NumOutputs": "[1 1]"}),
]


def walk(sch, path=""):
    for c in sch.children_of("Component"):
        yield c, sch
        sub = c.child("Schematic")
        if sub is not None:
            yield from walk(sub)


def harvest(model_files):
    """First instance of every type, plus terminal kinds seen in connections."""
    templates = {}
    kinds = collections.defaultdict(collections.Counter)  # (type, terminal) -> {"in","out","elec"}
    for f in model_files:
        sch = pf.schematic(pf.parse(f.read_text(encoding="utf-8", errors="replace")))
        if sch is None:
            continue
        levels = [sch] + [c.child("Schematic") for c, _ in walk(sch) if c.child("Schematic") is not None]
        for level in levels:
            comps = {c.get("Name"): c for c in level.children_of("Component")}
            for c in comps.values():
                templates.setdefault(c.get("Type"), c)

            def note(conn, is_root, wire):
                # A Branch does not repeat its parent's Type, so the type is passed down.
                src, dst = conn.get("SrcComponent"), conn.get("DstComponent")
                if is_root and src in comps:
                    kinds[(comps[src].get("Type"), conn.get("SrcTerminal"))]["elec" if wire else "out"] += 1
                if dst in comps:
                    kinds[(comps[dst].get("Type"), conn.get("DstTerminal"))]["elec" if wire else "in"] += 1
                for br in conn.children_of("Branch"):
                    note(br, False, wire)

            for conn in level.children_of("Connection"):
                note(conn, True, conn.get("Type") in ("Wire", "WireMux", "WireSelector"))
    return templates, kinds


def set_param(comp, var, value):
    for p in comp.children_of("Parameter"):
        if p.get("Variable") == var:
            p.items = [(("Value", json.dumps(value)) if isinstance(i, tuple) and i[0] == "Value" else i) for i in p.items]
            return True
    comp.items.append(pf.Block("Parameter", [("Variable", json.dumps(var)), ("Value", json.dumps(value)), ("Show", "off")]))
    return False


def instance(template, name, pos, direction, flipped, params):
    """Copy a template component with a new name, position and orientation."""
    blk = pf.parse(pf.dump(template)).children[0]
    replace = {"Name": json.dumps(name), "Show": "off", "Position": f"[{pos[0]}, {pos[1]}]",
               "Direction": direction, "Flipped": "on" if flipped else "off", "Open": '"0"'}
    replace.update({k[1:]: json.dumps(v) for k, v in params.items() if k.startswith("@")})
    blk.items = [((i[0], replace[i[0]]) if isinstance(i, tuple) and i[0] in replace else i) for i in blk.items]
    if blk.get("Type") in ("Goto", "From", "Label"):
        set_param(blk, "Tag", name)  # unique tags: no duplicate-Goto errors on the sheet
    for var, value in params.items():
        if not var.startswith("@") and not set_param(blk, var, value):
            print(f"warning: {template.get('Type')} has no parameter {var!r}; appended", file=sys.stderr)
    return blk


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plecs-dir", required=True, type=Path, help="PLECS install folder (contains demos/)")
    ap.add_argument("--extra-models", type=Path, action="append", default=[],
                    help="more folders of .plecs files to take templates from")
    ap.add_argument("--out", type=Path, default=HERE / "build")
    args = ap.parse_args(argv)

    files = sorted((args.plecs_dir / "demos").glob("*/*.plecs"))
    for extra in args.extra_models:
        files += sorted(extra.rglob("*.plecs"))
    templates, kinds = harvest(files)

    partner_for = {"elec": "Ground", "in": "Constant", "out": "Gain"}
    missing = [t for t in {"Ground", "Constant", "Gain"} if t not in templates]
    if missing:
        sys.exit(f"partner templates not found: {missing}")

    sch = pf.Block("Schematic", [("Location", "[0, 26; 1600, 1000]"), ("ZoomFactor", "1")])
    index, skipped, n = [], [], 0
    connections = []  # written after all components; PLECS rejects a Component after a Connection
    for row, (kind, variant, params) in enumerate(TYPES):
        if kind not in templates:
            skipped.append(kind)
            continue
        y = 100 + row * PITCH_Y
        col = 0
        for direction in DIRECTIONS:
            for flipped in (False, True):
                name = f"k{n:04d}"
                n += 1
                pos = (100 + col * PITCH_X, y)
                sch.items.append(instance(templates[kind], name, pos, direction, flipped, params))
                index.append({"name": name, "type": kind, "variant": variant, "params": params,
                              "direction": direction, "flipped": flipped, "position": pos, "numbered": None})
                col += 1
        terms = sorted({int(t) for (tk, t) in kinds if tk == kind and t and t.isdigit()})
        for term in terms:
            seen = kinds[(kind, str(term))]
            role = "elec" if seen["elec"] else seen.most_common(1)[0][0]
            name = f"k{n:04d}"
            n += 1
            pos = (100 + col * PITCH_X, y)
            sch.items.append(instance(templates[kind], name, pos, "right", False, params))
            partner = f"p{n:04d}"
            ppos = (pos[0] + PARTNER_OFFSET, pos[1] + PARTNER_OFFSET)
            sch.items.append(instance(templates[partner_for[role]], partner, ppos, "right", False, {}))
            wire = "Wire" if role == "elec" else "Signal"
            src, st, dst, dt = (partner, 1, name, term) if role == "in" else (name, term, partner, 1)
            connections.append(pf.Block("Connection", [
                ("Type", wire), ("SrcComponent", json.dumps(src)), ("SrcTerminal", str(st)),
                ("DstComponent", json.dumps(dst)), ("DstTerminal", str(dt))]))
            index.append({"name": name, "type": kind, "variant": variant, "params": params,
                          "direction": "right", "flipped": False, "position": pos,
                          "numbered": {"terminal": term, "role": role, "partner": partner, "partner_position": ppos}})
            col += 1

    # Fiducials: a wire with explicit Points is drawn exactly at those coordinates, so two
    # U-shaped wires at opposite corners give the PDF-to-schematic scale and offset.
    max_x = max(c["position"][0] for c in index) + PITCH_X
    max_y = max(c["position"][1] for c in index) + PITCH_Y
    fiducials = []
    for i, (fx, fy) in enumerate(((-200, -200), (max_x, max_y))):  # both clear of the cell grid
        a, b = f"fidA{i}", f"fidB{i}"
        sch.items.append(instance(templates["Ground"], a, (fx - 40, fy + 80), "right", False, {}))
        sch.items.append(instance(templates["Ground"], b, (fx + 80, fy + 80), "right", False, {}))
        pts = [(fx, fy + 40), (fx, fy), (fx + FIDUCIAL, fy), (fx + FIDUCIAL, fy + 40)]
        connections.append(pf.Block("Connection", [
            ("Type", "Wire"), ("SrcComponent", json.dumps(a)), ("SrcTerminal", "1"),
            ("Points", "[" + "; ".join(f"{x}, {y}" for x, y in pts) + "]"),
            ("DstComponent", json.dumps(b)), ("DstTerminal", "1")]))
        fiducials.append({"corner": [fx, fy], "points": pts})

    sch.items.extend(connections)
    model = pf.Block("Plecs", [("Name", '"plecs_geometry_calibration"'), ("Version", '"4.7"'),
                               ("CircuitModel", '"ContStateSpace"'), ("StartTime", '"0.0"'),
                               ("TimeSpan", '"1e-3"'), ("Solver", '"auto"')])
    model.items.append(sch)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "plecs_geometry_calibration.plecs").write_text(pf.dump(model), encoding="utf-8")
    (args.out / "calibration_index.json").write_text(json.dumps({
        "pitch": [PITCH_X, PITCH_Y], "fiducials": fiducials, "cells": index, "skipped_types": skipped}, indent=1), encoding="utf-8")
    print(f"{len(index)} cells, {len(TYPES) - len(skipped)} block variants; skipped (no template): {skipped}")
    print(args.out / "plecs_geometry_calibration.plecs")


if __name__ == "__main__":
    main()
