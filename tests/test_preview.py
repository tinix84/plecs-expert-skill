import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/plecs-layout/scripts"))
import layout  # noqa: E402
import plecs_file  # noqa: E402
import preview  # noqa: E402


def test_preview_shows_reserved_displayed_text_and_hides_disabled_names():
    sheet = layout.Sheet()
    sheet.add("Gain", "Visible controller", (100, 100))
    sheet.add("Gain", "Hidden controller", (300, 100), show_name=False)
    sheet.goto("Goto", "feedback_signal", (200, 200))
    sch = plecs_file.schematic(plecs_file.parse(sheet.model("preview")))

    svg = preview.render(sch)

    assert "Visible controller" in svg
    assert "Hidden controller" not in svg
    assert "feedback_signal" in svg
    assert 'stroke="#d80"' in svg
