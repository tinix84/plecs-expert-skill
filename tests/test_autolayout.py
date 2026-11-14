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


def test_series_chains_keep_their_rows_across_zones(fake_geometry):
    nl = autolayout.Netlist()
    zones = ("source", "power", "measure")
    for phase in ("A", "B"):
        for stage, zone in enumerate(zones):
            nl.part(f"{phase}{stage}", "Resistor", zone=zone)
        for stage in range(len(zones) - 1):
            nl.net(f"{phase}{stage}", "Wire", [(f"{phase}{stage}", 1), (f"{phase}{stage + 1}", 2)])
        nl.part(f"{phase}src", "Gain", zone=zones[0])
        nl.part(f"{phase}load", "Gain", zone=zones[-1])
        nl.net(f"{phase}src-net", "Wire", [(f"{phase}0", 2), (f"{phase}src", 1)])
        nl.net(f"{phase}load-net", "Wire", [(f"{phase}2", 1), (f"{phase}load", 1)])

    nl.layout(zones=zones)

    for phase in ("A", "B"):
        ys = [nl.parts[f"{phase}{stage}"].pos[1] for stage in range(len(zones))]
        assert len(set(ys)) == 1
        xs = [nl.parts[f"{phase}{stage}"].pos[0] for stage in range(len(zones))]
        assert xs == sorted(xs)
    assert nl.parts["A0"].pos[1] != nl.parts["B0"].pos[1]


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


@pytest.mark.parametrize("zones", [("control", "control", "control"), ("control", "measure", "measure")])
def test_forced_signal_tag_has_one_from_per_receiver(fake_geometry, zones):
    nl = autolayout.Netlist()
    for name, zone in zip(("Source", "R1", "R2"), zones):
        nl.part(name, "Gain", zone=zone)
    nl.net("feedback", "Signal", [("Source", 2), ("R1", 1), ("R2", 1)], tag="feedback")

    sheet, report = nl.layout(zones=list(dict.fromkeys(zones)))
    schematic = plecs_file.schematic(plecs_file.parse(sheet.model("t")))
    tags = [component for component in schematic.children_of("Component")
            if component.get("Type") in ("Goto", "From")]

    assert [component.get("Type") for component in tags].count("Goto") == 1
    assert [component.get("Type") for component in tags].count("From") == 2
    assert {component.param("Tag") for component in tags} == {"feedback"}
    assert report["connectivity"] == []
    assert report["unrouted"] == []


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
    sheet, report = nl.layout(zones=["source", "power"])
    vin, gnd = nl.parts["Vin"], nl.parts["Gnd"]
    resistor = nl.parts["R1"]
    plus = geometry.shape("DCVoltageSource", vin.pos, vin.direction, vin.flipped).terminals["1"]
    minus = geometry.shape("DCVoltageSource", vin.pos, vin.direction, vin.flipped).terminals["2"]
    assert plus[0] == minus[0] and plus[1] < minus[1]            # vertical, + on top
    g = geometry.shape("Ground", gnd.pos, gnd.direction, gnd.flipped).terminals["1"]
    assert g[1] < gnd.pos[1]                                      # terminal on top: symbol points down
    lowest = max(geometry.shape(p.kind, p.pos, p.direction, p.flipped).terminals[t][1]
                 for p, t in ((vin, "2"), (nl.parts["R1"], "2")))
    assert gnd.pos[1] > lowest                                    # below the node it grounds
    resistor_terms = geometry.shape("Resistor", resistor.pos, resistor.direction, resistor.flipped).terminals
    assert resistor_terms["1"][0] == resistor_terms["2"][0]
    assert resistor_terms["1"][1] < resistor_terms["2"][1]       # shunt stands above its grounded pin
    assert report["connectivity"] == []
    assert [f for f in sheet.lint() if f.severity == "error"] == []


def test_electrical_tag_emits_one_label_per_zone(fake_geometry):
    nl = autolayout.Netlist()
    for name, zone in (("A1", "left"), ("A2", "left"), ("B1", "right"), ("B2", "right")):
        nl.part(name, "Gain", zone=zone)
    nl.net("dc", "Wire", [("A1", 1), ("A2", 2), ("B1", 1), ("B2", 2)], tag="bus")

    sheet, report = nl.layout(zones=["left", "right"])
    schematic = plecs_file.schematic(plecs_file.parse(sheet.model("t")))
    labels = [component for component in schematic.children_of("Component") if component.get("Type") == "Label"]

    assert report["tagged"] == ["dc"]
    assert len(labels) == 2
    assert {component.param("Tag") for component in labels} == {"bus"}


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


def test_grounded_phase_rows_leave_room_for_each_ground():
    nl = autolayout.Netlist()
    for phase in "abc":
        nl.part(f"V{phase}", "ACVoltageSource", zone="source")
        nl.part(f"R{phase}", "Resistor", zone="load")
        nl.net(f"line_{phase}", "Wire", [(f"V{phase}", 1), (f"R{phase}", 1)])
    nl.part("Gnd", "Ground", zone="source")
    nl.net("neutral", "Wire", [(f"V{phase}", 2) for phase in "abc"]
           + [(f"R{phase}", 2) for phase in "abc"] + [("Gnd", 1)])

    sheet, report = nl.layout(zones=["source", "load"])

    assert report["unrouted"] == []
    assert report["connectivity"] == []
    assert [finding for finding in sheet.lint() if finding.severity == "error"] == []
    schematic = plecs_file.schematic(plecs_file.parse(sheet.model("phases")))
    grounds = [c for c in schematic.children_of("Component") if c.get("Type") == "Ground"]
    assert len(grounds) == 6
    assert all(c.get("Show") == "off" for c in grounds)


def test_series_ammeter_faces_the_electrical_chain():
    nl = autolayout.Netlist()
    nl.part("Left", "Resistor", at=(100, 100))
    meter = nl.part("Meter", "Ammeter", at=(250, 100))
    nl.part("Right", "Resistor", at=(400, 100))
    nl.net("in", "Wire", [("Left", 2), ("Meter", 1)])
    nl.net("out", "Wire", [("Meter", 2), ("Right", 1)])
    nl._orient()

    terminals = geometry.shape(meter.kind, meter.pos, meter.direction, meter.flipped).terminals
    assert terminals["1"][0] < meter.pos[0] < terminals["2"][0]
    assert terminals["1"][1] == terminals["2"][1] == meter.pos[1]


def test_router_keeps_wires_out_of_displayed_names():
    nl = autolayout.Netlist()
    nl.part("A", "Gain", at=(100, 100))
    nl.part("B", "Gain", at=(400, 100))
    nl.part("Keepout", "Gain", at=(250, 125))
    nl.net("signal", "Signal", [("A", 2), ("B", 1)])

    sheet, report = nl.layout()

    assert report["unrouted"] == []
    assert report["connectivity"] == []
    assert [finding for finding in sheet.lint() if finding.severity == "error"] == []


def test_new_tag_does_not_cover_an_existing_wire():
    sheet = autolayout.Sheet()
    sheet.add("Gain", "A", (100, 100))
    sheet.add("Gain", "B", (300, 100))
    sheet.signal(("A", 2), ("B", 1))

    assert not autolayout._tag_text_clear(sheet, "Goto", "Vdc", (200, 100), "right")
    assert autolayout._tag_text_clear(sheet, "Goto", "Vdc", (200, 200), "right")
