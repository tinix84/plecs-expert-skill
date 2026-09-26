#!/usr/bin/env python3
"""Lint a PLECS .plecs schematic for layout problems (standard library only).

Usage:
    python lint_schematic.py MODEL.plecs [MODEL2.plecs ...] [--grid 5] [--json]

Exit code 1 if any error-level finding is reported.

PLECS does not store terminal offsets in the file, so terminals are
approximated by the component centre. PLECS draws the corner itself on the
leg between a terminal and the nearest Point, so only Point-to-Point segments
are checked for diagonals. Checks near terminals are conservative.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plecs_file as pf  # noqa: E402

TAG_BLOCKS = {"Goto", "From", "Label"}
# Visibility parameter value that means "this schematic only"; other values search wider.
LOCAL_VISIBILITY = "2"
OVERLAP_PX = 15        # centres closer than this on both axes overlap (parts stack at 20 px in the demos)
SMALL_OVERLAP_PX = 10  # tag, constant and probe blocks stack at 15 px
SMALL = {"Goto", "From", "Label", "Constant", "Input", "Output", "PlecsProbe", "Ground"}
# Blocks drawn around other blocks on purpose.
CONTAINERS = {"HeatSink", "Annotation"}
BODY_HALF = 15   # half-size of the keep-out box a foreign wire must not enter
SMALL_BODY_HALF = 8
UNROUTED_PX = 40  # a Points-free connection spanning more than this on both axes is left to PLECS routing


@dataclass
class Finding:
    code: str
    severity: str  # "error" | "warn"
    path: str      # schematic path, "/" or "/Subsystem"
    where: str     # component or connection
    message: str


def _segments(conn, comps, start=None):
    """Yield ((a, a_owner), (b, b_owner)) segments of a connection tree.

    An owner is the component whose terminal the end approximates (its centre),
    or None for an explicit Point. A branch starts where its parent's Points end,
    or at the parent's source terminal when the parent has no Points.
    """
    src = conn.get("SrcComponent")
    pts = pf.points(conn)
    chain = []
    if start is not None:
        chain.append(start)
    elif src in comps and comps[src].position:
        chain.append((comps[src].position, src))
    chain += [(p, None) for p in pts]
    dst = conn.get("DstComponent")
    if dst in comps and comps[dst].position:
        chain.append((comps[dst].position, dst))
    yield from zip(chain, chain[1:])
    tail = (pts[-1], None) if pts else (chain[0] if chain else None)
    for br in conn.children_of("Branch"):
        yield from _segments(br, comps, start=tail)


def _endpoints(conn) -> set:
    names = {conn.get("SrcComponent"), conn.get("DstComponent")}
    for br in conn.children_of("Branch"):
        names |= _endpoints(br)
    return {n for n in names if n}


def _all_points(conn):
    yield from pf.points(conn)
    for br in conn.children_of("Branch"):
        yield from _all_points(br)


def _seg_hits_box(a, b, c, half) -> bool:
    """Axis-aligned segment a-b passes through the square of half-size `half` around c."""
    (x1, y1), (x2, y2) = a, b
    if y1 == y2:
        return abs(y1 - c[1]) < half and min(x1, x2) < c[0] < max(x1, x2)
    if x1 == x2:
        return abs(x1 - c[0]) < half and min(y1, y2) < c[1] < max(y1, y2)
    return False


def _cross(s, t) -> bool:
    """Proper crossing of a horizontal and a vertical segment; touching endpoints do not count."""
    if s[0][1] == s[1][1] and t[0][0] == t[1][0]:
        h, v = s, t
    elif t[0][1] == t[1][1] and s[0][0] == s[1][0]:
        h, v = t, s
    else:
        return False
    x, y = v[0][0], h[0][1]
    return (min(h[0][0], h[1][0]) < x < max(h[0][0], h[1][0])
            and min(v[0][1], v[1][1]) < y < max(v[0][1], v[1][1]))


def _lint_level(sch, path, grid, tags) -> list:
    out = []
    comps = {c.get("Name"): c for c in sch.children_of("Component")}

    for name, c in comps.items():
        p = c.position
        if p and (p[0] % grid or p[1] % grid):
            out.append(Finding("grid", "error", path, name, f"Position {p} is off the {grid} px grid"))
        kind = c.get("Type")
        if kind in TAG_BLOCKS:
            scope = path if c.param("Visibility") == LOCAL_VISIBILITY else "<global>"
            role = "from" if kind == "From" else "goto" if kind == "Goto" else "label"
            tags.setdefault((c.param("Tag"), scope), []).append((role, path, name))
        sub = c.child("Schematic")
        if sub is not None:
            out += _lint_level(sub, f"{path.rstrip('/')}/{name}", grid, tags)

    names = [n for n in comps if comps[n].position and comps[n].get("Type") not in CONTAINERS]
    for i, a in enumerate(names):
        pa = comps[a].position
        for b in names[i + 1:]:
            pb = comps[b].position
            lim = SMALL_OVERLAP_PX if SMALL & {comps[a].get("Type"), comps[b].get("Type")} else OVERLAP_PX
            if abs(pa[0] - pb[0]) < lim and abs(pa[1] - pb[1]) < lim:
                out.append(Finding("overlap", "error", path, f"{a} / {b}", f"components {a} and {b} overlap"))

    segs = []
    for k, conn in enumerate(sch.children_of("Connection")):
        label = f"connection {k} ({conn.get('SrcComponent')}:{conn.get('SrcTerminal')})"
        for p in _all_points(conn):
            if p[0] % grid or p[1] % grid:
                out.append(Finding("grid", "error", path, label, f"point {p} is off the {grid} px grid"))
        mine = _endpoints(conn)
        diagonal = False
        for (a, oa), (b, ob) in _segments(conn, comps):
            if a == b:
                continue
            if a[0] != b[0] and a[1] != b[1]:
                # PLECS adds the corner itself on a leg that ends at a terminal, so only a
                # segment between two explicit Points is a real diagonal.
                if oa is None and ob is None and not diagonal:
                    out.append(Finding("diagonal", "error", path, label,
                                       f"segment {a} -> {b} between two Points is not horizontal or vertical"))
                    diagonal = True
                elif oa and ob and abs(a[0] - b[0]) > UNROUTED_PX and abs(a[1] - b[1]) > UNROUTED_PX:
                    out.append(Finding("unrouted", "warn", path, label,
                                       f"no Points between {oa} and {ob}; PLECS routes it without avoiding other blocks"))
                continue
            segs.append(((a, b), k))
            for n, c in comps.items():
                half = SMALL_BODY_HALF if c.get("Type") in SMALL else BODY_HALF
                if (n not in mine and c.position and c.get("Type") not in CONTAINERS
                        and _seg_hits_box(a, b, c.position, half)):
                    out.append(Finding("wire-through-component", "error", path, label,
                                       f"wire runs through {n}; dragging {n} can join it to this net"))
    crossings = sum(1 for i, (s, ks) in enumerate(segs) for t, kt in segs[i + 1:] if ks != kt and _cross(s, t))
    if crossings:
        out.append(Finding("crossing", "warn", path, "-",
                           f"{crossings} wire crossing(s); reroute or replace the long run with Goto/From or Label tags"))
    return out


def lint_text(text: str, grid: int = 5) -> list:
    sch = pf.schematic(pf.parse(text))
    if sch is None:
        return [Finding("parse", "error", "/", "-", "no Plecs/Schematic block found")]
    tags: dict = {}
    out = _lint_level(sch, "/", grid, tags)
    for (tag, scope), entries in tags.items():
        roles = [e[0] for e in entries]
        if "goto" in roles or "from" in roles:
            gotos = [e for e in entries if e[0] == "goto"]
            if len(gotos) > 1:
                out.append(Finding("tag-duplicate-goto", "error", gotos[1][1], gotos[1][2],
                                   f"tag '{tag}' has {len(gotos)} Goto blocks in one scope"))
            global_goto = any(e[0] == "goto" for e in tags.get((tag, "<global>"), []))
            if "from" in roles and not gotos and not global_goto:
                for role, p, n in entries:
                    if role == "from":
                        out.append(Finding("tag-orphan-from", "error", p, n, f"From tag '{tag}' has no matching Goto"))
            used_below = any(e[0] == "from" for (t, s), es in tags.items() if t == tag for e in es)
            if gotos and not used_below:
                out.append(Finding("tag-unused-goto", "warn", gotos[0][1], gotos[0][2], f"Goto tag '{tag}' has no From"))
        elif len(entries) == 1:
            role, p, n = entries[0]
            out.append(Finding("tag-single-label", "warn", p, n, f"electrical Label '{tag}' appears only once"))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lint PLECS .plecs schematics for layout problems.")
    ap.add_argument("models", nargs="+", type=Path)
    ap.add_argument("--grid", type=int, default=5)
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    args = ap.parse_args(argv)
    failed, report = False, {}
    for m in args.models:
        findings = lint_text(m.read_text(encoding="utf-8", errors="replace"), args.grid)
        failed |= any(f.severity == "error" for f in findings)
        report[str(m)] = [asdict(f) for f in findings]
        if not args.json:
            for f in findings:
                print(f"{m}:{f.path}: {f.severity} [{f.code}] {f.where}: {f.message}")
            counts: dict = {}
            for f in findings:
                counts[f.code] = counts.get(f.code, 0) + 1
            print(f"{m}: {len(findings)} finding(s) {counts}")
    if args.json:
        print(json.dumps(report, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
