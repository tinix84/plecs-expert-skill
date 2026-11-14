import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/plecs-layout/scripts"))
import plecs_file  # noqa: E402
from layout import Sheet  # noqa: E402
from router import Router  # noqa: E402


def box(cx, cy, hw=20, hh=10):
    return (cx - hw, cy - hh, cx + hw, cy + hh)


def segments(tree, start):
    """All segments of a routed tree, starting from the source terminal."""
    out, pts = [], [start] + tree["points"]
    out += list(zip(pts, pts[1:]))
    return out, pts[-1]


def test_route_goes_around_an_obstacle():
    r = Router(grid=5, margin=10)
    r.add_obstacle("A", box(100, 100))
    r.add_obstacle("B", box(300, 100))
    r.add_obstacle("X", box(200, 100, 20, 30))    # sits on the straight line between A and B
    route = r.route([("A", 2, (120, 100)), ("B", 1, (280, 100))])
    assert route.tree["dst"] == ("B", 1)
    pts = [(120, 100)] + route.tree["points"] + [(280, 100)]
    for a, b in zip(pts, pts[1:]):
        assert a[0] == b[0] or a[1] == b[1]                    # orthogonal
    x0, y0, x1, y1 = (180, 70, 220, 130)
    for a, b in zip(pts, pts[1:]):                              # never enters X
        if a[1] == b[1]:
            assert not (y0 < a[1] < y1 and min(a[0], b[0]) < x1 and max(a[0], b[0]) > x0)


def test_three_terminal_net_becomes_branches():
    r = Router()
    for n, c in (("A", (100, 100)), ("B", (300, 100)), ("C", (300, 250))):
        r.add_obstacle(n, box(*c))
    route = r.route([("A", 2, (120, 100)), ("B", 1, (280, 100)), ("C", 1, (280, 250))])

    def dsts(node):
        return ([node["dst"]] if node["dst"] else []) + [d for b in node["branches"] for d in dsts(b)]

    assert sorted(dsts(route.tree)) == [("B", 1), ("C", 1)]
    assert route.tree["branches"]


def test_second_net_crosses_only_when_it_must():
    r = Router()
    for n, c in (("A", (100, 200)), ("B", (400, 200)), ("C", (250, 100)), ("D", (250, 300))):
        r.add_obstacle(n, box(*c))
    r.route([("A", 2, (120, 200)), ("B", 1, (380, 200))])
    vertical = r.route([("C", 2, (250, 110)), ("D", 1, (250, 290))])
    assert vertical.crossings == 1


def test_routed_tree_serializes_and_parses():
    sh = Sheet()
    sh.add("Gain", "A", (100, 100))
    sh.add("Gain", "B", (300, 200))
    r = Router()
    r.add_obstacle("A", box(100, 100))
    r.add_obstacle("B", box(300, 200))
    route = r.route([("A", 2, (120, 100)), ("B", 1, (280, 200))])
    sh.connect_tree("Signal", ("A", 2), route.tree)
    conn = plecs_file.schematic(plecs_file.parse(sh.model("t"))).child("Connection")
    assert conn.get("DstComponent") == "B"
    assert plecs_file.points(conn)
