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
