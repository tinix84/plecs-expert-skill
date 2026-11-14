import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/plecs-layout/scripts"))
import autolayout  # noqa: E402
import blockdiagram  # noqa: E402
import layout  # noqa: E402
import score  # noqa: E402


def pair():
    nl = autolayout.Netlist()
    nl.part("Ref", "Constant", {"Value": "1"})
    nl.part("A", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    nl.part("B", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    nl.net("ref", "Signal", [("Ref", 1), ("A", 1)])
    nl.net("ab", "Signal", [("A", 2), ("B", 1)])
    sheet, report = blockdiagram.layout(nl, max_wire=200)
    return nl, sheet, report


def test_generated_clear_pair_has_zero_score_and_passes_all_correctness_gates():
    nl, sheet, report = pair()

    result = score.score(sheet.model("controller"), nl, max_wire=200, layout_report=report)

    assert result["weighted_total"] == 0
    assert result["accepted"]
    assert result["connectivity"]["equivalent"]
    assert result["coverage"]["supported_geometry"]


def test_unknown_geometry_prevents_acceptance_even_when_score_is_zero():
    nl = autolayout.Netlist()
    nl.part("Mystery", "UnknownBlock")
    sheet = layout.Sheet()
    sheet.add("UnknownBlock", "Mystery", (100, 100))

    result = score.score(sheet.model("unknown"), nl)

    assert result["coverage"]["supported_geometry"] is False
    assert result["coverage"]["unsupported"][0]["component"] == "Mystery"
    assert result["accepted"] is False


def test_unconnected_inputs_have_a_separate_weighted_item():
    nl = autolayout.Netlist()
    nl.part("Controller", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    sheet = layout.Sheet()
    sheet.add("CScript", "Controller", (100, 100), direction="up",
              params={"NumInputs": "1", "NumOutputs": "1"})

    result = score.score(sheet.model("unconnected"), nl)

    assert result["counts"]["unconnected_inputs"] == 1
    assert result["weighted_total"] == 5
    assert result["accepted"] is False


def test_connectivity_fault_uses_the_correctness_weight():
    nl, sheet, _ = pair()
    broken = sheet.model("controller").replace('DstComponent  "B"', 'DstComponent  "A"')

    result = score.score(broken, nl, max_wire=200)

    assert result["counts"]["connectivity"] > 0
    assert result["weighted_total"] >= 100
    assert result["accepted"] is False


def test_tag_and_wire_length_are_reported_separately_from_correctness():
    nl = autolayout.Netlist()
    nl.part("A", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    nl.part("B", "CScript", {"NumInputs": "1", "NumOutputs": "1"})
    nl.net("ab", "Signal", [("A", 2), ("B", 1)])
    sheet, report = blockdiagram.layout(nl, max_wire=0)

    result = score.score(sheet.model("tagged"), nl, max_wire=0, layout_report=report)

    assert result["metrics"]["tag_count"] == 2
    assert result["metrics"]["wire_length"] == 40
    assert result["counts"]["non_straight"] == 0
    assert result["connectivity"]["equivalent"]


def two_block_net(source_at=(100, 100), sink_at=(400, 100), direction="right"):
    nl = autolayout.Netlist()
    nl.part("Source", "Constant", {"Value": "1"})
    nl.part("Sink", "Gain", {"K": "2"})
    nl.net("n", "Signal", [("Source", 1), ("Sink", 1)])
    sheet = layout.Sheet()
    sheet.add("Constant", "Source", source_at, direction=direction)
    sheet.add("Gain", "Sink", sink_at, direction=direction)
    return nl, sheet


def test_overlap_is_a_weight_100_lint_error():
    nl = autolayout.Netlist()
    nl.part("A", "Gain")
    nl.part("B", "Gain")
    sheet = layout.Sheet()
    sheet.add("Gain", "A", (100, 100))
    sheet.add("Gain", "B", (100, 100))

    result = score.score(sheet.model("overlap"), nl)

    assert result["counts"]["lint_errors"] > 0
    assert result["weighted_total"] >= 100
    assert not result["accepted"]


def test_nonstraight_leg_is_counted_independently():
    nl, sheet = two_block_net(source_at=(100, 100), sink_at=(300, 300))
    sheet.signal(("Source", 1), ("Sink", 1))

    result = score.score(sheet.model("diagonal"), nl)

    assert result["counts"]["non_straight"] > 0
    assert not result["accepted"]


def test_orthogonal_bends_are_controller_policy_violations():
    nl, sheet = two_block_net(source_at=(100, 100), sink_at=(400, 100))
    sheet.signal(("Source", 1), ("Sink", 1), via=[(150, 100), (150, 200), (350, 200)])

    result = score.score(sheet.model("bent"), nl, max_wire=500)

    assert result["metrics"]["bends"] >= 2
    assert result["counts"]["non_straight"] > 0
    assert not result["accepted"]


def test_overlength_direct_wire_is_counted():
    nl, sheet = two_block_net()
    sheet.signal(("Source", 1), ("Sink", 1))

    result = score.score(sheet.model("long"), nl, max_wire=100)

    assert result["counts"]["overlength_wires"] == 1
    assert not result["accepted"]


def test_zero_max_wire_rejects_a_direct_terminal_connection():
    nl, sheet = two_block_net(source_at=(100, 100), sink_at=(200, 100))
    sheet.signal(("Source", 1), ("Sink", 1))

    result = score.score(sheet.model("untagged"), nl, max_wire=0)

    assert result["counts"]["missing_tags"] == 1
    assert not result["accepted"]


def test_undeclared_tag_alias_cannot_bypass_tag_stub_validation():
    nl = autolayout.Netlist()
    nl.part("Source", "Constant", {"Value": "1"})
    nl.part("Sink", "Output", {"Index": "1"})
    nl.net("n", "Signal", [("Source", 1), ("Sink", 1)])
    sheet = layout.Sheet()
    sheet.add("Constant", "Source", (100, 100))
    sheet.add("Output", "Sink", (500, 100))
    sheet.goto("G", "alias", (300, 100))
    sheet.from_("F", "alias", (400, 100))
    sheet.signal(("Source", 1), ("G", 1))
    sheet.signal(("F", 1), ("Sink", 1))

    result = score.score(sheet.model("alias"), nl, max_wire=0)

    assert result["connectivity"]["equivalent"]
    assert result["counts"]["non_straight"] > 0
    assert not result["accepted"]


def test_declared_tag_alias_does_not_reject_generated_controller_layout():
    nl = autolayout.Netlist()
    nl.part("A", "Constant", {"Value": "1"})
    nl.part("B", "Output", {"Index": "1"})
    nl.net("n", "Signal", [("A", 1), ("B", 1)], tag="alias")

    sheet, report = blockdiagram.layout(nl, max_wire=0)

    assert report["quality"]["accepted"]
    assert report["quality"]["counts"]["non_straight"] == 0
    assert report["connectivity"] == []


def test_crossing_wires_are_counted_as_an_aesthetic_failure():
    nl = autolayout.Netlist()
    for name, kind in (("HS", "Constant"), ("HT", "Gain"), ("VS", "Constant"), ("VT", "Gain")):
        nl.part(name, kind)
    nl.net("horizontal", "Signal", [("HS", 1), ("HT", 1)])
    nl.net("vertical", "Signal", [("VS", 1), ("VT", 1)])
    sheet = layout.Sheet()
    sheet.add("Constant", "HS", (100, 200))
    sheet.add("Gain", "HT", (300, 200))
    sheet.add("Constant", "VS", (200, 100), direction="down")
    sheet.add("Gain", "VT", (200, 300), direction="down")
    sheet.signal(("HS", 1), ("HT", 1))
    sheet.signal(("VS", 1), ("VT", 1))

    result = score.score(sheet.model("crossing"), nl, max_wire=500)

    assert result["counts"]["crossings"] == 1
    assert result["metrics"]["crossings"] == 1
    assert not result["accepted"]


def test_bends_area_and_optional_displacement_are_reported():
    nl, sheet = two_block_net(source_at=(100, 100), sink_at=(300, 100))
    sheet.signal(("Source", 1), ("Sink", 1), via=[(115, 200), (280, 200)])
    previous = {"Source": (95, 100), "Sink": (300, 100)}

    result = score.score(sheet.model("bent"), nl, max_wire=500, previous_positions=previous)

    assert result["metrics"]["bends"] == 2
    assert result["metrics"]["occupied_area"] > 0
    assert result["metrics"]["displacement"] == {"Source": 5, "Sink": 0}


def test_unrouted_output_fails_acceptance_independently():
    nl, sheet, report = pair()
    report["unrouted"] = [["A", "B"]]

    result = score.score(sheet.model("unrouted"), nl, max_wire=200, layout_report=report)

    assert result["weighted_total"] > 0
    assert result["unrouted"]
    assert not result["accepted"]
