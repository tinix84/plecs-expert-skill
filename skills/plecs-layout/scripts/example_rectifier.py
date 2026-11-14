#!/usr/bin/env python3
"""Worked example: a three-phase diode rectifier drawn by the placer and router.

    python example_rectifier.py [-o rectifier.plecs]

Three 230 V / 50 Hz phases in star with the neutral grounded, series R and L and an
ammeter per phase, a six-diode bridge, a DC link (2 mF, 20 Ohm) with a voltmeter, a
phase-a voltmeter, a Vdc error chain (Vdc - 540 V, gain 0.1, limit +-1), and a scope.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from autolayout import Netlist  # noqa: E402

ZONES = ["source", "line", "bridge", "dclink", "measure", "control", "output"]


def rectifier() -> Netlist:
    nl = Netlist()
    for i, ph in enumerate("abc"):
        nl.part(f"V{ph}", "ACVoltageSource", {"V": "230*sqrt(2)", "w": "2*pi*50", "phi": f"{-i}*2*pi/3"}, zone="source")
        nl.part(f"R{ph}", "Resistor", {"R": "10e-3"}, zone="line")
        nl.part(f"L{ph}", "Inductor", {"L": "100e-6", "i_init": "0"}, zone="line")
        nl.part(f"Am{ph}", "Ammeter", zone="line")
        nl.part(f"D{ph}p", "Diode", {"Vf": "0", "Ron": "0"}, zone="bridge")   # upper diode
        nl.part(f"D{ph}n", "Diode", {"Vf": "0", "Ron": "0"}, zone="bridge")   # lower diode
        nl.net(f"{ph}1", "Wire", [(f"V{ph}", 1), (f"R{ph}", 1)])
        nl.net(f"{ph}2", "Wire", [(f"R{ph}", 2), (f"L{ph}", 1)])
        nl.net(f"{ph}3", "Wire", [(f"L{ph}", 2), (f"Am{ph}", 1)])
        pins = [(f"Am{ph}", 2), (f"D{ph}p", 1), (f"D{ph}n", 2)]
        if ph == "a":
            pins.append(("Van", 1))
        nl.net(f"p{ph}", "Wire", pins, tag="pa" if ph == "a" else None)
    nl.part("Gnd", "Ground", zone="source")
    nl.part("Cdc", "Capacitor", {"C": "2e-3", "v_init": "0"}, zone="dclink")
    nl.part("Rload", "Resistor", {"R": "20"}, zone="dclink")
    nl.part("Vdc", "Voltmeter", zone="dclink")
    nl.part("Van", "Voltmeter", zone="measure")
    nl.part("Ref", "Constant", {"Value": "540"}, zone="control")
    nl.part("Err", "Sum", {"IconShape": "2", "Inputs": "|+-"}, zone="control")
    nl.part("Kp", "Gain", {"K": "0.1"}, zone="control")
    nl.part("Lim", "Saturation", {"UpperLimit": "1", "LowerLimit": "-1"}, zone="control")
    nl.part("Kia", "Gain", {"K": "1"}, zone="control")
    nl.part("Mux", "SignalMux", {"Width": "3"}, zone="output")
    nl.part("Scope", "Scope", {"@Axes": "3"}, zone="output")
    nl.part("Out", "Output", {"Index": "1", "Width": "-1"}, zone="output")

    nl.net("neutral", "Wire", [("Va", 2), ("Vb", 2), ("Vc", 2), ("Van", 2), ("Gnd", 1)])
    nl.net("dcp", "Wire", [("Dap", 2), ("Dbp", 2), ("Dcp", 2), ("Cdc", 1), ("Rload", 1), ("Vdc", 1)], tag="dcp")
    nl.net("dcn", "Wire", [("Dan", 1), ("Dbn", 1), ("Dcn", 1), ("Cdc", 2), ("Rload", 2), ("Vdc", 2)], tag="dcn")
    nl.net("vdc", "Signal", [("Vdc", 3), ("Err", 2), ("Scope", 1), ("Out", 1)], tag="Vdc")
    nl.net("ref", "Signal", [("Ref", 1), ("Err", 3)])
    nl.net("err", "Signal", [("Err", 1), ("Kp", 1)])
    nl.net("u", "Signal", [("Kp", 2), ("Lim", 1)])
    nl.net("u_sat", "Signal", [("Lim", 2), ("Scope", 2)], tag="u_sat")
    nl.net("ia", "Signal", [("Ama", 3), ("Kia", 1), ("Mux", 2)], tag="ia")
    nl.net("ib", "Signal", [("Amb", 3), ("Mux", 3)], tag="ib")
    nl.net("ic", "Signal", [("Amc", 3), ("Mux", 4)], tag="ic")
    nl.net("iabc", "Signal", [("Mux", 1), ("Scope", 3)])
    return nl


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Draw the three-phase rectifier example.")
    ap.add_argument("-o", "--out", type=Path, default=Path("rectifier.plecs"))
    args = ap.parse_args(argv)
    sheet, report = rectifier().layout(zones=ZONES)
    args.out.write_text(sheet.model("rectifier", time_span="0.1", outputs=1), encoding="utf-8")
    print(args.out, report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
