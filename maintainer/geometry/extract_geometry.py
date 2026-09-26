#!/usr/bin/env python3
"""Read symbol boxes and terminal positions from the printed calibration sheet.

    python extract_geometry.py build/calibration.pdf build/calibration_index.json \
        --out ../../skills/plecs-layout/scripts/geometry.json --plecs-version 4.9

Needs PyMuPDF (maintainer tool only; the skills themselves use the standard library).

Method:
  1. Map PDF points to schematic coordinates with the two fiducial wires.
  2. In each orientation cell (nothing connected), take the symbol box from all
     drawings, electrical terminals from the small circles PLECS draws on open
     terminals, and signal terminals from the outer end of the green port markers.
     Remove the constant print offset and snap to the 5 px grid.
  3. In each numbering cell (one terminal wired), the wire ends at that terminal;
     this names the terminals of the 'right / not flipped' orientation.
  4. For the other orientations, pick the rotation/flip mapping that best carries
     the named terminals onto the measured points, and name them through it.
"""
from __future__ import annotations

import argparse
import itertools
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import pymupdf

GRID = 5
WINDOW = (65, 75)          # half-size of a cell's window, schematic px
MARKER_MAX = 10            # terminal circles and port markers are smaller than this
GREEN = (0.0, 0.698, 0.0)  # PLECS signal port colour in print
# Blocks whose print cannot be read reliably; the tools fall back to the approximate model.
UNMEASURED = {
    "ThreePhaseMeter": "13 port markers for 9 terminals and auto-routed wires over its own ports",
    "ToFile": "input marker not found in print",
    "SignalSwitch": "green switch contacts touch the port arrows; 4 markers for 3 terminals",
}


def near(a, b, tol=0.02):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def find_fiducials(drawings, fids):
    """PDF positions of the fiducial corners: top-left and bottom-right U-shaped wires."""
    rects = [d["rect"] for d in drawings]
    tl = min(rects, key=lambda r: r.x0 + r.y0)
    br = max(rects, key=lambda r: r.x1 + r.y1)
    # the corner is the top-left of the U's top edge; for the bottom-right U it is the
    # left end of its top edge, which is the drawing just above-left of the extreme one
    top_edges = [r for r in rects if r.height < 0.2 and r.width > 3]
    tl_edge = min(top_edges, key=lambda r: abs(r.x0 - tl.x0) + abs(r.y0 - tl.y0))
    br_edge = min(top_edges, key=lambda r: abs(r.x1 - br.x1) + abs(r.y0 - (br.y1 - 5.6)))
    return (tl_edge.x0, tl_edge.y0), (br_edge.x0, br_edge.y0)


class Frame:
    def __init__(self, p0, p1, m0, m1):
        self.p0, self.m0 = p0, m0
        self.sx = (p1[0] - p0[0]) / (m1[0] - m0[0])
        self.sy = (p1[1] - p0[1]) / (m1[1] - m0[1])
        self.bias = (0.0, 0.0)

    def pt(self, x, y):
        return (self.m0[0] + (x - self.p0[0]) / self.sx - self.bias[0],
                self.m0[1] + (y - self.p0[1]) / self.sy - self.bias[1])

    def rect(self, r):
        (x0, y0), (x1, y1) = self.pt(r.x0, r.y0), self.pt(r.x1, r.y1)
        return (x0, y0, x1, y1)


def snap(v):
    return GRID * round(v / GRID)


def cell_items(drawings, frame, pos, exclude=()):
    out = []
    for d in drawings:
        x0, y0, x1, y1 = frame.rect(d["rect"])
        cx, cy = (x0 + x1) / 2 - pos[0], (y0 + y1) / 2 - pos[1]
        if abs(cx) > WINDOW[0] or abs(cy) > WINDOW[1]:
            continue
        if any(abs((x0 + x1) / 2 - e[0]) < 22 and abs((y0 + y1) / 2 - e[1]) < 22 for e in exclude):
            continue
        out.append((d, (x0 - pos[0], y0 - pos[1], x1 - pos[0], y1 - pos[1])))
    return out


def _merge(rects, gap=6):
    """Merge marker pieces printed as separate paths (for example the two halves of an arrow)."""
    out = []
    for r in rects:
        for i, m in enumerate(out):
            if r[0] - gap < m[2] and m[0] - gap < r[2] and r[1] - gap < m[3] and m[1] - gap < r[3]:
                out[i] = (min(r[0], m[0]), min(r[1], m[1]), max(r[2], m[2]), max(r[3], m[3]))
                break
        else:
            out.append(r)
    return out


def classify(items, symbol_box=None):
    """Split a cell's drawings into symbol parts, terminal circles, and signal port markers.

    symbol_box: outline to test port markers against; pass the unconnected cell's box for a
    numbering cell, whose wire would otherwise enlarge the outline."""
    body, circles, ports = [], [], []
    for d, r in items:
        w, h = r[2] - r[0], r[3] - r[1]
        kinds = {i[0] for i in d["items"]}
        fill = d.get("fill")
        if fill and near(fill, GREEN) and max(w, h) < MARKER_MAX:
            ports.append(r)
        elif "c" in kinds and max(w, h) < MARKER_MAX and fill and near(fill, (1, 1, 1)):
            circles.append(r)   # open electrical terminal: PLECS prints a small white disc
        elif "c" in kinds and max(w, h) < MARKER_MAX:
            continue            # the disc's black outline, sometimes fused with the lead line
        else:
            body.append(r)
    # A port marker sticks out past the symbol outline; green strokes inside it are symbol
    # graphics (for example the contacts of a Signal Switch).
    if symbol_box is None and body:
        symbol_box = (min(r[0] for r in body), min(r[1] for r in body),
                      max(r[2] for r in body), max(r[3] for r in body))
    if symbol_box:
        x0, y0, x1, y1 = symbol_box
        outside = [r for r in ports if r[0] < x0 - 0.5 or r[2] > x1 + 0.5 or r[1] < y0 - 0.5 or r[3] > y1 + 0.5]
        body += [r for r in ports if r not in outside]
        ports = outside
    # port arrows of neighbouring terminals sit 10 px apart; the two halves of one arrow touch
    return body, _merge(circles, gap=1), _merge(ports, gap=0.5)


def marker_keys(circles, ports):
    """Comparable marker positions, used to see which terminal lost its open-terminal marker."""
    return ([("c", (r[0] + r[2]) / 2, (r[1] + r[3]) / 2, r[2] - r[0], r[3] - r[1]) for r in circles]
            + [("p", (r[0] + r[2]) / 2, (r[1] + r[3]) / 2, r[2] - r[0], r[3] - r[1]) for r in ports])


def terminal_points(circles, ports, body=()):
    pts = [((r[0] + r[2]) / 2, (r[1] + r[3]) / 2, "elec") for r in circles]
    if body:
        bx, by = (min(r[0] for r in body) + max(r[2] for r in body)) / 2, (min(r[1] for r in body) + max(r[3] for r in body)) / 2
    else:
        bx = by = 0.0
    for r in ports:
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        # An arrow marker is short along the direction it points and long across it. Wires
        # attach at its outer end: the end of the short axis away from the symbol body.
        if (r[2] - r[0]) <= (r[3] - r[1]):
            pts.append((r[2] if cx > bx else r[0], cy, "sig"))
        else:
            pts.append((cx, r[3] if cy > by else r[1], "sig"))
    return pts  # same order as marker_keys(): circles, then ports


def wire_ends(items):
    """Endpoints of thin, long drawings (wire segments) in a numbering cell."""
    ends = []
    for d, r in items:
        w, h = r[2] - r[0], r[3] - r[1]
        if min(w, h) < 2.5 and max(w, h) > 6:
            if w >= h:
                ends += [(r[0], (r[1] + r[3]) / 2), (r[2], (r[1] + r[3]) / 2)]
            else:
                ends += [((r[0] + r[2]) / 2, r[1]), ((r[0] + r[2]) / 2, r[3])]
    return ends


TRANSFORMS = {}
for rot in range(4):
    for flip in (False, True):
        def t(p, rot=rot, flip=flip):
            x, y = p
            if flip:
                y = -y
            for _ in range(rot):
                x, y = -y, x
            return (x, y)
        TRANSFORMS[(rot, flip)] = t


ROTATION = {"right": 0, "down": 1, "left": 2, "up": 3}


def convention(orientation):
    """PLECS orientation as a TRANSFORMS key: Flipped mirrors the symbol along its own axis,
    then Direction rotates it clockwise in 90 degree steps. Learned from the asymmetric blocks
    of the calibration sheet (Ammeter, Voltmeter, MOSFET, ...), where only this mapping fits."""
    direction, flip = orientation.split("/")
    flipped = flip == "on"
    return ((ROTATION[direction] + (2 if flipped else 0)) % 4, flipped)


def map_terminals(named, measured, orientation):
    """Carry the named base terminals into an orientation and match them to measured points."""
    key = convention(orientation)
    t = TRANSFORMS[key]
    assign, worst = {}, 0.0
    for num, p in named.items():
        q = t(p)
        m = min(measured, key=lambda m: (m[0] - q[0]) ** 2 + (m[1] - q[1]) ** 2)
        worst = max(worst, ((m[0] - q[0]) ** 2 + (m[1] - q[1]) ** 2) ** 0.5)
        assign[num] = m
    return key, assign, worst


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf", type=Path)
    ap.add_argument("index", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--plecs-version", required=True)
    args = ap.parse_args(argv)

    page = pymupdf.open(args.pdf)[0]
    drawings = page.get_drawings()
    idx = json.loads(args.index.read_text(encoding="utf-8"))
    f0, f1 = idx["fiducials"]
    p0, p1 = find_fiducials(drawings, idx["fiducials"])
    frame = Frame(p0, p1, f0["corner"], f1["corner"])

    groups = defaultdict(lambda: {"orient": {}, "numbered": {}})
    for c in idx["cells"]:
        key = (c["type"], c["variant"])
        if c["numbered"]:
            groups[key]["numbered"][c["numbered"]["terminal"]] = c
        else:
            groups[key]["orient"][f"{c['direction']}/{'on' if c['flipped'] else 'off'}"] = c

    # print offset: median distance of terminal circles from the grid
    res_x, res_y = [], []
    for g in groups.values():
        for c in g["orient"].values():
            _, circles, _ = classify(cell_items(drawings, frame, c["position"]))
            for r in circles:
                cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
                res_x.append(cx - snap(cx))
                res_y.append(cy - snap(cy))
    frame.bias = (statistics.median(res_x), statistics.median(res_y)) if res_x else (0.0, 0.0)
    print(f"scale {frame.sx:.5f} x {frame.sy:.5f} pt/px, print offset {frame.bias[0]:+.2f}, {frame.bias[1]:+.2f} px")

    table, problems, notes = {}, [], []
    for (kind, variant), g in sorted(groups.items()):
        if kind in UNMEASURED:
            notes.append(f"{kind}: left unmeasured ({UNMEASURED[kind]})")
            continue
        measured = {}
        for o, c in g["orient"].items():
            body, circles, ports = classify(cell_items(drawings, frame, c["position"]))
            allr = body + circles + ports
            if not allr:
                problems.append(f"{kind}/{variant} {o}: nothing drawn")
                continue
            box = [snap(min(r[0] for r in allr)), snap(min(r[1] for r in allr)),
                   snap(max(r[2] for r in allr)), snap(max(r[3] for r in allr))]
            pts = [(snap(x), snap(y), k) for x, y, k in terminal_points(circles, ports, body)]
            measured[o] = (box, pts)
        base = measured.get("right/off")
        if not base:
            problems.append(f"{kind}/{variant}: no right/off cell")
            continue
        named = {}
        bc = g["orient"]["right/off"]
        bbody, bcirc, bport = classify(cell_items(drawings, frame, bc["position"]))
        bbox = (min(r[0] for r in bbody), min(r[1] for r in bbody),
                max(r[2] for r in bbody), max(r[3] for r in bbody)) if bbody else None
        base_markers = marker_keys(bcirc, bport)
        base_pts = terminal_points(bcirc, bport, bbody)
        for num, c in sorted(g["numbered"].items()):
            items = cell_items(drawings, frame, c["position"],
                               exclude=[tuple(c["numbered"]["partner_position"])])
            _, ncirc, nport = classify(items, bbox)
            now = marker_keys(ncirc, nport)
            # a connected terminal loses its open-terminal disc, or (signal ports) its arrow changes
            # shape; disc sizes vary with print quantisation, so only port sizes are compared
            missing = [i for i, (k, x, y, w, h) in enumerate(base_markers)
                       if not any(k == k2 and abs(x - x2) < 2.5 and abs(y - y2) < 2.5
                                  and (k == "c" or (abs(w - w2) < 3 and abs(h - h2) < 3))
                                  for k2, x2, y2, w2, h2 in now)]
            if not missing:
                notes.append(f"{kind}/{variant}: terminal {num} absent in this configuration, dropped")
                continue
            if len(missing) == 1:
                x, y, _ = base_pts[missing[0]] if missing[0] < len(base_pts) else (None, None, None)
                p = (snap(x), snap(y)) if x is not None else None
            else:
                # fall back to the wire end closest to a drawn terminal
                ends = [(snap(x), snap(y)) for x, y in wire_ends(items)]
                cands = [(x, y) for x, y, _ in base[1]]
                p = (min(cands, key=lambda q: min((q[0] - e[0]) ** 2 + (q[1] - e[1]) ** 2 for e in ends))
                     if ends and cands else None)
                problems.append(f"{kind}/{variant}: terminal {num} by wire end ({len(missing)} markers changed)")
            if p is None:
                problems.append(f"{kind}/{variant}: terminal {num} not found")
                continue
            if p in named.values():
                problems.append(f"{kind}/{variant}: terminals share point {p}")
                continue
            named[num] = p
        if len(named) != len(base[1]):
            problems.append(f"{kind}/{variant}: {len(named)} named terminals, {len(base[1])} drawn")
        entry = {}
        for o, (box, pts) in measured.items():
            if not named or not pts:
                if named:
                    notes.append(f"{kind}/{variant} {o}: no terminal markers found; orientation left out")
                else:
                    entry[o] = {"box": box, "terminals": {}}
                continue
            mapping, assign, worst = map_terminals(named, [(x, y) for x, y, _ in pts], o)
            if len(set(assign.values())) != len(assign):
                # overlapping port markers (tiny blocks); leave the orientation out rather than guess
                notes.append(f"{kind}/{variant} {o}: two terminals map to one point; orientation left out")
                continue
            elif worst > 10:
                notes.append(f"{kind}/{variant} {o}: symbol does not rotate rigidly (off by {worst:.0f} px); measured points used")
            entry[o] = {"box": box, "terminals": {str(n): list(p) for n, p in sorted(assign.items())},
                        "mapping": list(mapping)}
        table.setdefault(kind, {})[variant] = entry

    args.out.write_text(json.dumps({"plecs_version": args.plecs_version,
                                    "source": "maintainer/geometry calibration sheet",
                                    "blocks": table}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{sum(len(v) for v in table.values())} block variants written to {args.out}")
    for n in notes:
        print("note:", n)
    for p in problems:
        print("problem:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
