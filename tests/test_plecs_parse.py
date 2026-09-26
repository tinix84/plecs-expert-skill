import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/plecs-layout/scripts"))
import plecs_file  # noqa: E402

SAMPLE = r'''Plecs {
  Name          "demo"
  InitializationCommands "a = 1;\n"
"b = 2;"
  Schematic {
    Location      [0, 26; 800, 600]
    Component {
      Type          Resistor
      Name          "R1"
      Show          on
      Position      [100, 50]
      Direction     up
      Flipped       off
      Parameter {
        Variable      "R"
        Value         "1 {x}"
        Show          on
      }
    }
    Connection {
      Type          Wire
      SrcComponent  "R1"
      SrcTerminal   1
      Points        [100, 20; 200, 20]
      Branch {
        DstComponent  "C1"
        DstTerminal   1
      }
      Branch {
        Points        [200, 80]
        DstComponent  "L1"
        DstTerminal   2
      }
    }
  }
}
'''


def test_parse_nests_blocks_and_values():
    root = plecs_file.model(plecs_file.parse(SAMPLE))
    assert root.kind == "Plecs"
    assert root.get("Name") == "demo"
    assert root.get("InitializationCommands") == r"a = 1;\nb = 2;"
    sch = root.child("Schematic")
    comp = sch.child("Component")
    assert comp.get("Type") == "Resistor"
    assert comp.position == (100, 50)
    assert comp.child("Parameter").get("Value") == "1 {x}"


def test_connection_branches_and_points():
    conn = plecs_file.schematic(plecs_file.parse(SAMPLE)).child("Connection")
    assert plecs_file.points(conn) == [(100, 20), (200, 20)]
    branches = conn.children_of("Branch")
    assert [b.get("DstComponent") for b in branches] == ["C1", "L1"]
    assert plecs_file.points(branches[1]) == [(200, 80)]


def test_roundtrip_is_lossless():
    root = plecs_file.parse(SAMPLE)
    assert plecs_file.parse(plecs_file.dump(root)) == root


def test_trailing_root_field_and_order_are_kept():
    text = 'Plecs {\n  Name          "x"\n  Schematic {\n  }\n  Tail          1\n}\nDemoSignature "abc"\n'
    root = plecs_file.parse(text)
    assert plecs_file.model(root).get("Name") == "x"
    assert plecs_file.schematic(root) is not None
    assert plecs_file.dump(root) == text
