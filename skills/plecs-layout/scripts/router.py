"""Orthogonal maze router for PLECS schematics (standard library only).

Routes each net on the grid with A*: symbol boxes (plus a margin) are obstacles,
bends cost extra, crossing another net at right angles is allowed at a cost, and
running along another net is forbidden. Nets with three or more terminals grow
as a tree, which is written as nested PLECS Branch blocks.

    r = Router(grid=5, margin=10)
    r.add_obstacle("R1", box)                       # absolute box from geometry.shape()
    route = r.route([("R1", 2, (140, 100)), ("C1", 1, (260, 160))])
    route.cost, route.crossings, route.tree         # tree: nested dict for Sheet.wire_tree()
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

H, V = 1, 2
BEND_COST = 8
CROSS_COST = 40


@dataclass
class Route:
    tree: dict | None            # {"points": [...], "dst": (name, term) | None, "branches": [...]}
    cost: float
    length: int                  # in grid steps
    crossings: int
    cells: dict = field(default_factory=dict)


class Router:
    def __init__(self, grid: int = 5, margin: int = 10, pad: int = 100):
        self.g = grid
        self.margin = margin
        self.pad = pad
        self.boxes: dict[str, tuple] = {}
        self.used: dict[tuple, int] = {}   # cell -> H|V bits of wires already routed

    # ---- setup -----------------------------------------------------------------
    def add_obstacle(self, name, box):
        m = self.margin
        self.boxes[name] = (box[0] - m, box[1] - m, box[2] + m, box[3] + m)

    def _cell(self, p):
        return (round(p[0] / self.g), round(p[1] / self.g))

    def _pt(self, c):
        return (c[0] * self.g, c[1] * self.g)

    def _blocked_by(self, c):
        x, y = self._pt(c)
        return [n for n, (x0, y0, x1, y1) in self.boxes.items() if x0 < x < x1 and y0 < y < y1]

    def _escape(self, name, tp):
        """Cells from a terminal straight out of its own (inflated) box, and the direction."""
        x0, y0, x1, y1 = self.boxes.get(name, (tp[0], tp[1], tp[0], tp[1]))
        d = min((tp[0] - x0, (-1, 0)), (x1 - tp[0], (1, 0)), (tp[1] - y0, (0, -1)), (y1 - tp[1], (0, 1)))[1]
        c = self._cell(tp)
        cells = [c]
        while name in self._blocked_by(c):
            c = (c[0] + d[0], c[1] + d[1])
            cells.append(c)
        return cells

    # ---- search ----------------------------------------------------------------
    def _bounds(self, pts):
        xs = [p[0] for p in pts] + [b[0] for b in self.boxes.values()] + [b[2] for b in self.boxes.values()]
        ys = [p[1] for p in pts] + [b[1] for b in self.boxes.values()] + [b[3] for b in self.boxes.values()]
        lo = self._cell((min(xs) - self.pad, min(ys) - self.pad))
        hi = self._cell((max(xs) + self.pad, max(ys) + self.pad))
        return lo, hi

    def _search(self, starts, targets, allowed, bounds):
        """A* from any start cell to any target cell. Returns (path, cost, crossings)."""
        (lx, ly), (hx, hy) = bounds
        tx = [t[0] for t in targets]
        ty = [t[1] for t in targets]

        def h(c):
            return max(0, min(tx) - c[0], c[0] - max(tx)) + max(0, min(ty) - c[1], c[1] - max(ty))

        open_, best, prev = [], {}, {}
        for s, d in starts:
            best[(s, d)] = 0
            heapq.heappush(open_, (h(s), 0, s, d))
        tset = set(targets)
        while open_:
            f, cost, c, d = heapq.heappop(open_)
            if cost > best.get((c, d), 1e18):
                continue
            if c in tset:
                path, node = [c], (c, d)
                while node in prev:
                    node = prev[node]
                    path.append(node[0])
                return path[::-1], cost
            for nd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + nd[0], c[1] + nd[1])
                if not (lx <= n[0] <= hx and ly <= n[1] <= hy):
                    continue
                if n not in allowed and n not in tset and self._blocked_by(n):
                    continue
                axis = H if nd[1] == 0 else V
                u = self.used.get(n, 0)
                if u & axis:
                    continue                      # would run along another net
                step = 1 + (BEND_COST if d and d != nd else 0) + (CROSS_COST if u else 0)
                nc = cost + step
                if nc < best.get((n, nd), 1e18):
                    best[(n, nd)] = nc
                    prev[(n, nd)] = (c, d)
                    heapq.heappush(open_, (nc + h(n), nc, n, nd))
        return None, float("inf")

    def route(self, terms, commit: bool = True) -> Route:
        """terms: [(component, terminal, (x, y)), ...]; the first is the connection source."""
        escapes = [self._escape(n, p) for n, _, p in terms]
        allowed = {c for e in escapes for c in e}
        bounds = self._bounds([p for _, _, p in terms])
        tree_cells = set(escapes[0])
        edges: dict = {}
        total, crossings = 0.0, 0

        def add_path(path):
            for a, b in zip(path, path[1:]):
                edges.setdefault(a, set()).add(b)
                edges.setdefault(b, set()).add(a)
            tree_cells.update(path)

        add_path(escapes[0])
        for esc in escapes[1:]:
            # search from the far end of this terminal's escape to the tree built so far
            start = esc[-1]
            path, cost = self._search([(start, None)], list(tree_cells), allowed, bounds)
            if path is None:
                return Route(None, float("inf"), 0, 0)
            total += cost
            crossings += sum(1 for c in path if self.used.get(c))
            add_path(esc + path[1:])
        if commit:
            for a, nbrs in edges.items():
                for b in nbrs:
                    self.used[a] = self.used.get(a, 0) | (H if a[1] == b[1] else V)
        tree = self._to_tree(escapes, edges, terms)
        length = sum(len(v) for v in edges.values()) // 2
        return Route(tree, total, length, crossings, dict(self.used))

    # ---- output ----------------------------------------------------------------
    def _to_tree(self, escapes, edges, terms):
        term_cell = {esc[0]: (n, t) for esc, (n, t, _) in zip(escapes, terms)}
        root = escapes[0][0]

        def corners(path):
            out = []
            for a, b, c in zip(path, path[1:], path[2:]):
                if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
                    out.append(self._pt(b))
            return out

        def walk(start, came_from):
            path = [start] if came_from is None else [came_from, start]
            cur, prev = start, came_from
            while True:
                nxt = [n for n in edges.get(cur, ()) if n != prev]
                if cur in term_cell and cur != root:
                    return {"points": corners(path), "dst": term_cell[cur], "branches": []}
                if len(nxt) == 1:
                    prev, cur = cur, nxt[0]
                    path.append(cur)
                    continue
                pts = corners(path) + ([self._pt(cur)] if len(nxt) > 1 and cur != root else [])
                return {"points": pts, "dst": None,
                        "branches": [walk(n, cur) for n in nxt]}

        return walk(root, None)
