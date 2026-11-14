# PLECS layout conventions: facts and sources

Measured on the 90 demo models shipped with PLECS 4.9 (`demos/*/*.plecs`) and checked against the PLECS 4.9 manual and PLECS itself where stated. Prose is our own; only file syntax is quoted.

## Grid and spacing

- 99.9 % of the demos' 8,678 component positions and 5,902 wire points are multiples of 5. Use a 5 px grid.
- Two-terminal parts wired in a row sit 40 to 55 px apart, centre to centre.
- Tag blocks (Goto, From, Label, Constant, probes) stack as close as 15 px. Other parts stack at 20 px or more.

## Tag blocks

Goto and From have separate calibrated shapes by direction and flip state. Electrical `Label`
uses the same `Tag` and `Visibility` parameters, with its own geometry entries.

```
Component {
  Type          Goto          (or From, or Label)
  Name          "Goto1"
  Show          off
  Position      [195, 245]
  Direction     right
  Flipped       off
  LabelPosition south
  Parameter {
    Variable      "Tag"
    Value         "gate"
    Show          off
  }
  Parameter {
    Variable      "Visibility"
    Value         "2"
    Show          off
  }
}
```

| Visibility | Scope | Evidence |
|------------|-------|----------|
| `"1"` | Global: the whole model | PLECS 4.9: the `three_phase_diode_bridge_rectifier` demo matches tag `id` across a subsystem boundary at `"1"` |
| `"2"` | Schematic: only the sheet containing the block | PLECS 4.9: the same model fails at `"2"` with "No matching Goto block found for tag 'id'" |
| `"3"` | Masked subsystem hierarchy (global if not inside one) | Manual order of the Scope options; not supported by the repository connectivity checker |

The manual lists the Scope options as Global, Schematic, Masked Subsystem, Code-Gen Subsystem, with no numbers. Values `"1"` and `"2"` were verified by simulation on 2026-09-26. The checker resolves local tags per schematic path and global tags across paths; other values are reported as unsupported.

A `Label` connects electrical potentials by name. It has one electrical terminal and sits on a net like any other part, through a `Branch` of a `Type Wire` connection. A Label pair was verified by simulation to join two otherwise unconnected nets (`tests/test_plecs_integration.py` in the repository).

## Probe block

```
Component {
  Type          PlecsProbe
  Name          "Mains current"
  Show          on
  Position      [100, 345]
  Direction     right
  Flipped       off
  LabelPosition south
  Probe {
    Component     "Am1"
    Path          ""
    Signals       {"Measured current"}
  }
}
```

A probe refers to a component by name (and `Path` for another subsystem), so it needs no wire. Its signal names are the probe signals listed for each component in the `plecs-components` skill.

## Wires

- `Type Wire` for electrical, `Type Signal` for signals.
- `Points [x1, y1; x2, y2]` lists the corners. A `Branch` starts at the parent's last Point, or at the source terminal when the parent has none.
- In the demos, the leg from a terminal to the nearest Point often differs on both axes. PLECS draws that leg with its own corner. This is inferred from the demos, not from the manual: segments between two explicit Points are always horizontal or vertical there.
- Dragging a block so that its terminal lands on a wire, or a wire onto a terminal, joins the nets (manual, "Connections"). This is the "joined when moved" failure. Keep foreign wires out of a block's area.

## Terminal numbers that matter for tags

| Block | Terminals |
|-------|-----------|
| Ammeter | 1, 2 electrical; 3 signal output (measured current) |
| Voltmeter | 1, 2 electrical; 3 signal output (measured voltage) |
| Goto | 1 signal input |
| From | 1 signal output |
| Label | 1 electrical |
| Diode | 1 anode, 2 cathode |

## Terminal geometry

Built-in blocks do not store terminal offsets in the file. The repository's `scripts/geometry.json`
contains measured boxes and terminal offsets for the listed kind, variant, orientation and flip
state. Geometry lookup must match that full combination. A missing variant stays unmeasured;
falling back to a block centre is only a diagnostic aid for the generic preview/linter and cannot
establish a valid controller layout. The C-Script entries are table-backed; literal expressions
that do not select a calibrated entry are unsupported. A scalar `NumInputs`/`NumOutputs` denotes
one port width, while a vector denotes separate ports.

The controller path reads Subsystem geometry only from the component's serialized `Frame` and
ordered `Terminal Position` records; nested sheet contents are not used to infer an interface.
The adapter currently accepts only `Direction up` with `Flipped off`. Missing/malformed records
and other orientations remain unsupported. An installed PLECS 4.9.8 `enabled_subsystem.plecs`
example exposes a 50-by-30 frame and three ordered ports; the adapter regression covers those
record forms, and `Sheet.add_component` preserves them. Independent screen-coordinate measurement
and a retained GUI capture are still open, so this evidence does not calibrate the text estimate.

## Text and occupied space

Layout, lint and preview share a conservative plain-text estimate: 8 px per character, 12 px line
height, 2 px margin and 8 px clearance from the associated body. It supports single-line names,
tag strings and shown parameter values without formatting. Multiline, escaped/markup text and
other unsupported rendered text are reported as coverage limitations. These estimates have not
been calibrated against a retained PLECS screenshot in this implementation; the SVG remains
diagnostic, not a replacement for inspecting the model in PLECS.

## How the demos arrange a sheet

- Control and modulation sit in a `Subsystem` beside the power stage, not mixed into it.
- Gate and PWM signals reach switches through Goto/From pairs placed next to each switch, not through long wires.
- Tags are engineering names: `Vdc`, `Idc`, `gate`, `vo`, `is_abc`, `ma`/`mb`/`mc`, `Vph`, `Iph`.
- Probes are stacked in one column at a fixed x.

## Linter calibration

`scripts/lint_schematic.py` on the 90 demos: 62 have no errors. The rest are mostly overlapping blocks and wires close to blocks. Three unguided generated models of a three-phase diode rectifier scored 10 to 21 findings each.

## Related work

[yingriyanlong/plecs-mcp](https://github.com/yingriyanlong/plecs-mcp) (MIT) documents a two-rail placement for single small converters, also derived from the demos (`docs/plecs-layout-conventions.md`).

## Implementation verification (2026-10-02)

PLECS Standalone 4.9.8 loaded and simulated the authored controller example. Its final output was
`1.0` for a unit reference, within the integration test's `1e-6` absolute tolerance. A PLECS GUI
capture was not retained, so visual acceptance and calibration of the text estimate remain open.
