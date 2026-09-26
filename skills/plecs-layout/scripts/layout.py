"""Build readable PLECS schematics from Python (standard library only).

    from layout import Sheet, Zone
    sh = Sheet()
    grid = Zone(x=100, y=100, dx=60, dy=60)            # one zone per role
    sh.add("ACVoltageSource", "Va", grid.at(0, 0), direction="down", params={"V": "Vpk"})
    sh.wire(("Va", 1), ("Ra", 1), via=[grid.at(0, -1), grid.at(1, -1)])
    sh.goto("Vdc", tag="Vdc", at=(400, 300))           # tag instead of a long run
    sh.from_("Vdc_scope", tag="Vdc", at=(700, 500))
    text = sh.model("demo", init="Vpk = 230*sqrt(2);")
    assert not [f for f in sh.lint() if f.severity == "error"]

Every coordinate is snapped to the grid. Tags default to Visibility "2"
(this schematic only).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lint_schematic  # noqa: E402

LOCAL, GLOBAL = "2", "1"  # Goto/From/Label Visibility values


def snap(v: float, grid: int = 5) -> int:
    return int(round(v / grid) * grid)


@dataclass
class Zone:
    """A block of the sheet laid out as a column/row grid, e.g. the power stage or the control area."""
    x: int
    y: int
    dx: int = 60
    dy: int = 60

    def at(self, col: float, row: float) -> tuple[int, int]:
        return (self.x + round(col * self.dx), self.y + round(row * self.dy))


def _check_orthogonal(pts):
    for a, b in zip(pts, pts[1:]):
        if a[0] != b[0] and a[1] != b[1]:
            raise ValueError(f"points {a} -> {b} are not horizontal or vertical")


def hv(a, b):
    """Corner for an L-shaped route: horizontal first, then vertical."""
    return [(b[0], a[1])]


def vh(a, b):
    """Corner for an L-shaped route: vertical first, then horizontal."""
    return [(a[0], b[1])]


class Sheet:
    def __init__(self, grid: int = 5):
        self.grid = grid
        self._comps: list[str] = []
        self._conns: list[str] = []
        self.names: set[str] = set()

    def _pt(self, p):
        return (snap(p[0], self.grid), snap(p[1], self.grid))

    def add(self, kind: str, name: str, at, direction: str = "right", flipped: bool = False,
            params: dict | None = None, label: str = "north", show_name: bool = True) -> str:
        if name in self.names:
            raise ValueError(f"duplicate component name {name!r}")
        self.names.add(name)
        x, y = self._pt(at)
        body = [
            "Component {", f"  Type          {kind}", f"  Name          {json.dumps(name)}",
            f"  Show          {'on' if show_name else 'off'}", f"  Position      [{x}, {y}]",
            f"  Direction     {direction}", f"  Flipped       {'on' if flipped else 'off'}",
            f"  LabelPosition {label}",
        ]
        for var, val in (params or {}).items():
            body += ["  Parameter {", f"    Variable      {json.dumps(var)}",
                     f"    Value         {json.dumps(str(val))}", "    Show          off", "  }"]
        self._comps.append("\n".join(body + ["}"]))
        return name

    def goto(self, name, tag, at, visibility=LOCAL, direction="right"):
        return self.add("Goto", name, at, direction, params={"Tag": tag, "Visibility": visibility},
                        label="south", show_name=False)

    def from_(self, name, tag, at, visibility=LOCAL, direction="right"):
        return self.add("From", name, at, direction, params={"Tag": tag, "Visibility": visibility},
                        label="south", show_name=False)

    def label(self, name, tag, at, visibility=LOCAL, direction="right"):
        """Electrical Label: joins electrical nets that carry the same tag."""
        return self.add("Label", name, at, direction, params={"Tag": tag, "Visibility": visibility},
                        label="south", show_name=False)

    def _connection(self, kind, src, dst_list, via):
        sname, sterm = src
        lines = ["Connection {", f"  Type          {kind}", f"  SrcComponent  {json.dumps(sname)}",
                 f"  SrcTerminal   {sterm}"]
        pts = [self._pt(p) for p in via or []]
        _check_orthogonal(pts)
        if pts:
            lines.append("  Points        [" + "; ".join(f"{x}, {y}" for x, y in pts) + "]")
        if len(dst_list) == 1 and len(dst_list[0]) == 2:
            dname, dterm = dst_list[0]
            lines += [f"  DstComponent  {json.dumps(dname)}", f"  DstTerminal   {dterm}"]
        else:
            for d in dst_list:
                dname, dterm, *bvia = d
                bpts = [self._pt(p) for p in (bvia[0] if bvia else [])]
                # A branch starts at the junction, the parent's last Point.
                _check_orthogonal(pts[-1:] + bpts)
                lines.append("  Branch {")
                if bpts:
                    lines.append("    Points        [" + "; ".join(f"{x}, {y}" for x, y in bpts) + "]")
                lines += [f"    DstComponent  {json.dumps(dname)}", f"    DstTerminal   {dterm}", "  }"]
        self._conns.append("\n".join(lines + ["}"]))

    def wire(self, src, dst, via=None):
        """Electrical wire. dst is (name, terminal) or a list of (name, terminal[, branch_points])."""
        self._connection("Wire", src, dst if isinstance(dst, list) else [dst], via)

    def signal(self, src, dst, via=None):
        """Signal line. Same arguments as wire()."""
        self._connection("Signal", src, dst if isinstance(dst, list) else [dst], via)

    def connect_tree(self, kind: str, src, tree: dict):
        """Write a routed net (router.Route.tree) as one connection with nested Branch blocks."""
        sname, sterm = src

        def body(node, pad):
            out = []
            if node["points"]:
                out.append(pad + "Points        [" + "; ".join(f"{x}, {y}" for x, y in node["points"]) + "]")
            if node["dst"]:
                out += [pad + f"DstComponent  {json.dumps(node['dst'][0])}", pad + f"DstTerminal   {node['dst'][1]}"]
            for b in node["branches"]:
                out += [pad + "Branch {"] + body(b, pad + "  ") + [pad + "}"]
            return out

        lines = ["Connection {", f"  Type          {kind}", f"  SrcComponent  {json.dumps(sname)}",
                 f"  SrcTerminal   {sterm}"] + body(tree, "  ") + ["}"]
        self._conns.append("\n".join(lines))

    def schematic(self) -> str:
        body = "\n".join(self._comps + self._conns)
        inner = "\n".join("    " + line for line in body.splitlines())
        return "  Schematic {\n    Location      [0, 26; 1200, 800]\n    ZoomFactor    1\n" + inner + "\n  }\n"

    def model(self, name: str, init: str = "", time_span: str = "0.1", outputs: int = 0) -> str:
        """Full model text. `outputs` declares model-level output ports, which XML-RPC
        plecs.simulate returns; place matching Output blocks with Index 1..outputs."""
        init_q = json.dumps(init)
        terminals = "".join(f'  Terminal {{\n    Type          Output\n    Index         "{i}"\n  }}\n'
                            for i in range(1, outputs + 1))
        return (
            "Plecs {\n"
            f"  Name          {json.dumps(name)}\n"
            '  Version       "4.7"\n'
            '  CircuitModel  "ContStateSpace"\n'
            '  StartTime     "0.0"\n'
            f"  TimeSpan      {json.dumps(time_span)}\n"
            '  Solver        "auto"\n'
            f"  InitializationCommands {init_q}\n"
            + terminals + self.schematic() + "}\n"
        )

    def lint(self):
        return lint_schematic.lint_text(self.model("lint"), self.grid)
