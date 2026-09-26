import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/plecs-layout/scripts"))
import layout  # noqa: E402
import plecs_file  # noqa: E402


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
