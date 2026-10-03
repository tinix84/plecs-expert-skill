#!/usr/bin/env python3
"""Generate a small synthetic C-Script controller sheet.

Usage:
    python scripts/example_blockdiagram.py [-o controller.plecs]

The C-Script is a pass-through, so a unit input should produce a unit output.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blockdiagram  # noqa: E402
import plecs_file as pf  # noqa: E402
from autolayout import Netlist  # noqa: E402
from layout import Sheet  # noqa: E402


def _cscript_template(name="Controller", *, num_inputs="1", num_outputs="1",
                     output_fcn="OutputSignal(0, 0) = InputSignal(0, 0);"):
    params = {
        "NumInputs": num_inputs, "NumOutputs": num_outputs, "NumContStates": "0",
        "NumDiscStates": "0", "NumZCSignals": "0", "DirectFeedthrough": "1",
        "Ts": "0", "Parameters": "", "LangStandard": "2", "GnuExtensions": "1",
        "RuntimeCheck": "2", "Declarations": "", "StartFcn": "",
        "OutputFcn": output_fcn, "UpdateFcn": "",
        "DerivativeFcn": "", "TerminateFcn": "", "StoreCustomStateFcn": "",
        "RestoreCustomStateFcn": "",
    }
    template_sheet = Sheet()
    template_sheet.add("CScript", name, (100, 100), direction="up", params=params)
    return pf.schematic(pf.parse(template_sheet.model("template"))).children_of("Component")[0]


def _scope_template():
    template_sheet = Sheet()
    template_sheet.add("Scope", "View", (100, 100), params={"@Axes": "1"}, label="east")
    return pf.schematic(pf.parse(template_sheet.model("template"))).children_of("Component")[0]


def controller():
    """Return the generated PLECS Sheet and its score report."""
    netlist = Netlist()
    netlist.part("Ref", "Constant", {"Value": "1"}, zone="input")
    cscript_template = _cscript_template()
    cscript_params = {p.get("Variable"): p.get("Value")
                      for p in cscript_template.children_of("Parameter")}
    netlist.part("Controller", "CScript", cscript_params, zone="control",
                 component=cscript_template)
    netlist.part("Out", "Output", {"Index": "1", "Width": "-1"}, zone="output")
    netlist.part("View", "Scope", {"@Axes": "1"}, zone="output",
                 component=_scope_template())
    netlist.net("reference", "Signal", [("Ref", 1), ("Controller", 1)])
    netlist.net("controller_output", "Signal",
                [("Controller", 2), ("Out", 1), ("View", 1)])
    return blockdiagram.layout(netlist, zones=["input", "control", "output"])


def multiport_controller():
    """Return a two-channel synthetic controller for geometry and simulation checks."""
    template = _cscript_template(
        "M", num_inputs="[1 1]", num_outputs="[1 1]",
        output_fcn=("OutputSignal(0, 0) = InputSignal(0, 0); "
                    "OutputSignal(1, 0) = InputSignal(1, 0);"),
    )
    params = {p.get("Variable"): p.get("Value") for p in template.children_of("Parameter")}
    netlist = Netlist()
    netlist.part("A", "Constant", {"Value": "1"}, zone="lower", at=(100, 195))
    netlist.part("B", "Constant", {"Value": "2"}, zone="upper", at=(400, 205))
    netlist.part("M", "CScript", params, zone="control", component=template, at=(750, 200))
    netlist.part("X", "Output", {"Index": "1", "Width": "-1"}, zone="out-x", at=(1150, 195))
    netlist.part("Y", "Output", {"Index": "2", "Width": "-1"}, zone="out-y", at=(1400, 205))
    netlist.net("input_a", "Signal", [("A", 1), ("M", 1)])
    netlist.net("input_b", "Signal", [("B", 1), ("M", 2)])
    netlist.net("output_x", "Signal", [("M", 3), ("X", 1)])
    netlist.net("output_y", "Signal", [("M", 4), ("Y", 1)])
    return blockdiagram.layout(
        netlist, zones=["lower", "upper", "control", "out-x", "out-y"], max_wire=800
    )


def _subsystem_template(name, half_width, half_height, gain):
    """Build a small authored Subsystem using the measured PLECS interface record form."""
    component = f'''Component {{
  Type Subsystem
  Name "{name}"
  Show on
  Position [500, 200]
  Direction up
  Flipped off
  LabelPosition south
  Frame [-{half_width}, -{half_height}; {half_width}, {half_height}]
  TreatAsAtomicUnit on
  SampleTime "-1"
  Terminal {{
    Type Input
    Position [-{half_width}, 0]
    Direction left
    Index "1"
  }}
  Terminal {{
    Type Output
    Position [{half_width + 4}, 0]
    Direction right
    Index "1"
  }}
  Schematic {{
    Location [73, 647; 414, 920]
    ZoomFactor 1
    Component {{
      Type Input
      Name "In"
      Show on
      Position [60, 80]
      Direction right
      Flipped off
      LabelPosition south
      Parameter {{ Variable "Index" Value "1" Show on }}
      Parameter {{ Variable "DataType" Value "10" Show off }}
      Parameter {{ Variable "Width" Value "-1" Show off }}
    }}
    Component {{
      Type Output
      Name "Out"
      Show on
      Position [255, 80]
      Direction right
      Flipped off
      LabelPosition south
      Parameter {{ Variable "Index" Value "2" Show on }}
      Parameter {{ Variable "OutputWhenDisabled" Value "1" Show off }}
      Parameter {{ Variable "InitialOutput" Value "0" Show off }}
      Parameter {{ Variable "Width" Value "-1" Show off }}
    }}
    Component {{
      Type Gain
      Name "K"
      Show on
      Position [120, 80]
      Direction right
      Flipped off
      LabelPosition south
      Parameter {{ Variable "K" Value "{gain}" Show off }}
    }}
    Connection {{
      Type Signal
      SrcComponent "In"
      SrcTerminal 1
      DstComponent "K"
      DstTerminal 1
    }}
    Connection {{
      Type Signal
      SrcComponent "K"
      SrcTerminal 2
      DstComponent "Out"
      DstTerminal 1
    }}
  }}
}}'''
    return pf.parse(component).children[0]


def unequal_subsystem_controller():
    """Return a two-Subsystem chain for measured geometry and PLECS simulation checks."""
    netlist = Netlist()
    netlist.part("Reference", "Constant", {"Value": "1"}, zone="source")
    netlist.part("Small", "Subsystem", zone="control",
                 component=_subsystem_template("Small", 25, 15, 2))
    netlist.part("Large", "Subsystem", zone="control",
                 component=_subsystem_template("Large", 50, 40, 3))
    netlist.part("Result", "Output", {"Index": "1", "Width": "-1"}, zone="output")
    netlist.net("reference", "Signal", [("Reference", 1), ("Small", 1)])
    netlist.net("between", "Signal", [("Small", 2), ("Large", 1)])
    netlist.net("result", "Signal", [("Large", 2), ("Result", 1)])
    return blockdiagram.layout(netlist, zones=["source", "control", "output"])


def feedback_controller():
    """Return a first-order closed-loop controller for feedback simulation checks."""
    sum_sheet = Sheet()
    sum_sheet.add("Sum", "Error", (100, 100), direction="right",
                  params={"Inputs": "|+-", "IconShape": "2"}, show_name=False)
    sum_template = pf.schematic(pf.parse(sum_sheet.model("template"))).children_of("Component")[0]

    netlist = Netlist()
    netlist.part("Reference", "Constant", {"Value": "1"}, zone="source")
    netlist.part("Error", "Sum", {"Inputs": "|+-", "IconShape": "2"}, zone="control",
                 component=sum_template)
    netlist.part("Gain", "Gain", {"K": "1"}, zone="control")
    netlist.part("State", "Integrator", zone="control")
    netlist.part("Result", "Output", {"Index": "1", "Width": "-1"}, zone="output")
    netlist.net("reference", "Signal", [("Reference", 1), ("Error", 2)])
    netlist.net("error", "Signal", [("Error", 1), ("Gain", 1)])
    netlist.net("derivative", "Signal", [("Gain", 2), ("State", 1)])
    netlist.net("feedback", "Signal", [("State", 2), ("Error", 3), ("Result", 1)])
    return blockdiagram.layout(netlist, zones=["source", "control", "output"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--out", type=Path, default=Path("controller.plecs"))
    args = parser.parse_args(argv)
    sheet, report = controller()
    model = sheet.model("synthetic_controller", time_span="1e-3", outputs=1)
    args.out.write_text(model, encoding="utf-8")
    preview = args.out.with_suffix(".svg")
    import preview as preview_module
    schematic = pf.schematic(pf.parse(model))
    preview.write_text(preview_module.render(schematic), encoding="utf-8")
    print(f"{args.out} | accepted={report['accepted']} | quality={report['quality']['weighted_total']} | {preview}")
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
