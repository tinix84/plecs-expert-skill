import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/plecs-layout/scripts"))
import lint_schematic as lint  # noqa: E402
import geometry  # noqa: E402


def comp(kind, name, pos, params=None, direction="right", show="on", show_params=False):
    ps = "".join(
        f'      Parameter {{\n        Variable      "{k}"\n        Value         "{v}"\n'
        f'        Show          {"on" if show_params else "off"}\n      }}\n'
        for k, v in (params or {}).items()
    )
    return (
        f"    Component {{\n      Type          {kind}\n      Name          \"{name}\"\n"
        f"      Show          {show}\n      Position      [{pos[0]}, {pos[1]}]\n"
        f"      Direction     {direction}\n      Flipped       off\n{ps}    }}\n"
    )


def conn(src, st, dst, dt, points=None, kind="Signal"):
    p = f"      Points        [{'; '.join(f'{x}, {y}' for x, y in points)}]\n" if points else ""
    return (
        f"    Connection {{\n      Type          {kind}\n      SrcComponent  \"{src}\"\n"
        f"      SrcTerminal   {st}\n{p}      DstComponent  \"{dst}\"\n      DstTerminal   {dt}\n    }}\n"
    )


def model(*parts):
    return 'Plecs {\n  Name          "t"\n  Schematic {\n' + "".join(parts) + "  }\n}\n"


def codes(text):
    return sorted(f.code for f in lint.lint_text(text))


def test_clean_model_has_no_findings():
    text = model(
        comp("Constant", "K", (100, 100)),
        comp("Goto", "G", (160, 100), {"Tag": "ref", "Visibility": "1"}),
        comp("From", "F", (100, 200), {"Tag": "ref", "Visibility": "1"}),
        comp("Gain", "A", (160, 200)),
        conn("K", 1, "G", 1),
        conn("F", 1, "A", 1),
    )
    assert codes(text) == []


def test_off_grid_position_and_point():
    text = model(comp("Gain", "A", (101, 100)), comp("Gain", "B", (300, 100)),
                 conn("A", 2, "B", 1, points=[(200, 103)]))
    assert codes(text).count("grid") == 2


def test_diagonal_segment_between_points():
    text = model(comp("Gain", "A", (100, 100)), comp("Gain", "B", (300, 300)),
                 conn("A", 2, "B", 1, points=[(200, 100), (250, 300)]))
    assert "diagonal" in codes(text)


def test_orphan_from_and_unused_goto():
    text = model(
        comp("Goto", "G", (100, 100), {"Tag": "a", "Visibility": "1"}),
        comp("From", "F", (100, 200), {"Tag": "b", "Visibility": "1"}),
    )
    assert codes(text) == ["tag-orphan-from", "tag-unused-goto"]


def test_duplicate_goto_tag():
    text = model(
        comp("Goto", "G1", (100, 100), {"Tag": "a", "Visibility": "1"}),
        comp("Goto", "G2", (100, 200), {"Tag": "a", "Visibility": "1"}),
        comp("From", "F", (100, 300), {"Tag": "a", "Visibility": "1"}),
    )
    assert codes(text) == ["tag-duplicate-goto"]


def test_overlapping_components_use_measured_boxes():
    text = model(comp("Gain", "A", (100, 100)), comp("Gain", "B", (120, 100)))
    assert "overlap" in codes(text)


def test_rotated_measured_boxes_overlap(monkeypatch):
    monkeypatch.setattr(geometry, "_TABLE", {
        "Asymmetric": {"": {
            "up/off": {"box": [-5, -30, 5, 30], "terminals": {"1": [0, -30], "2": [0, 30]}},
            "right/off": {"box": [-30, -5, 30, 5], "terminals": {"1": [-30, 0], "2": [30, 0]}},
        }}
    })
    text = model(comp("Asymmetric", "Tall", (100, 100), direction="up"),
                 comp("Asymmetric", "Wide", (120, 120), direction="right"))

    assert "overlap" in codes(text)


def test_touching_measured_box_edges_are_not_overlap(monkeypatch):
    monkeypatch.setattr(geometry, "_TABLE", {
        "Box": {"": {"right/off": {"box": [-5, -5, 5, 5], "terminals": {}}}}
    })
    text = model(comp("Box", "A", (100, 100)), comp("Box", "B", (110, 100)))

    assert "overlap" not in codes(text)


def test_long_displayed_names_collide_even_when_bodies_do_not():
    text = model(comp("Gain", "Controller long name A", (100, 100)),
                 comp("Gain", "Controller long name B", (250, 100)))

    assert "text-overlap" in codes(text)
    assert "overlap" not in codes(text)


def test_wire_crossing_displayed_text_is_reported():
    parts = [comp("Constant", "Source", (100, 100), show="off"),
             comp("Output", "Sink", (400, 100), show="off"),
             comp("Constant", "Foreign label", (250, 130))]
    component_model = model(*parts)
    schematic = lint.pf.schematic(lint.pf.parse(component_model))
    foreign = next(c for c in schematic.children_of("Component")
                   if c.get("Name") == "Foreign label")
    record = lint.text_envelopes(foreign)[0][0]
    x0, _, x1, _ = record["box"]
    y = record["center"][1]
    wire = conn("Source", 1, "Sink", 1, points=[(x0 - 10, y), (x1 + 10, y)])

    findings = lint.lint_text(model(*parts, wire))

    assert any(f.code == "wire-through-text" and "Foreign label" in f.message
               for f in findings)


def test_hidden_component_names_do_not_reserve_text_space():
    text = model(comp("Gain", "Controller long name A", (100, 100), show="off"),
                 comp("Gain", "Controller long name B", (250, 100), show="off"))

    assert "text-overlap" not in codes(text)


def test_unsupported_shown_parameter_text_is_reported():
    text = model(comp("Gain", "A", (100, 100), {"K": "{controller_value}"}, show_params=True))

    assert "text-coverage" in codes(text)


def test_long_connection_without_points_is_unrouted():
    text = model(comp("Gain", "A", (100, 100)), comp("Gain", "B", (300, 300)), conn("A", 2, "B", 1))
    assert codes(text) == ["unrouted"]


def test_terminal_leg_may_bend_implicitly():
    text = model(comp("Gain", "A", (100, 100)), comp("Gain", "B", (300, 300)),
                 conn("A", 2, "B", 1, points=[(200, 100), (200, 300)]))
    assert codes(text) == []


def test_wire_through_foreign_component():
    text = model(comp("Gain", "A", (100, 100)), comp("Gain", "B", (300, 100)), comp("Gain", "C", (200, 100)),
                 conn("A", 2, "B", 1, points=[(150, 100), (250, 100)]))
    assert "wire-through-component" in codes(text)


def test_terminal_to_point_leg_avoids_foreign_component():
    text = model(comp("Gain", "A", (100, 100)), comp("Gain", "B", (300, 100)),
                 comp("Gain", "C", (150, 100)), conn("A", 2, "B", 1, points=[(180, 100)]))

    assert "wire-through-component" in codes(text)


def test_wire_over_a_measured_terminal(monkeypatch):
    import geometry
    box = {"box": [-15, -10, 15, 10], "terminals": {"1": [-15, 0], "2": [15, 0]}}
    monkeypatch.setattr(geometry, "_TABLE", {"Gain": {"": {"right/off": box}}})
    # C sits below the wire; its terminal 1 at (185, 100) lies exactly on the wire.
    text = model(comp("Gain", "A", (100, 100)), comp("Gain", "B", (300, 100)), comp("Gain", "C", (200, 100)),
                 conn("A", 2, "B", 1))
    assert "wire-over-terminal" in codes(text)


def test_crossing_message_names_the_location():
    text = model(comp("Gain", "A", (100, 200)), comp("Gain", "B", (300, 200)),
                 comp("Gain", "C", (200, 100)), comp("Gain", "D", (200, 300)),
                 conn("A", 2, "B", 1, points=[(150, 200), (250, 200)]),
                 conn("C", 2, "D", 1, points=[(200, 150), (200, 250)]))
    msg = [f.message for f in lint.lint_text(text) if f.code == "crossing"][0]
    assert "(200, 200)" in msg


def test_component_after_connection_is_a_syntax_error():
    text = model(comp("Gain", "A", (100, 100)), conn("A", 2, "B", 1), comp("Gain", "B", (200, 100)))
    assert "order" in codes(text)


def test_wire_through_its_own_block(monkeypatch):
    import geometry
    r = {"box": [-20, -5, 25, 5], "terminals": {"1": [20, 0], "2": [-20, 0]}}
    monkeypatch.setattr(geometry, "_TABLE", {"Resistor": {"": {"right/off": r}}})
    # the wire reaches R's terminal 1 (right side) from the left, across R's body and terminal 2
    text = model(comp("Gain", "A", (60, 100)), comp("Resistor", "R", (180, 100)),
                 conn("A", 2, "R", 1, points=[(100, 100)], kind="Wire"))
    assert "wire-through-own-block" in codes(text)


def test_two_connections_on_one_terminal():
    # PLECS uses one connection per terminal; a second one is ignored
    text = model(comp("Gain", "A", (100, 100)), comp("Gain", "B", (300, 100)), comp("Gain", "C", (300, 200)),
                 conn("A", 2, "B", 1), conn("A", 2, "C", 1, points=[(200, 100), (200, 200)]))
    assert "terminal-multiple-connections" in codes(text)
