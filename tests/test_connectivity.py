import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/plecs-layout/scripts"))
import autolayout  # noqa: E402
import layout  # noqa: E402


def signal_net(*specs):
    netlist = autolayout.Netlist()
    for name in {part for net in specs for part, _ in net}:
        netlist.part(name, "Gain")
    for index, pins in enumerate(specs):
        netlist.net(f"n{index}", "Signal", pins)
    return netlist


def blank_sheet(*names):
    sheet = layout.Sheet()
    for name in names:
        sheet.add("Gain", name, (100 + len(sheet.names) * 50, 100))
    return sheet


def test_connectivity_rejects_signal_nets_with_reversed_driver():
    netlist = signal_net([("A", 2), ("B", 1)])
    sheet = blank_sheet("A", "B")
    sheet.signal(("B", 1), ("A", 2))

    findings = autolayout.check_connectivity(sheet.model("t"), netlist)

    assert any("signal source" in finding for finding in findings)


def test_connectivity_preserves_wire_and_signal_kinds():
    netlist = signal_net([("A", 2), ("B", 1)])
    sheet = blank_sheet("A", "B")
    sheet.wire(("A", 2), ("B", 1))

    findings = autolayout.check_connectivity(sheet.model("t"), netlist)

    assert any("split" in finding for finding in findings)


def test_connectivity_reports_accidentally_joined_nets():
    netlist = signal_net([("A", 2), ("B", 1)], [("C", 2), ("D", 1)])
    sheet = blank_sheet("A", "B", "C", "D")
    sheet.signal(("A", 2), [("B", 1), ("D", 1)])

    findings = autolayout.check_connectivity(sheet.model("t"), netlist)

    assert any("joined" in finding for finding in findings)


def test_connectivity_reports_duplicate_gotos_and_unresolved_froms():
    netlist = signal_net([("A", 2), ("B", 1)])
    sheet = blank_sheet("A", "B")
    sheet.goto("G1", "same", (300, 100))
    sheet.goto("G2", "same", (350, 100))
    sheet.from_("F", "missing", (400, 100))
    sheet.signal(("A", 2), ("G1", 1))
    sheet.signal(("F", 1), ("B", 1))

    findings = autolayout.check_connectivity(sheet.model("t"), netlist)

    assert any("duplicate signal drivers" in finding for finding in findings)
    assert any("unresolved From" in finding for finding in findings)


def hierarchy_model(visibility):
    return f'''Plecs {{
  Schematic {{
    Component {{
      Type Subsystem
      Name "ControlA"
      Position [100, 100]
      Schematic {{
        Component {{
          Type Goto
          Name "GA"
          Position [100, 100]
          Parameter {{
            Variable "Tag"
            Value "shared"
          }}
          Parameter {{
            Variable "Visibility"
            Value "{visibility}"
          }}
        }}
      }}
    }}
    Component {{
      Type Subsystem
      Name "ControlB"
      Position [400, 100]
      Schematic {{
        Component {{
          Type From
          Name "FB"
          Position [100, 100]
          Parameter {{
            Variable "Tag"
            Value "shared"
          }}
          Parameter {{
            Variable "Visibility"
            Value "{visibility}"
          }}
        }}
      }}
    }}
  }}
}}'''


def test_sheet_path_checks_connections_inside_nested_subsystem():
    text = '''Plecs {
  Schematic {
    Component {
      Type Subsystem
      Name "Control"
      Position [100, 100]
      Schematic {
        Component {
          Type Gain
          Name "A"
          Position [100, 100]
        }
        Component {
          Type Gain
          Name "B"
          Position [200, 100]
        }
        Connection {
          Type Signal
          SrcComponent "A"
          SrcTerminal 2
          DstComponent "B"
          DstTerminal 1
        }
      }
    }
  }
}'''
    netlist = signal_net([("A", 2), ("B", 1)])

    assert autolayout.check_connectivity(text, netlist, sheet_path="/Control") == []


def test_equal_local_tags_in_different_sheets_do_not_resolve_each_other():
    findings = autolayout.check_connectivity(hierarchy_model("2"), autolayout.Netlist(),
                                             sheet_path="/ControlA")

    assert any("tag 'shared'" in finding and "no receiver" in finding for finding in findings)


def test_global_tag_can_resolve_across_nested_sheets():
    findings = autolayout.check_connectivity(hierarchy_model("1"), autolayout.Netlist(),
                                             sheet_path="/ControlA")

    assert not any("tag 'shared'" in finding for finding in findings)
