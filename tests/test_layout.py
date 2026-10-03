import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/plecs-layout/scripts"))
import layout  # noqa: E402
import plecs_file  # noqa: E402
import autolayout  # noqa: E402


SUBSYSTEM_MODEL = r'''Plecs {
  Schematic {
    Component {
      Type          Subsystem
      Name          "Ctrl"
      Show          on
      Position      [100, 200]
      Direction     right
      Flipped       off
      Frame         [-25, -15; 25, 15]
      Terminal {
        Type          Input
        Position      [-25, 0]
        Direction     left
        Index         "1"
      }
      Terminal {
        Type          Output
        Position      [29, 0]
        Direction     right
        Index         "1"
      }
      Schematic {
        Location      [0, 26; 400, 300]
        Component {
          Type          CScript
          Name          "Code"
          Position      [80, 90]
          Direction     up
          Flipped       off
          Parameter {
            Variable      "NumInputs"
            Value         "[1 1]"
            Show          off
          }
        }
      }
    }
  }
}
'''


CSCRIPT_MODEL = r'''Plecs {
  Schematic {
    Component {
      Type          CScript
      Name          "Controller"
      Show          on
      Position      [100, 200]
      Direction     up
      Flipped       off
      Parameter {
        Variable      "NumInputs"
        Value         "1"
        Show          off
      }
      Parameter {
        Variable      "NumOutputs"
        Value         "1"
        Show          off
      }
      Parameter {
        Variable      "DirectFeedthrough"
        Value         "1"
        Show          off
      }
      Parameter {
        Variable      "OutputFcn"
        Value         "OutputSignal(0, 0) = InputSignal(0, 0);"
        Show          off
      }
    }
  }
}
'''


def parsed_component(model_text):
    return plecs_file.schematic(plecs_file.parse(model_text)).children_of("Component")[0]


def small_sheet():
    sh = layout.Sheet()
    z = layout.Zone(x=100, y=100, dx=60, dy=60)
    sh.add("Constant", "Ref", z.at(0, 0), params={"Value": "540"})
    sh.add("Gain", "K", z.at(2, 0), params={"K": "0.1"})
    sh.goto("G_err", tag="err", at=z.at(4, 0))
    sh.from_("F_err", tag="err", at=z.at(0, 2))
    sh.add("Scope", "Scope", z.at(3, 3))
    sh.signal(("Ref", 1), ("K", 1))
    sh.signal(("K", 2), ("G_err", 1))
    sh.signal(("F_err", 1), ("Scope", 1), via=[(210, 220), (210, 280)])
    return sh


def test_generated_model_parses_and_lints_clean():
    sh = small_sheet()
    root = plecs_file.parse(sh.model("t", init="a = 1;"))
    assert plecs_file.model(root).get("InitializationCommands") == "a = 1;"
    assert len(plecs_file.schematic(root).children_of("Component")) == 5
    assert [f for f in sh.lint() if f.severity == "error"] == []


def test_positions_snap_to_grid():
    sh = layout.Sheet()
    sh.add("Gain", "K", (101, 98))
    assert "Position      [100, 100]" in sh.schematic()


def test_top_level_parameters_are_preserved():
    sh = layout.Sheet()
    sh.add("Scope", "Scope", (100, 100), params={"@Axes": "2"})
    component = parsed_component(sh.model("scope"))
    assert component.get("Axes") == "2"
    assert component.param("@Axes") is None


def test_diagonal_via_is_rejected():
    sh = small_sheet()
    with pytest.raises(ValueError):
        sh.signal(("Ref", 1), ("K", 1), via=[(100, 100), (200, 200)])


def test_duplicate_name_is_rejected():
    sh = small_sheet()
    with pytest.raises(ValueError):
        sh.add("Gain", "K", (500, 500))


def test_tags_default_to_this_schematic_only():
    assert '"Visibility"\n        Value         "2"' in small_sheet().schematic()


def test_diagonal_branch_from_junction_is_rejected():
    sh = small_sheet()
    with pytest.raises(ValueError):
        sh.signal(("K", 2), [("Scope", 1), ("G_err", 1, [(260, 160)])], via=[(220, 100)])


def test_model_declares_output_ports():
    assert sh_text().count("Type          Output") == 2


def sh_text():
    return small_sheet().model("t", outputs=2)


def test_add_component_preserves_nested_content_when_layout_fields_change():
    template = parsed_component(SUBSYSTEM_MODEL)
    sheet = layout.Sheet()

    sheet.add_component(template, at=(205, 305), direction="up", flipped=True)
    result = parsed_component(sheet.model("t"))

    assert result.position == (205, 305)
    assert result.get("Direction") == "up"
    assert result.get("Flipped") == "on"
    assert result.get("Frame") == "[-25, -15; 25, 15]"
    assert [(term.get("Type"), term.get("Position"))
            for term in result.children_of("Terminal")] == [
        ("Input", "[-25, 0]"),
        ("Output", "[29, 0]"),
    ]
    assert template.position == (100, 200)
    nested = result.child("Schematic")
    assert nested.get("Location") == "[0, 26; 400, 300]"
    assert nested.children_of("Component")[0].get("Name") == "Code"
    assert nested.children_of("Component")[0].param("NumInputs") == "[1 1]"


def test_netlist_part_round_trips_cscript_parameters_and_checks_template():
    template = parsed_component(CSCRIPT_MODEL)
    netlist = autolayout.Netlist()
    part = netlist.part("Controller", "CScript", component=template)

    assert part.params["NumInputs"] == "1"
    assert part.params["NumOutputs"] == "1"
    assert part.params["DirectFeedthrough"] == "1"
    sheet, _ = netlist.layout()
    result = parsed_component(sheet.model("t"))
    assert result.param("OutputFcn") == "OutputSignal(0, 0) = InputSignal(0, 0);"
    assert result.param("DirectFeedthrough") == "1"
    assert result.param("NumInputs") == "1"
    assert result.param("NumOutputs") == "1"
    assert template.position == (100, 200)

    with pytest.raises(ValueError, match="does not match"):
        netlist.part("Other", "CScript", component=template)
    with pytest.raises(ValueError, match="parameters differ"):
        netlist.part("Controller", "CScript", {"NumInputs": "1"}, component=template)
