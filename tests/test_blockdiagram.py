import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/plecs-layout/scripts"))
import autolayout  # noqa: E402
import blockdiagram  # noqa: E402
import example_blockdiagram  # noqa: E402
import geometry  # noqa: E402
import plecs_file  # noqa: E402


def cscript_chain():
    nl = autolayout.Netlist()
    nl.part("Ref", "Constant", {"Value": "1"}, zone="control")
    for name in ("C1", "C2"):
        nl.part(name, "CScript", {"NumInputs": "1", "NumOutputs": "1"}, zone="control")
    nl.part("View", "Scope", {"@Axes": "1"}, zone="output")
    nl.net("ref", "Signal", [("Ref", 1), ("C1", 1)])
    nl.net("stage", "Signal", [("C1", 2), ("C2", 1)])
    nl.net("result", "Signal", [("C2", 2), ("View", 1)])
    return nl


def components(sheet):
    return {c.get("Name"): c for c in plecs_file.schematic(plecs_file.parse(sheet.model("controller"))).children_of("Component")}


def subsystem_template(name, half_width, half_height):
    return plecs_file.parse(f'''Component {{
  Type Subsystem
  Name "{name}"
  Position [0, 0]
  Direction up
  Flipped off
  Frame [-{half_width}, -{half_height}; {half_width}, {half_height}]
  Terminal {{
    Type Input
    Position [-{half_width}, 0]
    Direction left
    Index "1"
  }}
  Terminal {{
    Type Output
    Position [{half_width}, 0]
    Direction right
    Index "1"
  }}
}}''').children[0]


def cscript_template(name, direction):
    return plecs_file.parse(f'''Component {{
  Type CScript
  Name "{name}"
  Position [100, 100]
  Direction {direction}
  Flipped off
  Parameter {{
    Variable "NumInputs"
    Value "1"
  }}
  Parameter {{
    Variable "NumOutputs"
    Value "1"
  }}
}}''').children[0]


def scope_template(name, label_position="north"):
    return plecs_file.parse(f'''Component {{
  Type Scope
  Name "{name}"
  Position [100, 100]
  Direction right
  Axes "1"
  LabelPosition {label_position}
}}''').children[0]


def test_chain_is_layered_left_to_right_with_fixed_orientations():
    nl = cscript_chain()
    sheet, report = blockdiagram.layout(nl, zones=["control", "output"])
    comps = components(sheet)
    assert comps["C1"].get("Direction") == "up"
    assert comps["C2"].get("Direction") == "up"
    assert comps["View"].get("Direction") == "right"
    assert comps["Ref"].position[0] < comps["C1"].position[0] < comps["C2"].position[0] < comps["View"].position[0]
    assert report["placement"]["layers"]["Ref"] < report["placement"]["layers"]["C1"]
    assert report["placement"]["layers"]["C1"] < report["placement"]["layers"]["C2"]
    assert report["placement"]["layers"]["C2"] < report["placement"]["layers"]["View"]


def test_template_orientation_is_normalized_before_geometry_reserves_space():
    nl = autolayout.Netlist()
    nl.part("Ref", "Constant", {"Value": "1"}, zone="input")
    nl.part("C1", "CScript", zone="control", component=cscript_template("C1", "right"))
    nl.part("C2", "CScript", zone="control", component=cscript_template("C2", "right"))
    nl.part("View", "Scope", zone="output", component=scope_template("View", "east"))
    nl.net("ref", "Signal", [("Ref", 1), ("C1", 1)])
    nl.net("stage", "Signal", [("C1", 2), ("C2", 1)])
    nl.net("result", "Signal", [("C2", 2), ("View", 1)])

    sheet, report = blockdiagram.layout(nl, zones=["input", "control", "output"])

    emitted = components(sheet)
    assert emitted["C1"].get("Direction") == "up"
    assert emitted["C2"].get("Direction") == "up"
    for name in ("C1", "C2"):
        assert geometry.component_shape(emitted[name]).box == geometry.shape(
            "CScript", emitted[name].position, "up",
            params={"NumInputs": "1", "NumOutputs": "1"}
        ).box
    assert report["quality"]["accepted"]
    assert report["connectivity"] == []


def test_subsystem_template_supplies_controller_frame_and_port_roles():
    template = plecs_file.parse('''Component {
  Type Subsystem
  Name "Controller"
  Position [100, 200]
  Direction up
  Flipped off
  Frame [-25, -15; 25, 15]
  Terminal {
    Type Input
    Position [-25, 0]
    Direction left
    Index "1"
  }
  Terminal {
    Type Output
    Position [30, 0]
    Direction right
    Index "1"
  }
  Schematic {
    Component {
      Type Gain
      Name "NestedGain"
      Position [80, 90]
    }
  }
}''').children[0]
    netlist = autolayout.Netlist()
    netlist.part("Reference", "Constant", {"Value": "1"}, zone="control")
    netlist.part("Controller", "Subsystem", zone="control", component=template)
    netlist.part("View", "Scope", {"@Axes": "1"}, zone="output")
    netlist.net("reference", "Signal", [("Reference", 1), ("Controller", 1)])
    netlist.net("result", "Signal", [("Controller", 2), ("View", 1)])

    resolved, roles = blockdiagram._validate(netlist, 5)

    assert resolved["Controller"][2].box == (-25, -15, 25, 15)
    assert resolved["Controller"][2].terminals == {"1": (-25, 0), "2": (30, 0)}
    assert roles["Controller"] == {"1": "in", "2": "out"}

    sheet, report = blockdiagram.layout(netlist, zones=["control", "output"])
    emitted = components(sheet)["Controller"]
    assert report["quality"]["coverage"]["unsupported"] == []
    assert report["quality"]["coverage"]["unsupported"] == []
    assert emitted.get("Frame") == "[-25, -15; 25, 15]"
    assert [(term.get("Type"), term.get("Position"))
            for term in emitted.children_of("Terminal")] == [
        ("Input", "[-25, 0]"),
        ("Output", "[30, 0]"),
    ]


def test_unequal_size_subsystems_fit_in_a_connected_controller_chain():
    nl = autolayout.Netlist()
    nl.part("Reference", "Constant", {"Value": "1"}, zone="source")
    nl.part("Small", "Subsystem", zone="control",
            component=subsystem_template("Small", 25, 15))
    nl.part("Large", "Subsystem", zone="control",
            component=subsystem_template("Large", 50, 40))
    nl.part("View", "Output", {"Index": "1"}, zone="output")
    nl.net("input", "Signal", [("Reference", 1), ("Small", 1)])
    nl.net("between", "Signal", [("Small", 2), ("Large", 1)])
    nl.net("result", "Signal", [("Large", 2), ("View", 1)])

    sheet, report = blockdiagram.layout(nl, zones=["source", "control", "output"])

    emitted = components(sheet)
    small = geometry.component_shape(emitted["Small"])
    large = geometry.component_shape(emitted["Large"])
    assert (small.box[2] - small.box[0], small.box[3] - small.box[1]) == (50, 30)
    assert (large.box[2] - large.box[0], large.box[3] - large.box[1]) == (100, 80)
    assert small.box[2] < large.box[0]
    assert report["quality"]["accepted"]
    assert report["connectivity"] == []


def test_feedback_edge_is_removed_from_placement_graph_and_reported():
    nl = autolayout.Netlist()
    nl.part("A", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    nl.part("B", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    nl.net("forward", "Signal", [("A", 2), ("B", 1)])
    nl.net("feedback", "Signal", [("B", 2), ("A", 1)])

    sheet, report = blockdiagram.layout(nl)

    assert report["placement"]["feedback_edges"] == [("feedback", "B", "A")]
    assert components(sheet)["A"].position[0] < components(sheet)["B"].position[0]
    assert nl.parts["A"].pos == (0, 0) and nl.parts["B"].pos == (0, 0)


def test_self_loop_is_a_feedback_edge():
    nl = autolayout.Netlist()
    nl.part("Loop", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    nl.net("self", "Signal", [("Loop", 2), ("Loop", 1)])

    _, report = blockdiagram.layout(nl)

    assert report["placement"]["feedback_edges"] == [("self", "Loop", "Loop")]


def test_fixed_coordinates_are_preserved_and_inputs_are_unchanged():
    nl = autolayout.Netlist()
    nl.part("Fixed", "CScript", {"NumInputs": "1", "NumOutputs": "1"}, at=(100, 200))

    sheet, _ = blockdiagram.layout(nl)

    assert components(sheet)["Fixed"].position == (100, 200)
    assert nl.parts["Fixed"].pos == (100, 200)


def test_controller_layout_rejects_off_grid_fixed_coordinates():
    nl = autolayout.Netlist()
    nl.part("Fixed", "CScript", {"NumInputs": "1", "NumOutputs": "1"}, at=(101, 200))

    with pytest.raises(blockdiagram.LayoutError, match="off the 5 px grid"):
        blockdiagram.layout(nl)


def test_controller_layout_rejects_non_five_pixel_grid():
    nl = autolayout.Netlist()
    nl.part("A", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    with pytest.raises(blockdiagram.LayoutError, match="only grid=5"):
        blockdiagram.layout(nl, grid=10)


def test_controller_layout_rejects_unknown_geometry_with_component_identity():
    nl = autolayout.Netlist()
    nl.part("Mystery", "UnknownBlock")

    with pytest.raises(blockdiagram.LayoutError, match="Mystery.*geometry"):
        blockdiagram.layout(nl)


def test_controller_layout_rejects_unmeasured_cscript_port_count():
    nl = autolayout.Netlist()
    nl.part("Wide", "CScript", {"NumInputs": "[1 1 1]", "NumOutputs": "1"})

    with pytest.raises(blockdiagram.LayoutError, match="Wide.*3in1out"):
        blockdiagram.layout(nl)


def test_conflicting_column_hints_are_reported():
    nl = autolayout.Netlist()
    nl.part("A", "CScript", {"NumInputs": "1", "NumOutputs": "1"}, col=1)
    nl.part("B", "CScript", {"NumInputs": "1", "NumOutputs": "1"}, col=0)
    nl.net("ab", "Signal", [("A", 2), ("B", 1)])

    with pytest.raises(blockdiagram.LayoutError, match="column hints"):
        blockdiagram.layout(nl)


def test_fixed_position_that_conflicts_with_row_hint_is_rejected():
    nl = autolayout.Netlist()
    nl.part("Fixed", "CScript", {"NumInputs": "1", "NumOutputs": "1"}, at=(100, 200), row=0)
    with pytest.raises(blockdiagram.LayoutError, match="Fixed fixed y=.*conflicts with row 0"):
        blockdiagram.layout(nl)


def test_same_inputs_produce_same_text_without_mutating_netlist():
    nl = cscript_chain()
    first, first_report = blockdiagram.layout(nl, zones=["control", "output"])
    second, second_report = blockdiagram.layout(nl, zones=["control", "output"])

    assert first.model("same") == second.model("same")
    assert first_report["placement"] == second_report["placement"]
    assert all(part.pos == (0, 0) for part in nl.parts.values())


def test_signal_net_rejects_wrong_driver_role():
    nl = autolayout.Netlist()
    nl.part("Reader", "Scope", {"@Axes": "1"})
    nl.part("Writer", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    nl.net("bad", "Signal", [("Reader", 1), ("Writer", 1)])

    with pytest.raises(blockdiagram.LayoutError, match="Reader:1.*input terminal.*drive"):
        blockdiagram.layout(nl)


def test_clear_neighbouring_chain_uses_one_direct_connection_per_net():
    nl = autolayout.Netlist()
    nl.part("A", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    nl.part("B", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    nl.net("ab", "Signal", [("A", 2), ("B", 1)])
    sheet, report = blockdiagram.layout(nl, max_wire=200)
    schematic = plecs_file.schematic(plecs_file.parse(sheet.model("controller")))

    assert len(schematic.children_of("Connection")) == 1
    assert report["routed"] == ["ab"]
    assert report["tagged"] == []
    assert report["connectivity"] == []


@pytest.mark.parametrize("net_name", ["nnnnnn", "nnnnnnn", "nnnnnnnn", "nnnnnnnnn"])
def test_long_net_name_keeps_reserved_column_gap_at_least_forty_pixels(net_name):
    nl = autolayout.Netlist()
    nl.part("A", "Constant", {"Value": "1"})
    nl.part("B", "Output", {"Index": "1"})
    nl.net(net_name, "Signal", [("A", 1), ("B", 1)])

    sheet, report = blockdiagram.layout(nl)

    resolved, roles = blockdiagram._validate(nl, 5)
    bounds = {}
    for name, part in nl.parts.items():
        tags = [(str(term), net.name) for net in nl.nets for owner, term in net.pins
                if owner == name]
        bounds[name] = blockdiagram._expanded_bounds(
            part, resolved[name][2], roles[name], tags
        )
    positions = report["placement"]["positions"]
    envelope_gap = (positions["B"][0] + bounds["B"][0]
                    - positions["A"][0] - bounds["A"][2])

    assert envelope_gap >= blockdiagram.MIN_COLUMN_GAP


def test_max_wire_zero_tags_every_net_and_creates_each_receiver():
    sheet, report = blockdiagram.layout(cscript_chain(), zones=["control", "output"], max_wire=0)
    schematic = plecs_file.schematic(plecs_file.parse(sheet.model("controller")))
    tags = [c for c in schematic.children_of("Component") if c.get("Type") in ("Goto", "From")]

    assert len([c for c in tags if c.get("Type") == "Goto"]) == 3
    assert len([c for c in tags if c.get("Type") == "From"]) == 3
    assert report["tagged"] == ["ref", "result", "stage"]
    assert report["connectivity"] == []


def test_fanout_uses_all_tags_when_one_receiver_is_not_straight():
    nl = autolayout.Netlist()
    nl.part("Source", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    nl.part("A", "CScript", {"NumInputs": "1", "NumOutputs": "1"}, row=0)
    nl.part("B", "CScript", {"NumInputs": "1", "NumOutputs": "1"}, row=2)
    nl.net("fan", "Signal", [("Source", 2), ("A", 1), ("B", 1)])

    sheet, report = blockdiagram.layout(nl)
    schematic = plecs_file.schematic(plecs_file.parse(sheet.model("controller")))
    tags = [c for c in schematic.children_of("Component") if c.get("Type") in ("Goto", "From")]

    assert [c.get("Type") for c in tags].count("Goto") == 1
    assert [c.get("Type") for c in tags].count("From") == 2
    assert report["tagged"] == ["fan"]
    assert report["connectivity"] == []


def test_report_separates_routing_and_connectivity_results():
    _, report = blockdiagram.layout(cscript_chain())
    assert "connectivity" in report and "unrouted" in report
    assert report["connectivity"] == []
    assert report["unrouted"] == []


def test_multiport_cscript_geometry_preserves_all_four_signal_ports():
    nl = autolayout.Netlist()
    ports = {"NumInputs": "[1 1]", "NumOutputs": "[1 1]"}
    nl.part("C1", "CScript", ports, zone="control")

    sheet, report = blockdiagram.layout(nl)

    comps = components(sheet)
    assert set(geometry.shape("CScript", comps["C1"].position, "up", params=ports).terminals) == {
        "1", "2", "3", "4"
    }
    assert report["connectivity"] == []
    assert [finding for finding in report["lint"] if finding["severity"] == "error"] == []


def test_connected_multiport_cscript_accepts_separated_straight_wires():
    nl = autolayout.Netlist()
    nl.part("A", "Constant", {"Value": "1"}, zone="lower", at=(-200, 195))
    nl.part("B", "Constant", {"Value": "2"}, zone="upper", at=(100, 205))
    ports = {"NumInputs": "[1 1]", "NumOutputs": "[1 1]"}
    nl.part("M", "CScript", ports, zone="control", at=(400, 200))
    nl.part("Out1", "Output", {"Index": "1", "Width": "-1"}, zone="out1", at=(650, 195))
    nl.part("Out2", "Output", {"Index": "2", "Width": "-1"}, zone="out2", at=(850, 205))
    nl.net("a", "Signal", [("A", 1), ("M", 1)])
    nl.net("b", "Signal", [("B", 1), ("M", 2)])
    nl.net("x", "Signal", [("M", 3), ("Out1", 1)])
    nl.net("y", "Signal", [("M", 4), ("Out2", 1)])

    sheet, report = blockdiagram.layout(
        nl, zones=["lower", "upper", "control", "out1", "out2"], max_wire=600
    )

    assert report["quality"]["accepted"]
    assert report["connectivity"] == []
    assert report["tagged"] == []
    assert report["routed"] == ["a", "b", "x", "y"]
    assert components(sheet)["M"].get("Direction") == "up"


def test_connected_multiport_cscript_rejects_colliding_signal_tags():
    nl = autolayout.Netlist()
    nl.part("InA", "Constant", {"Value": "1"}, zone="input")
    nl.part("InB", "Constant", {"Value": "2"}, zone="input")
    nl.part("Controller", "CScript", {"NumInputs": "[1 1]", "NumOutputs": "[1 1]"}, zone="control")
    nl.part("OutA", "Output", {"Index": "1"}, zone="output")
    nl.part("OutB", "Output", {"Index": "2"}, zone="output")
    for name, pins in (
        ("input_a", [("InA", 1), ("Controller", 1)]),
        ("input_b", [("InB", 1), ("Controller", 2)]),
        ("output_a", [("Controller", 3), ("OutA", 1)]),
        ("output_b", [("Controller", 4), ("OutB", 1)]),
    ):
        nl.net(name, "Signal", pins)

    with pytest.raises(blockdiagram.LayoutError) as exc_info:
        blockdiagram.layout(nl, zones=["input", "control", "output"], max_wire=0)

    assert any(finding["code"] == "tag_spacing_conflict"
               and finding["component"] == "Controller"
               for finding in exc_info.value.findings)


def test_long_component_and_tag_names_expand_without_text_conflicts():
    nl = autolayout.Netlist()
    source = "Reference measurement at controller input"
    receiver = "Controller result display channel"
    tag = "compensated_dc_bus_voltage_reference"
    nl.part(source, "Constant", {"Value": "1"}, zone="input")
    nl.part(receiver, "CScript", {"NumInputs": "1", "NumOutputs": "1"}, zone="control")
    nl.part("Output display", "Output", {"Index": "1"}, zone="output")
    nl.net(tag, "Signal", [(source, 1), (receiver, 1)], tag=tag)
    nl.net("controller result", "Signal", [(receiver, 2), ("Output display", 1)])

    sheet, report = blockdiagram.layout(nl, zones=["input", "control", "output"])

    assert report["quality"]["accepted"]
    assert report["quality"]["metrics"]["occupied_area"] > 0
    assert [finding for finding in report["quality"]["findings"]
            if finding.get("code") == "text-overlap"] == []


def test_subsystem_geometry_is_rejected_without_an_authored_fixture():
    nl = autolayout.Netlist()
    nl.part("Nested controller", "Subsystem")

    with pytest.raises(blockdiagram.LayoutError, match="Nested controller.*geometry"):
        blockdiagram.layout(nl)


def test_authored_controller_example_has_zero_quality_score():
    sheet, report = example_blockdiagram.controller()

    assert report["quality"]["weighted_total"] == 0
    assert report["quality"]["accepted"]
    assert [finding for finding in sheet.lint() if finding.severity == "error"] == []


def test_authored_multiport_controller_has_zero_quality_score():
    sheet, report = example_blockdiagram.multiport_controller()

    assert report["quality"]["weighted_total"] == 0
    assert report["quality"]["accepted"]
    assert report["routed"] == ["input_a", "input_b", "output_x", "output_y"]
    assert report["tagged"] == []
    assert [finding for finding in sheet.lint() if finding.severity == "error"] == []
