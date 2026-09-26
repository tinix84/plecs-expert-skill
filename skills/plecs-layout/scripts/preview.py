#!/usr/bin/env python3
"""Draw a .plecs schematic as SVG from the measured geometry, to check a layout without PLECS.

Usage:
    python preview.py MODEL.plecs [-o MODEL.svg] [--path /Subsystem]

Symbol boxes are grey, terminals are small circles with their numbers, wires are
black (electrical) or green (signal). A leg between a terminal and a Point that is
not horizontal or vertical is drawn dashed red: PLECS bends it on its own, so check
that corner in the GUI. Blocks without measured geometry are drawn as dashed boxes.
"""
from __future__ import annotations

import argparse
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lint_schematic as L  # noqa: E402
import plecs_file as pf  # noqa: E402

PAD = 40


def level(root, path):
    sch = pf.schematic(root)
    for part in [p for p in path.split("/") if p]:
        sch = next(c for c in sch.children_of("Component") if c.get("Name") == part).child("Schematic")
    return sch


def render(sch) -> str:
    comps = {c.get("Name"): c for c in sch.children_of("Component") if c.position}
    shapes = {n: L._shape(c) for n, c in comps.items()}
    items, xs, ys = [], [], []

    for n, c in comps.items():
        s = shapes[n]
        x0, y0, x1, y1 = s.box
        xs += [x0, x1]
        ys += [y0, y1]
        dash = "" if s.measured else ' stroke-dasharray="3,2"'
        items.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="#e8e8e8" stroke="#888"{dash}/>')
        items.append(f'<text x="{(x0 + x1) / 2}" y="{y0 - 3}" font-size="7" text-anchor="middle">{escape(n)}</text>')
        for t, (tx, ty) in s.terminals.items():
            items.append(f'<circle cx="{tx}" cy="{ty}" r="2" fill="white" stroke="#c00"/>')
            items.append(f'<text x="{tx + 3}" y="{ty - 3}" font-size="5" fill="#c00">{escape(t)}</text>')

    for conn in sch.children_of("Connection"):
        color = "#090" if conn.get("Type") == "Signal" else "#000"
        for (a, oa), (b, ob) in L._segments(conn, comps):
            xs += [a[0], b[0]]
            ys += [a[1], b[1]]
            if a[0] != b[0] and a[1] != b[1]:
                style = 'stroke="#d00" stroke-dasharray="4,2"'
            else:
                style = f'stroke="{color}"'
            items.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" {style} stroke-width="1"/>')

    if not xs:
        xs, ys = [0, 100], [0, 100]
    x0, y0, x1, y1 = min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {y0} {x1 - x0} {y1 - y0}" '
            f'width="{3 * (x1 - x0)}" height="{3 * (y1 - y0)}" font-family="sans-serif">'
            f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="white"/>'
            + "".join(items) + "</svg>\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Draw a .plecs schematic as SVG from the measured geometry.")
    ap.add_argument("model", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--path", default="/", help="schematic level, for example /Controller")
    args = ap.parse_args(argv)
    root = pf.parse(args.model.read_text(encoding="utf-8", errors="replace"))
    out = args.out or args.model.with_suffix(".svg")
    out.write_text(render(level(root, args.path)), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
