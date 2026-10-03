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
import lint_schematic as lint  # noqa: E402
import plecs_file as pf  # noqa: E402
from router import Router  # noqa: E402

ORIENTATIONS = [(d, f) for d in ("right", "down", "left", "up") for f in (False, True)]
DETOUR_FACTOR = 2.5   # a route longer than this times its direct length becomes a tag
DETOUR_SLACK = 40     # ... plus this many grid steps
TAG_GAP = 20          # distance from a terminal to its tag block
GROUND_DROP = 40      # a Ground sits this far below the lowest terminal of its net


def _tag_text_clear(sheet, kind, tag, at, direction):
    tag_shape = geometry.shape(kind, at, direction, False, {})
    x0, y0, x1, y1 = tag_shape.box
    tag_text = geometry.estimate_text_box(
        tag, ((x0 + x1) / 2, y1 + geometry.TEXT_GAP + geometry.TEXT_HEIGHT / 2))
    root = pf.parse(sheet.model("tag-space"))
    schematic = pf.schematic(root)
    for component in schematic.children_of("Component"):
        if component.position is None:
            continue
        shape = lint._shape(component)
        records, _ = lint.text_envelopes(component, shape)
        if lint._rects_overlap(tag_text, shape.box):
            return False
        for record in records:
            if lint._rects_overlap(tag_shape.box, record["box"]):
                return False
            if lint._rects_overlap(tag_text, record["box"]):
                return False
    return True

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
    row: int | None = None       # grid hint inside the zone
    col: int | None = None
    component: pf.Block | None = None
    requested_pos: tuple | None = None
    direction_explicit: bool = False
    flipped_explicit: bool = False


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

    def part(self, name, kind, params=None, zone="main", direction=None, flipped=None, at=None,
             row=None, col=None, component=None):
        """Add a part. row/col place it on its zone's grid (col 0 is the zone's left edge)."""
        part_params = dict(params or {})
        if component is not None:
            if not isinstance(component, pf.Block) or component.kind != "Component":
                raise ValueError("component must be a parsed Component block")
            if component.get("Name") != name or component.get("Type") != kind:
                raise ValueError("component template Name or Type does not match the part")
            template_params = {
                parameter.get("Variable"): parameter.get("Value")
                for parameter in component.children_of("Parameter")
                if parameter.get("Variable") is not None
            }
            if component.get("Axes") is not None:
                template_params["@Axes"] = component.get("Axes")
            if params is None:
                part_params = template_params
            elif {str(k): str(v) for k, v in part_params.items()} != template_params:
                raise ValueError("part parameters differ from component template")

        p = Part(name, kind, part_params, zone, row=row, col=col, component=component,
                 requested_pos=tuple(at) if at is not None else None)
        if direction:
            p.direction, p.oriented = direction, True
            p.direction_explicit = True
        elif component is not None and component.get("Direction"):
            p.direction, p.oriented = component.get("Direction"), True
        if flipped is not None:
            p.flipped, p.oriented = flipped, True
            p.flipped_explicit = True
        elif component is not None and component.get("Flipped") is not None:
            p.flipped = component.get("Flipped") == "on"
            p.oriented = True
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

    def _chains(self):
        """Series chains: two-terminal parts joined end to end by two-pin wire nets.

        Each chain becomes one row, and keeps that row across zones, so for example the
        three phases V -> R -> L -> Am line up as three rows.
        """
        def elec_pins(name):
            return {str(t) for n in self.nets if n.kind == "Wire" for a, t in n.pins if a == name}

        two_term = {n for n, p in self.parts.items() if p.kind != "Ground" and len(elec_pins(n)) == 2}
        link = defaultdict(set)
        for n in self.nets:
            if n.kind == "Wire" and len(n.pins) == 2:
                (a, _), (b, _) = n.pins
                if a in two_term and b in two_term:
                    link[a].add(b)
                    link[b].add(a)
        chains, seen = [], set()
        for start in sorted(two_term, key=lambda m: list(self.parts).index(m)):
            if start in seen or len(link[start]) > 1 or not link[start]:
                continue
            chain, prev, cur = [start], None, start
            seen.add(start)
            while True:
                nxt = [m for m in link[cur] if m != prev and m not in seen]
                if not nxt:
                    break
                prev, cur = cur, nxt[0]
                chain.append(cur)
                seen.add(cur)
            if len(chain) > 1:
                chains.append(chain)
        return chains

    def _place(self, zones, x0, y0, dx, dy, zone_gap):
        nb = self._neighbours()
        # series chains give rows (and column order) to parts without hints
        auto_row, auto_col = {}, {}
        for r, chain in enumerate(self._chains()):
            col_in_zone = defaultdict(int)
            for m in chain:
                p = self.parts[m]
                if p.row is None and p.col is None:
                    auto_row[m] = r
                    auto_col[m] = col_in_zone[p.zone]
                    col_in_zone[p.zone] += 1
        x = x0
        for z in zones:
            members = [n for n, p in self.parts.items() if p.zone == z]
            if not members:
                continue
            grid = {}
            for m in members:
                p = self.parts[m]
                if p.row is not None or p.col is not None:
                    grid[m] = (p.col or 0, p.row or 0)
                elif m in auto_row:
                    grid[m] = (auto_col[m], auto_row[m])
            rest = [m for m in members if m not in grid]
            used = set(grid.values())
            if rest:
                layer = self._layers(rest)
                cols = defaultdict(list)
                for m in rest:
                    cols[layer[m]].append(m)
                order = {m: i for i, m in enumerate(rest)}
                for _ in range(4):  # barycentre sweeps to reduce crossings
                    for c in sorted(cols):
                        def bary(m):
                            ys = [order[o] for o in nb[m] if o in order and o not in cols[c]]
                            return sum(ys) / len(ys) if ys else order[m]
                        cols[c].sort(key=bary)
                        for i, m in enumerate(cols[c]):
                            order[m] = i
                base = max((c for c, _ in used), default=-1) + 1 if used else 0
                for c in sorted(cols):
                    row = 0
                    for m in cols[c]:
                        while (base + c, row) in used:
                            row += 1
                        grid[m] = (base + c, row)
                        used.add((base + c, row))
                        row += 1
            for m, (c, r) in grid.items():
                p = self.parts[m]
                if not p.fixed:
                    p.pos = (snap(x + c * dx), snap(y0 + r * dy))
            x += (max(c for c, _ in grid.values()) + 1) * dx + zone_gap

    def _grounded_pins(self):
        """(part, terminal) pins that sit on a net containing a Ground block."""
        out = set()
        for n in self.nets:
            if any(self.parts[a].kind == "Ground" for a, _ in n.pins):
                out |= {(a, str(t)) for a, t in n.pins if self.parts[a].kind != "Ground"}
        return out

    def _style(self):
        """Apply drawing conventions using the measured geometry.

        STYLE parts (sources, Ground) get their listed terminal on top. A two-terminal part
        from a node to ground (shunt capacitor, load, voltmeter) stands vertical with the
        ground pin at the bottom.
        """
        grounded = self._grounded_pins()
        for p in self.parts.values():
            measured = geometry.shape(p.kind, p.pos, p.direction, p.flipped, p.params).measured
            if p.oriented or not measured or p.kind in STYLE:
                continue
            elec = [t for t in ("1", "2") if (p.name, t) in grounded]
            if len(elec) != 1:
                continue
            top = "2" if elec[0] == "1" else "1"
            for d, f in sorted(ORIENTATIONS, key=lambda o: o[1]):
                ts = geometry.shape(p.kind, (0, 0), d, f, p.params).terminals
                if top in ts and elec[0] in ts and ts[top][0] == ts[elec[0]][0] and ts[top][1] < ts[elec[0]][1]:
                    p.direction, p.flipped, p.oriented = d, f, True
                    break
        for p in self.parts.values():
            rule = STYLE.get(p.kind)
            measured = geometry.shape(p.kind, p.pos, p.direction, p.flipped, p.params).measured
            if p.oriented or not rule or not measured:
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
            if p.oriented:
                continue
            base = geometry.shape(p.kind, p.pos, p.direction, p.flipped, p.params)
            if not base.measured or len(base.terminals) != 2:
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
        original = Netlist(dict(self.parts), list(self.nets))
        self.report_unrouted = []
        self._place(zones, x0, y0, dx, dy, zone_gap)
        self._style()
        self._orient()
        self._split_grounds()
        sheet = Sheet(grid)
        router = Router(grid=grid)
        for p in self.parts.values():
            if p.component is not None:
                sheet.add_component(p.component, at=p.pos, direction=p.direction, flipped=p.flipped)
            else:
                sheet.add(p.kind, p.name, p.pos, p.direction, p.flipped, p.params)
            router.add_obstacle(p.name, geometry.shape(p.kind, p.pos, p.direction, p.flipped, p.params).box)

        geometry_coverage = []
        for p in sorted(self.parts.values(), key=lambda part: part.name):
            shape = geometry.shape(p.kind, p.pos, p.direction, p.flipped, p.params)
            if shape.measured:
                continue
            issue = geometry.coverage_issue(p.kind, p.params, p.direction, p.flipped)
            if issue is not None:
                geometry_coverage.append({"component": p.name, **issue})
        report = {"routed": [], "tagged": [],
                  "unmeasured": sorted({issue["kind"] for issue in geometry_coverage}),
                  "geometry_coverage": geometry_coverage}

        def span(n):
            pts = [self._terminal(a, t) for a, t in n.pins]
            return max(x for x, _ in pts) - min(x for x, _ in pts) + max(y for _, y in pts) - min(y for _, y in pts)

        for n in sorted(self.nets, key=span):
            pins = [(a, t, self._terminal(a, t)) for a, t in n.pins]
            direct = span(n) / grid
            trial = router.route(pins, commit=False) if not n.tag else None
            ok = (trial is not None and trial.tree is not None and trial.crossings == 0
                  and trial.length <= DETOUR_FACTOR * direct + DETOUR_SLACK)
            one_zone = len({self.parts[a].zone for a, _ in n.pins}) == 1
            if ok:
                route = router.route(pins)
                sheet.connect_tree(n.kind, n.pins[0], route.tree)
                report["routed"].append(n.name)
            elif one_zone and not n.tag:
                # a tag cannot help inside one zone: keep the best route, crossing or not
                route = router.route(pins)
                if route.tree is not None:
                    sheet.connect_tree(n.kind, n.pins[0], route.tree)
                    report["routed"].append(n.name)
                else:
                    self._unrouted(sheet, n.kind, pins)
            else:
                self._tag(sheet, router, n, pins)
                report["tagged"].append(n.name)
        original.parts = self.parts   # ground splitting added Ground parts
        report["connectivity"] = check_connectivity(sheet.model("check"), original)
        report["unrouted"] = self.report_unrouted
        return sheet, report

    def _unrouted(self, sheet, kind, ends):
        """Last resort: one connection with a branch per pin (PLECS takes one connection per
        terminal). Reported, because PLECS draws it without avoiding other blocks."""
        self.report_unrouted.append([e[0] for e in ends])
        tree = {"points": [], "dst": None, "branches": [{"points": [], "dst": e[:2], "branches": []} for e in ends[1:]]}
        sheet.connect_tree(kind, ends[0][:2], tree)

    def _tag(self, sheet, router, n, pins):
        """Replace a net by one tag per zone: pins of a zone are wired together as usual and
        reach the other zones through a tag (Goto/From for signals, electrical Label for wires)."""
        if n.kind == "Signal" and n.tag is not None:
            self._tag_signal_receivers(sheet, router, n, pins)
            return
        tag = n.tag or n.name
        groups: dict = {}
        for pin in pins:
            groups.setdefault(self.parts[pin[0]].zone, []).append(pin)
        for gi, group in enumerate(groups.values()):
            driver = n.kind == "Signal" and pins[0] in group
            anchor = group[0]
            part, term, tp = anchor
            esc = router._escape(part, tp)
            (cx, cy), (ex, ey) = router._pt(esc[0]), router._pt(esc[-1])
            ux, uy = (ex > cx) - (ex < cx), (ey > cy) - (ey < cy)
            if (ux, uy) == (0, 0):
                ux = 1 if (driver or n.kind == "Wire") else -1
            at = (snap(ex + ux * TAG_GAP), snap(ey + uy * TAG_GAP))
            direction = {(1, 0): "right", (-1, 0): "left", (0, 1): "down", (0, -1): "up"}[(ux, uy)]
            if n.kind == "Wire":
                kind, tag_dir = "Label", direction
            elif driver:
                kind, tag_dir = "Goto", direction
            else:
                kind = "From"
                tag_dir = {"right": "left", "left": "right", "down": "up", "up": "down"}[direction]
            while (any(b[0] - 12 < at[0] < b[2] + 12 and b[1] - 10 < at[1] < b[3] + 10
                       for b in router.boxes.values())
                   or not _tag_text_clear(sheet, kind, tag, at, tag_dir)):
                at = (at[0] + ux * 10, at[1] + uy * 10)
            name = f"{tag}_{part}_{term}"
            if kind == "Label":
                sheet.label(name, tag, at, LOCAL, tag_dir)
            elif kind == "Goto":
                sheet.goto(name, tag, at, LOCAL, tag_dir)
            else:
                sheet.from_(name, tag, at, LOCAL, tag_dir)
            shp = geometry.shape(kind, at, tag_dir, False, {})
            router.add_obstacle(name, shp.box if shp.measured else (at[0] - 10, at[1] - 8, at[0] + 10, at[1] + 8))
            tag_pin = (name, 1, geometry.terminal(shp, 1, at))
            # one routed tree per zone: the group's pins plus its tag; a From drives its group
            ends = [tag_pin] + group if kind == "From" else group + [tag_pin]
            route = router.route(ends)
            if route.tree is not None:
                sheet.connect_tree(n.kind, ends[0][:2], route.tree)
            else:
                self._unrouted(sheet, n.kind, ends)

    def _tag_signal_receivers(self, sheet, router, net, pins):
        """Emit an explicit signal Goto at the driver and a From at every receiver."""
        tag = net.tag
        for index, (part, term, tp) in enumerate(pins):
            driver = index == 0
            esc = router._escape(part, tp)
            (cx, cy), (ex, ey) = router._pt(esc[0]), router._pt(esc[-1])
            ux, uy = (ex > cx) - (ex < cx), (ey > cy) - (ey < cy)
            if (ux, uy) == (0, 0):
                ux = 1 if driver else -1
            at = (snap(ex + ux * TAG_GAP), snap(ey + uy * TAG_GAP))
            direction = {(1, 0): "right", (-1, 0): "left", (0, 1): "down", (0, -1): "up"}[(ux, uy)]
            if driver:
                tag_kind, tag_direction = "Goto", direction
            else:
                tag_kind = "From"
                tag_direction = {"right": "left", "left": "right", "down": "up", "up": "down"}[direction]
            while (any(b[0] - 12 < at[0] < b[2] + 12 and b[1] - 10 < at[1] < b[3] + 10
                       for b in router.boxes.values())
                   or not _tag_text_clear(sheet, tag_kind, tag, at, tag_direction)):
                at = (at[0] + ux * 10, at[1] + uy * 10)
            name = f"{tag}_{part}_{term}"
            if driver:
                sheet.goto(name, tag, at, LOCAL, tag_direction)
            else:
                sheet.from_(name, tag, at, LOCAL, tag_direction)
            shape = geometry.shape(tag_kind, at, tag_direction, False, {})
            box = shape.box if shape.measured else (at[0] - 10, at[1] - 8, at[0] + 10, at[1] + 8)
            router.add_obstacle(name, box)
            tag_pin = (name, 1, geometry.terminal(shape, 1, at))
            ends = [(part, term, tp), tag_pin] if driver else [tag_pin, (part, term, tp)]
            route = router.route(ends)
            if route.tree is not None:
                sheet.connect_tree("Signal", ends[0][:2], route.tree)
            else:
                self._unrouted(sheet, "Signal", ends)


def check_connectivity(text: str, nl: "Netlist", sheet_path: str = "/") -> list[str]:
    """Compare logical nets with one selected schematic, resolving local and global tags.

    ``sheet_path`` names a nested Subsystem by component path, such as ``/Control``.
    Local tag names are scoped to their containing schematic; Visibility "1" tags
    share the model-wide scope. The legacy two-argument call still checks the root.
    """
    import plecs_file as pf

    root = pf.parse(text)
    root_schematic = pf.schematic(root)
    if root_schematic is None:
        return ["no Schematic block found"]

    def normalize_path(path):
        parts = [part for part in str(path).split("/") if part]
        return "/" + "/".join(parts) if parts else "/"

    selected_path = normalize_path(sheet_path)
    sheets = {}

    def collect(schematic, path):
        sheets[path] = schematic
        for component in schematic.children_of("Component"):
            nested = component.child("Schematic")
            if nested is not None:
                name = component.get("Name") or "?"
                child_path = normalize_path(path.rstrip("/") + "/" + name)
                collect(nested, child_path)

    collect(root_schematic, "/")
    sch = sheets.get(selected_path)
    if sch is None:
        return [f"sheet path {selected_path} was not found"]
    comps = {c.get("Name"): c for c in sch.children_of("Component")}
    findings = []

    def add(message):
        if message not in findings:
            findings.append(message)

    def node(kind, pin):
        path, name, terminal = pin
        return kind, path, name, terminal

    def show_pin(pin):
        path, name, terminal = pin
        return f"{name}:{terminal}" if path == selected_path else f"{path}:{name}:{terminal}"

    parent: dict = {}

    def find(value):
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    def union(kind, a, b):
        parent[find(node(kind, a))] = find(node(kind, b))

    def ends(connection, path, out=None, root_connection=True):
        out = [] if out is None else out
        if root_connection and connection.get("SrcComponent"):
            out.append((path, connection.get("SrcComponent"), str(connection.get("SrcTerminal"))))
        if connection.get("DstComponent"):
            out.append((path, connection.get("DstComponent"), str(connection.get("DstTerminal"))))
        for branch in connection.children_of("Branch"):
            ends(branch, path, out, False)
        return out

    expected_pins = set()
    expected_drivers = set()
    expected = []
    for index, net in enumerate(nl.nets):
        if net.kind not in ("Wire", "Signal"):
            add(f"net {net.name} has unsupported kind {net.kind!r}")
            continue
        pins = [(selected_path, str(name), str(term)) for name, term in net.pins]
        if not pins:
            add(f"net {net.name} has no terminals")
            continue
        expected.append((index, net, pins))
        if net.kind == "Signal":
            expected_drivers.add(pins[0])
        for pin in pins:
            if pin in expected_pins and net.kind == "Signal":
                add(f"signal terminal {show_pin(pin)} is assigned to more than one logical net")
            expected_pins.add(pin)

    claimed: dict = {}
    actual_kinds = defaultdict(set)
    signal_sources = []
    for connection_index, conn in enumerate(sch.children_of("Connection")):
        kind = conn.get("Type")
        if kind not in ("Wire", "Signal"):
            add(f"connection {connection_index} has unsupported kind {kind!r}")
            continue
        pins = ends(conn, selected_path)
        seen_in_tree = set()
        for pin in pins:
            actual_kinds[pin].add(kind)
            if pin in seen_in_tree:
                add(f"terminal {show_pin(pin)} is attached more than once in one connection")
            seen_in_tree.add(pin)
            if pin in claimed and claimed[pin] != connection_index:
                add(f"terminal {show_pin(pin)} has more than one connection; PLECS ignores the extra one")
            claimed.setdefault(pin, connection_index)
            find(node(kind, pin))
        if pins:
            for pin in pins[1:]:
                union(kind, pins[0], pin)
        if kind == "Signal" and conn.get("SrcComponent"):
            signal_sources.append((selected_path, conn.get("SrcComponent"), str(conn.get("SrcTerminal"))))

    tag_groups = defaultdict(list)
    for path, level in sheets.items():
        for component in level.children_of("Component"):
            kind = component.get("Type")
            if kind not in ("Label", "Goto", "From"):
                continue
            name = component.get("Name")
            tag = component.param("Tag")
            visibility = component.param("Visibility")
            if not tag:
                if path == selected_path:
                    add(f"tag block {name} has no tag name")
                continue
            if visibility == "2":
                scope = path
            elif visibility == "1":
                scope = "<global>"
            else:
                scope = f"<unsupported:{visibility}>"
                if path == selected_path:
                    add(f"tag block {name} has unsupported Visibility {visibility!r}")
            wire_kind = "Wire" if kind == "Label" else "Signal"
            member = (kind, path, name)
            tag_groups[(wire_kind, tag, scope)].append(member)

    for (wire_kind, tag, scope), members in tag_groups.items():
        terminals = [(path, name, "1") for _, path, name in members]
        for terminal in terminals[1:]:
            union(wire_kind, terminals[0], terminal)
        if wire_kind != "Signal" or scope not in (selected_path, "<global>"):
            continue
        gotos = [name for kind, _, name in members if kind == "Goto"]
        froms = [name for kind, _, name in members if kind == "From"]
        if len(gotos) > 1:
            add(f"tag {tag!r} in scope {scope} has duplicate signal drivers: {', '.join(gotos)}")
        if froms and not gotos:
            add(f"tag {tag!r} in scope {scope} has unresolved From blocks: {', '.join(froms)}")
        if gotos and not froms:
            add(f"tag {tag!r} in scope {scope} has a Goto but no receiver")

    grounds = [(path, name, "1") for path, level in sheets.items()
               for name, component in ((c.get("Name"), c) for c in level.children_of("Component"))
               if component.get("Type") == "Ground"]
    for ground in grounds[1:]:
        union("Wire", grounds[0], ground)

    for name, part in nl.parts.items():
        component = comps.get(name)
        if component is None:
            add(f"component {name} is missing from the written model in {selected_path}")
        elif component.get("Type") != part.kind:
            add(f"component {name} has kind {component.get('Type')!r}; expected {part.kind!r}")

    for net_index, net, pins in expected:
        missing_components = [name for path, name, _ in pins if path == selected_path and name not in comps]
        if missing_components:
            continue
        wrong_kind = [pin for pin in pins if actual_kinds.get(pin) and net.kind not in actual_kinds[pin]]
        if wrong_kind:
            actual = sorted(actual_kinds[wrong_kind[0]])
            add(f"net {net.name} uses connection kind {', '.join(actual)}; expected {net.kind}")
        roots = {find(node(net.kind, pin)) for pin in pins}
        if len(roots) > 1:
            add(f"net {net.name} is split into {len(roots)} parts")

    roots_to_nets = defaultdict(set)
    roots_to_drivers = defaultdict(set)
    for net_index, net, pins in expected:
        for pin in pins:
            roots_to_nets[find(node(net.kind, pin))].add(net_index)
        if net.kind == "Signal":
            roots_to_drivers[find(node("Signal", pins[0]))].add(pins[0])

    def joined_is_intended(indices):
        nets = [nl.nets[index] for index in indices]
        tagged = {(net.kind, net.tag) for net in nets if net.tag}
        if len(tagged) == 1 and all(net.tag for net in nets):
            return True
        return all(
            net.kind == "Wire" and any(nl.parts.get(name) and nl.parts[name].kind == "Ground" for name, _ in net.pins)
            for net in nets
        )

    for indices in roots_to_nets.values():
        if len(indices) > 1 and not joined_is_intended(indices):
            names = sorted(nl.nets[index].name for index in indices)
            add("nets " + ", ".join(names) + " are joined")
    for drivers in roots_to_drivers.values():
        if len(drivers) > 1:
            add("signal net has multiple drivers: " + ", ".join(show_pin(pin) for pin in sorted(drivers)))

    for source in signal_sources:
        _, name, _ = source
        component = comps.get(name)
        if component is not None and component.get("Type") == "From":
            continue
        if component is not None and component.get("Type") in ("Goto", "Label", "Ground"):
            add(f"signal source {show_pin(source)} is not a driving terminal")
        elif source not in expected_drivers:
            add(f"signal source {show_pin(source)} does not match a logical net driver")

    helper_types = {"Goto", "From", "Label", "Ground"}
    for kind, path, name, terminal in list(parent):
        pin = (path, name, terminal)
        if path != selected_path or pin in expected_pins:
            continue
        component = comps.get(name)
        if component is not None and component.get("Type") in helper_types:
            continue
        add(f"unexpected terminal {show_pin(pin)} is connected as {kind}")
    return findings
