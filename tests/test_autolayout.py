import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/plecs-layout/scripts"))
import autolayout  # noqa: E402
import geometry  # noqa: E402
import plecs_file  # noqa: E402


def rotations(box, terms):
    """All 8 orientations of a canonical ('right', not flipped) shape. Screen y points down."""
    def rot(p, d):
        x, y = p
        for _ in range(("right", "down", "left", "up").index(d)):
            x, y = -y, x
        return x, y

    out = {}
    for d in ("right", "down", "left", "up"):
        for f in (False, True):
            def t(p):
                x, y = p
                return rot((x, -y if f else y), d)
            corners = [t((box[0], box[1])), t((box[2], box[3]))]
            xs, ys = [c[0] for c in corners], [c[1] for c in corners]
            out[f"{d}/{'on' if f else 'off'}"] = {
                "box": [min(xs), min(ys), max(xs), max(ys)],
                "terminals": {k: list(t(v)) for k, v in terms.items()}}
    return out


FAKE = {
    "Resistor": {"": rotations((-20, -8, 20, 8), {"1": (-20, 0), "2": (20, 0)})},
    "Gain": {"": rotations((-15, -15, 15, 15), {"1": (-15, 0), "2": (15, 0)})},
    "Constant": {"": rotations((-10, -10, 10, 10), {"1": (10, 0)})},
    "Scope": {"1in": rotations((-15, -20, 15, 20), {"1": (-15, 0)})},
}


@pytest.fixture
def fake_geometry(monkeypatch):
    monkeypatch.setattr(geometry, "_TABLE", FAKE)


def chain():
    nl = autolayout.Netlist()
    nl.part("Ref", "Constant", {"Value": "1"}, zone="control")
    nl.part("K1", "Gain", {"K": "2"}, zone="control")
    nl.part("K2", "Gain", {"K": "3"}, zone="control")
    nl.part("Sc", "Scope", {"@Axes": "1"}, zone="output")
    nl.net("r", "Signal", [("Ref", 1), ("K1", 1)])
    nl.net("a", "Signal", [("K1", 2), ("K2", 1)])
    nl.net("b", "Signal", [("K2", 2), ("Sc", 1)])
    return nl


def test_signal_chain_is_layered_left_to_right(fake_geometry):
    nl = chain()
    sheet, report = nl.layout(zones=["control", "output"])
    xs = [nl.parts[n].pos[0] for n in ("Ref", "K1", "K2", "Sc")]
    assert xs == sorted(xs) and len(set(xs)) == 4
    assert report["tagged"] == [] and sorted(report["routed"]) == ["a", "b", "r"]
    assert report["unmeasured"] == []


def test_routed_output_is_orthogonal_and_parses(fake_geometry):
    sheet, _ = chain().layout(zones=["control", "output"])
    sch = plecs_file.schematic(plecs_file.parse(sheet.model("t")))
    for conn in sch.children_of("Connection"):
        pts = plecs_file.points(conn)
        for a, b in zip(pts, pts[1:]):
            assert a[0] == b[0] or a[1] == b[1]


def test_forced_tag_uses_goto_and_from(fake_geometry):
    nl = chain()
    nl.nets[2].tag = "y"          # ask for a tag on K2 -> Scope
    sheet, report = nl.layout(zones=["control", "output"])
    assert report["tagged"] == ["b"]
    text = sheet.schematic()
    assert "Type          Goto" in text and "Type          From" in text


def test_two_terminal_part_turns_to_face_its_neighbours(fake_geometry):
    nl = autolayout.Netlist()
    nl.part("A", "Gain", zone="z", at=(100, 100))
    nl.part("B", "Gain", zone="z", at=(100, 300))
    nl.part("R", "Resistor", zone="z", at=(100, 200))
    nl.net("n1", "Wire", [("A", 2), ("R", 1)])
    nl.net("n2", "Wire", [("R", 2), ("B", 1)])
    nl.layout(zones=["z"])
    assert nl.parts["R"].direction in ("down", "up")


def test_sources_are_vertical_and_ground_points_down_under_its_node():
    # uses the measured geometry.json shipped with the skill
    nl = autolayout.Netlist()
    nl.part("Vin", "DCVoltageSource", {"V": "10"}, zone="source")
    nl.part("R1", "Resistor", {"R": "1"}, zone="power")
    nl.part("Gnd", "Ground", zone="power")
    nl.net("in", "Wire", [("Vin", 1), ("R1", 1)])
    nl.net("gnd", "Wire", [("Vin", 2), ("R1", 2), ("Gnd", 1)])
    sheet, _ = nl.layout(zones=["source", "power"])
    vin, gnd = nl.parts["Vin"], nl.parts["Gnd"]
    plus = geometry.shape("DCVoltageSource", vin.pos, vin.direction, vin.flipped).terminals["1"]
    minus = geometry.shape("DCVoltageSource", vin.pos, vin.direction, vin.flipped).terminals["2"]
    assert plus[0] == minus[0] and plus[1] < minus[1]            # vertical, + on top
    g = geometry.shape("Ground", gnd.pos, gnd.direction, gnd.flipped).terminals["1"]
    assert g[1] < gnd.pos[1]                                      # terminal on top: symbol points down
    lowest = max(geometry.shape(p.kind, p.pos, p.direction, p.flipped).terminals[t][1]
                 for p, t in ((vin, "2"), (nl.parts["R1"], "2")))
    assert gnd.pos[1] > lowest                                    # below the node it grounds
    assert [f for f in sheet.lint() if f.severity == "error"] == []


def test_connectivity_check_finds_a_missing_wire():
    nl = autolayout.Netlist()
    nl.part("A", "Gain", zone="z")
    nl.part("B", "Gain", zone="z")
    nl.net("n", "Signal", [("A", 2), ("B", 1)])
    sheet, report = nl.layout(zones=["z"])
    assert report["connectivity"] == []
    broken = sheet.model("t").replace('DstComponent  "B"', 'DstComponent  "A"')
    assert autolayout.check_connectivity(broken, nl)


def test_connectivity_check_ignores_second_connection_on_a_terminal():
    nl = autolayout.Netlist()
    for n in ("A", "B", "C"):
        nl.part(n, "Gain", zone="z")
    nl.net("n", "Signal", [("A", 2), ("B", 1), ("C", 1)])
    sheet, _ = nl.layout(zones=["z"])
    two = sheet.model("t")
    import re
    # rewrite as two separate connections on A:2, which PLECS does not accept
    body = ('Connection {\n Type Signal\n SrcComponent "A"\n SrcTerminal 2\n DstComponent "B"\n DstTerminal 1\n}\n'
            'Connection {\n Type Signal\n SrcComponent "A"\n SrcTerminal 2\n DstComponent "C"\n DstTerminal 1\n}\n')
    two = re.sub(r"    Connection \{.*?\n    \}\n", "", two, flags=re.S).replace("  }\n}\n", body + "  }\n}\n")
    assert autolayout.check_connectivity(two, nl)
