import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/plecs-layout/scripts"))
import autolayout  # noqa: E402
import geometry  # noqa: E402
import lint_schematic  # noqa: E402
import plecs_file  # noqa: E402
import preview  # noqa: E402


@pytest.mark.parametrize(
    ("params", "terminals"),
    [
        ({"NumInputs": "1", "NumOutputs": "1"}, {"1": (100, 165), "2": (100, 235)}),
        (
            {"NumInputs": "[1 1]", "NumOutputs": "[1 1]"},
            {"1": (105, 165), "2": (95, 165), "3": (105, 235), "4": (95, 235)},
        ),
    ],
)
def test_cscript_calibrated_variant_has_terminals(params, terminals):
    shape = geometry.shape("CScript", (100, 200), "right", False, params)

    assert shape.measured
    assert shape.terminals == terminals


def test_known_kind_unknown_variant_is_unmeasured():
    params = {"@Axes": "99"}
    shape = geometry.shape("Scope", (100, 200), params=params)
    assert not shape.measured

    netlist = autolayout.Netlist()
    netlist.part("scope99", "Scope", params, zone="control")
    _, report = netlist.layout(zones=["control"])

    assert report["unmeasured"] == ["Scope"]
    assert report["geometry_coverage"] == [
        {
            "component": "scope99",
            "kind": "Scope",
            "variant": "99in",
            "direction": "right",
            "flip": False,
            "reason": "variant '99in' is not calibrated",
        }
    ]


def test_cscript_scalar_width_and_vector_port_count_are_distinct():
    scalar = {"NumInputs": "7", "NumOutputs": "1"}
    vector = {"NumInputs": "[1 1 1]", "NumOutputs": "1"}

    assert geometry.variant_of("CScript", scalar) == "1in1out"
    assert geometry.shape("CScript", (100, 200), params=scalar).measured
    assert geometry.variant_of("CScript", vector) == "3in1out"
    assert not geometry.shape("CScript", (100, 200), params=vector).measured


def test_cscript_zero_ports_are_explicitly_unmeasured():
    params = {"NumInputs": "0", "NumOutputs": "1"}

    assert geometry.variant_of("CScript", params) == "0in1out"
    assert not geometry.shape("CScript", (100, 200), params=params).measured


def test_cscript_parameter_expressions_are_reported_as_unresolved():
    params = {"NumInputs": "input_count", "NumOutputs": "1"}

    assert not geometry.shape("CScript", (100, 200), params=params).measured
    issue = geometry.coverage_issue("CScript", params)
    assert issue["reason"] == "C-Script port parameters must be literal widths or vectors"


def test_component_shape_uses_parsed_component_parameters():
    component = plecs_file.parse('''Component {
  Type CScript
  Name "Controller"
  Position [100, 200]
  Direction up
  Parameter {
    Variable "NumInputs"
    Value "1"
  }
  Parameter {
    Variable "NumOutputs"
    Value "1"
  }
}''').children[0]

    resolved = geometry.component_shape(component)

    assert resolved.measured
    assert resolved.terminals == geometry.shape(
        "CScript", (100, 200), "up", params={"NumInputs": "1", "NumOutputs": "1"}
    ).terminals


def test_component_shape_reads_top_level_scope_axes():
    component = plecs_file.parse('''Component {
  Type Scope
  Name "View"
  Position [100, 200]
  Direction right
  Axes "2"
}''').children[0]

    assert geometry.component_params(component) == {"@Axes": "2"}
    assert geometry.component_shape(component).measured


def test_subsystem_shape_uses_serialized_frame_and_ordered_terminal_positions():
    component = plecs_file.parse('''Component {
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
    Position [29, 0]
    Direction right
    Index "1"
  }
  Terminal {
    Type Input
    Position [0, -15]
    Direction up
    Index "2"
  }
  Schematic {
    Component {
      Type Gain
      Name "NestedGain"
      Position [80, 90]
    }
  }
}''').children[0]

    resolved = geometry.component_shape(component)

    assert resolved.measured
    assert resolved.box == (75, 185, 125, 215)
    assert resolved.terminals == {
        "1": (75, 200),
        "2": (129, 200),
        "3": (100, 185),
    }
    assert geometry.component_coverage_issue(component) is None
    assert lint_schematic._shape(component) == resolved
    svg = preview.render(plecs_file.schematic(plecs_file.parse(
        f"Plecs {{\n  Schematic {{\n{plecs_file.dump(component)}  }}\n}}"
    )))
    assert '<rect x="75.0" y="185.0" width="50.0" height="30.0"' in svg
    assert '<circle cx="75.0" cy="200.0"' in svg


def test_subsystem_shape_requires_frame_and_terminal_records():
    component = plecs_file.parse('''Component {
  Type Subsystem
  Name "Unknown"
  Position [0, 0]
  Direction up
  Terminal {
    Type Input
    Direction left
  }
}''').children[0]

    resolved = geometry.component_shape(component)

    assert not resolved.measured
    assert resolved.terminals == {}
    assert "Frame" in geometry.component_coverage_issue(component)["reason"]


def test_subsystem_shape_rejects_unverified_orientation():
    component = plecs_file.parse('''Component {
  Type Subsystem
  Name "Rotated"
  Position [0, 0]
  Direction right
  Flipped off
  Frame [-25, -15; 25, 15]
  Terminal {
    Type Input
    Position [-25, 0]
    Direction left
  }
}''').children[0]

    assert not geometry.component_shape(component).measured
    assert geometry.component_coverage_issue(component)["reason"] == (
        "Subsystem geometry is verified only for Direction up, Flipped off"
    )
