"""Integration tests against a running PLECS (XML-RPC on localhost:1080). Skipped when PLECS is not running."""
import socket
import sys
import xmlrpc.client
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/plecs-layout/scripts"))
from layout import GLOBAL, LOCAL, Sheet, Zone  # noqa: E402

URL = "http://localhost:1080/RPC2"


def _rpc():
    socket.setdefaulttimeout(120)
    rpc = xmlrpc.client.ServerProxy(URL)
    try:
        rpc.system.listMethods()
    except OSError:
        pytest.skip("PLECS XML-RPC is not running on localhost:1080")
    return rpc


def rc_with_tags(visibility_goto=LOCAL, visibility_from=LOCAL):
    """RC charge circuit whose voltmeter reaches the node only through an electrical Label,
    and whose reading reaches the gain only through a Goto/From pair."""
    sh = Sheet()
    pwr = Zone(x=100, y=100, dx=80, dy=60)
    sh.add("DCVoltageSource", "Vin", pwr.at(0, 1), direction="down", flipped=True, params={"V": "10"})
    sh.add("Resistor", "R1", pwr.at(1, 0), params={"R": "1"})
    sh.add("Capacitor", "C1", pwr.at(2, 1), direction="down", flipped=True, params={"C": "1e-3", "v_init": "0"})
    sh.label("Lvc_a", tag="vc", at=pwr.at(3, 0))
    sh.add("Ground", "Gnd", pwr.at(1, 3))
    meas = Zone(x=100, y=400, dx=80, dy=60)
    sh.label("Lvc_b", tag="vc", at=meas.at(0, 0))
    sh.add("Voltmeter", "Vm", meas.at(1, 1), direction="up")
    sh.add("Ground", "Gnd2", meas.at(1, 3))
    sh.goto("Gvc", tag="Vc", at=meas.at(3, 1), visibility=visibility_goto)
    ctl = Zone(x=500, y=100, dx=80, dy=60)
    sh.from_("Fvc", tag="Vc", at=ctl.at(0, 0), visibility=visibility_from)
    sh.add("Gain", "K", ctl.at(1, 0), params={"K": "0.1"})
    sh.add("Output", "Out", ctl.at(3, 0), params={"Index": "1", "Width": "-1"})
    sh.wire(("Vin", 1), ("R1", 1), via=[(100, 100)])
    sh.wire(("R1", 2), [("C1", 1, [(260, 100)]), ("Lvc_a", 1, [(340, 100)])], via=[(260, 100)])
    sh.wire(("Vin", 2), [("C1", 2, [(260, 280)]), ("Gnd", 1)], via=[(100, 280), (180, 280)])
    sh.wire(("Lvc_b", 1), ("Vm", 1), via=[(180, 400)])
    sh.wire(("Vm", 2), ("Gnd2", 1))
    sh.signal(("Vm", 3), ("Gvc", 1), via=[(340, 460)])
    sh.signal(("Fvc", 1), ("K", 1))
    sh.signal(("K", 2), ("Out", 1))
    return sh


def _simulate(rpc, sh, name, tmp_path):
    path = tmp_path / f"{name}.plecs"
    path.write_text(sh.model(name, time_span="0.05", outputs=1), encoding="utf-8")
    try:
        rpc.plecs.close(name)
    except xmlrpc.client.Fault:
        pass
    rpc.plecs.load(str(path))
    try:
        return rpc.plecs.simulate(name)
    finally:
        rpc.plecs.close(name)


def test_label_and_tags_carry_the_signal(tmp_path):
    rpc = _rpc()
    sh = rc_with_tags()
    assert [f for f in sh.lint() if f.severity == "error"] == []
    result = _simulate(rpc, sh, "it_tags_local", tmp_path)
    # RC time constant 1 ms, so after 50 ms Vc = 10 V and the gain output is 1.0.
    assert result["Values"][0][-1] == pytest.approx(1.0, abs=1e-6)


def test_global_tags_work_too(tmp_path):
    rpc = _rpc()
    result = _simulate(rpc, rc_with_tags(GLOBAL, GLOBAL), "it_tags_global", tmp_path)
    assert result["Values"][0][-1] == pytest.approx(1.0, abs=1e-6)
