"""Place, orient and route a PLECS schematic from a netlist (standard library only).

    from autolayout import Netlist
    nl = Netlist()
    nl.part("Va", "ACVoltageSource", {"V": "Vpk"}, zone="source")
    nl.part("Ra", "Resistor", {"R": "10e-3"}, zone="power")
    nl.net("pa", "Wire", [("Va", 1), ("Ra", 1)])
    nl.net("vdc", "Signal", [("Vm", 3), ("Err", 1), ("Scope", 1)])   # first entry drives the net
    sheet, report = nl.layout(zones=["source", "power", "measure", "control", "output"])
    text = sheet.model("demo")

Placement: zones run left to right. Inside a zone, blocks are layered by signal
flow (or by distance along nets for electrical parts) and ordered to reduce
crossings. Two-terminal parts get the direction that points their terminals at
their neighbours. Routing uses router.Router; a net that would cross another or
detour too far becomes a Goto/From pair (signals) or an electrical Label pair.

Sources stand vertical with terminal 1 on top, and every grounded pin gets its own
Ground symbol pointing down, straight below it (layout() adds Ground parts for this).

Terminal positions come from geometry.json. Without measured geometry for a block
the result is only approximate; `report["unmeasured"]` lists those blocks.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geometry  # noqa: E402
from layout import LOCAL, Sheet, snap  # noqa: E402
from router import Router  # noqa: E402

ORIENTATIONS = [(d, f) for d in ("right", "down", "left", "up") for f in (False, True)]
DETOUR_FACTOR = 2.5   # a route longer than this times its direct length becomes a tag
DETOUR_SLACK = 40     # ... plus this many grid steps
TAG_GAP = 20          # distance from a terminal to its tag block
GROUND_DROP = 40      # a Ground sits this far below the lowest terminal of its net

# Drawing conventions: this terminal faces this side. Sources stand vertical with terminal 1
# (+) on top; Ground has its terminal on top, so the symbol points down.
STYLE = {kind: ("1", "top") for kind in (
    "DCVoltageSource", "ACVoltageSource", "VoltageSource", "DCCurrentSource",
    "ACCurrentSource", "CurrentSource", "Ground")}


@dataclass
class Part:
    name: str
    kind: str
    params: dict
    zone: str
    direction: str = "right"
    flipped: bool = False
    pos: tuple = (0, 0)
    fixed: bool = False          # position given by the caller
    oriented: bool = False       # direction/flip given by the caller


@dataclass
class Net:
    name: str
    kind: str                  # "Wire" or "Signal"
    pins: list                 # [(part, terminal)]; for signals the first pin drives the net
    tag: str | None = None


@dataclass
class Netlist:
    parts: dict = field(default_factory=dict)
    nets: list = field(default_factory=list)

    def part(self, name, kind, params=None, zone="main", direction=None, flipped=None, at=None):
        p = Part(name, kind, dict(params or {}), zone)
        if direction:
            p.direction, p.oriented = direction, True
        if flipped is not None:
            p.flipped, p.oriented = flipped, True
        if at:
            p.pos, p.fixed = (snap(at[0]), snap(at[1])), True
        self.parts[name] = p
        return p

    def net(self, name, kind, pins, tag=None):
        self.nets.append(Net(name, kind, list(pins), tag))

    # ---- placement -------------------------------------------------------------
    def _neighbours(self):
        nb = defaultdict(set)
        for n in self.nets:
            names = [p for p, _ in n.pins]
            for a in names:
                nb[a].update(x for x in names if x != a)
        return nb

    def _layers(self, members):
        """Layer index per part: longest path over signal flow, else BFS over nets."""
        member_set = set(members)
        succ = defaultdict(set)
        for n in self.nets:
            if n.kind == "Signal" and n.pins[0][0] in member_set:
                for p, _ in n.pins[1:]:
                    if p in member_set:
                        succ[n.pins[0][0]].add(p)
        layer = {m: 0 for m in members}
        for _ in range(len(members)):
            changed = False
            for a in members:
                for b in succ[a]:
                    if layer[b] < layer[a] + 1 and layer[a] + 1 < len(members):
                        layer[b] = layer[a] + 1
                        changed = True
            if not changed:
                break
        if not any(succ.values()):
            nb = self._neighbours()
            layer, frontier = {members[0]: 0}, [members[0]]
            while frontier:
                nxt = []
                for a in frontier:
                    for b in sorted(nb[a] & member_set):
                        if b not in layer:
                            layer[b] = layer[a] + 1
                            nxt.append(b)
                frontier = nxt
                if not frontier:
                    rest = [m for m in members if m not in layer]
                    if rest:
                        layer[rest[0]] = max(layer.values()) + 1
                        frontier = [rest[0]]
        return layer

    def _place(self, zones, x0, y0, dx, dy, zone_gap):
        nb = self._neighbours()
        x = x0
        order_all = {}
        for z in zones:
            members = [n for n, p in self.parts.items() if p.zone == z]
            if not members:
                continue
            layer = self._layers(members)
            cols = defaultdict(list)
            for m in members:
                cols[layer[m]].append(m)
            # barycentre sweeps to reduce crossings
            order = {m: i for i, m in enumerate(members)}
            for _ in range(4):
                for c in sorted(cols):
                    def bary(m):
                        ys = [order[o] for o in nb[m] if o in order and o not in cols[c]]
                        return sum(ys) / len(ys) if ys else order[m]
                    cols[c].sort(key=bary)
                    for i, m in enumerate(cols[c]):
                        order[m] = i
            for c in sorted(cols):
                for i, m in enumerate(cols[c]):
                    p = self.parts[m]
                    if not p.fixed:
                        p.pos = (snap(x + c * dx), snap(y0 + i * dy))
            order_all.update(order)
            x += (max(cols) + 1) * dx + zone_gap

    def _style(self):
        """Apply STYLE: pick the first orientation (unflipped preferred) that puts the terminal on its side."""
        for p in self.parts.values():
            rule = STYLE.get(p.kind)
            if p.oriented or not rule or not geometry.is_measured(p.kind):
                continue
            term, side = rule
            for d, f in sorted(ORIENTATIONS, key=lambda o: o[1]):
                t = geometry.shape(p.kind, (0, 0), d, f, p.params).terminals.get(term)
                if t and side == "top" and t[0] == 0 and t[1] < 0:
                    p.direction, p.flipped, p.oriented = d, f, True
                    break

    def _split_grounds(self):
        """Give every grounded pin its own Ground symbol straight below it.

        All PLECS Ground blocks are one node, so a ground net needs no wire across the sheet:
        the net is replaced by one short pin-to-Ground net per pin. The netlist's own Ground
        parts are reused first; extra ones are added as '<ground>_<part>_<terminal>'.
        """
        new_nets = []
        for n in self.nets:
            grounds = [a for a, _ in n.pins if self.parts[a].kind == "Ground"]
            if n.kind != "Wire" or not grounds:
                new_nets.append(n)
                continue
            pins = [(a, t) for a, t in n.pins if self.parts[a].kind != "Ground"]
            pins.sort(key=lambda at: (-self._terminal(*at)[1], self._terminal(*at)[0]))
            template = self.parts[grounds[0]]
            for i, (a, t) in enumerate(pins):
                if i < len(grounds):
                    g = self.parts[grounds[i]]
                else:
                    g = self.part(f"{template.name}_{a}_{t}", "Ground", dict(template.params), zone=template.zone)
                    g.direction, g.flipped, g.oriented = template.direction, template.flipped, template.oriented
                self._drop_under(g, self._terminal(a, t))
                new_nets.append(Net(f"{n.name}_{a}_{t}", "Wire", [(a, t), (g.name, 1)]))
        self.nets = new_nets

    def _drop_under(self, g, node):
        """Place Ground g so that its terminal is GROUND_DROP below the node, on the same x."""
        if g.fixed:
            return
        t = geometry.shape(g.kind, (0, 0), g.direction, g.flipped, g.params).terminals.get("1", (0, 0))
        taken = {q.pos for q in self.parts.values() if q is not g}
        pos = (snap(node[0] - t[0]), snap(node[1] + GROUND_DROP - t[1]))
        while pos in taken:
            pos = (pos[0], pos[1] + GROUND_DROP)
        g.pos = pos

    def _orient(self):
        """Pick direction/flip for two-terminal parts so terminals face their neighbours."""
        where = {n: p.pos for n, p in self.parts.items()}
        pin_nets = defaultdict(list)
        for n in self.nets:
            for part, term in n.pins:
                pin_nets[(part, str(term))].append(n)
        for p in self.parts.values():
            if p.oriented or not geometry.is_measured(p.kind):
                continue
            base = geometry.shape(p.kind, p.pos, p.direction, p.flipped, p.params)
            if len(base.terminals) != 2:
                continue

            def cost(o):
                s = geometry.shape(p.kind, p.pos, o[0], o[1], p.params)
                total = 0
                for t, tp in s.terminals.items():
                    for n in pin_nets[(p.name, t)]:
                        for other, _ in n.pins:
                            if other != p.name:
                                ox, oy = where[other]
                                total += abs(ox - tp[0]) + abs(oy - tp[1])
                return total

            p.direction, p.flipped = min(ORIENTATIONS, key=cost)

    # ---- routing ---------------------------------------------------------------
    def _terminal(self, part, term):
        p = self.parts[part]
        s = geometry.shape(p.kind, p.pos, p.direction, p.flipped, p.params)
        return geometry.terminal(s, term, p.pos)

    def layout(self, zones=None, x0=100, y0=100, dx=80, dy=70, zone_gap=60, grid=5):
        zones = zones or sorted({p.zone for p in self.parts.values()})
        self._place(zones, x0, y0, dx, dy, zone_gap)
        self._style()
        self._orient()
        self._split_grounds()
        sheet = Sheet(grid)
        router = Router(grid=grid)
        for p in self.parts.values():
            sheet.add(p.kind, p.name, p.pos, p.direction, p.flipped,
                      {k: v for k, v in p.params.items() if not k.startswith("@")})
            router.add_obstacle(p.name, geometry.shape(p.kind, p.pos, p.direction, p.flipped, p.params).box)

        report = {"routed": [], "tagged": [],
                  "unmeasured": sorted({p.kind for p in self.parts.values() if not geometry.is_measured(p.kind)})}

        def span(n):
            pts = [self._terminal(a, t) for a, t in n.pins]
            return max(x for x, _ in pts) - min(x for x, _ in pts) + max(y for _, y in pts) - min(y for _, y in pts)

        for n in sorted(self.nets, key=span):
            pins = [(a, t, self._terminal(a, t)) for a, t in n.pins]
            direct = span(n) / grid
            trial = router.route(pins, commit=False) if not n.tag else None
            ok = (trial is not None and trial.tree is not None and trial.crossings == 0
                  and trial.length <= DETOUR_FACTOR * direct + DETOUR_SLACK)
            if ok:
                route = router.route(pins)
                sheet.connect_tree(n.kind, n.pins[0], route.tree)
                report["routed"].append(n.name)
            else:
                self._tag(sheet, router, n, pins)
                report["tagged"].append(n.name)
        return sheet, report

    def _tag(self, sheet, router, n, pins):
        """Replace a net by tag blocks next to each terminal plus a short stub wire."""
        tag = n.tag or n.name
        for i, (part, term, tp) in enumerate(pins):
            esc = router._escape(part, tp)
            (cx, cy), (ex, ey) = router._pt(esc[0]), router._pt(esc[-1])
            ux, uy = (ex > cx) - (ex < cx), (ey > cy) - (ey < cy)
            if (ux, uy) == (0, 0):
                ux = -1 if (n.kind == "Signal" and i > 0) else 1
            at = (snap(ex + ux * TAG_GAP), snap(ey + uy * TAG_GAP))
            name = f"{tag}_{part}_{term}"
            direction = {(1, 0): "right", (-1, 0): "left", (0, 1): "down", (0, -1): "up"}[(ux, uy)]
            if n.kind == "Wire":
                sheet.label(name, tag, at, LOCAL, direction)
                src, dst = (part, term), (name, 1)
            elif i == 0:
                sheet.goto(name, tag, at, LOCAL, direction)
                src, dst = (part, term), (name, 1)
            else:
                flip = {"right": "left", "left": "right", "down": "up", "up": "down"}[direction]
                sheet.from_(name, tag, at, LOCAL, flip)
                src, dst = (name, 1), (part, term)
            router.add_obstacle(name, (at[0] - 10, at[1] - 8, at[0] + 10, at[1] + 8))
            sheet.wire(src, dst) if n.kind == "Wire" else sheet.signal(src, dst)
