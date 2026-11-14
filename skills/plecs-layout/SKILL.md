---
name: plecs-layout
description: Use when generating, editing, or tidying a PLECS .plecs schematic that a person will open in the PLECS GUI. Covers separate electrical-circuit and controller-block layout paths, signal tags, electrical Labels, measured geometry, previews, connectivity checks and lint.
license: MIT
compatibility: Scripts need Python 3.10+ (standard library only). Loading or simulating the result needs PLECS 4.7 or later.
metadata:
  author: tinix84
  repository: https://github.com/tinix84/plecs-expert-skill
---

# PLECS schematic layout

**Core principle:** use the layout path that matches the sheet. Electrical circuits use the router and preserve circuit rails and grounded nodes. Controller block diagrams use measured terminals, short straight wires and signal tags for other connections. A clean lint report is one gate; connectivity, geometry coverage and routing must pass too.

Signal tags occupy space: Goto/From symbols and displayed tag text can overlap blocks or other text. Electrical Labels also occupy space. A connection without `Points` is left to PLECS routing, which ignores other blocks, and moving a block onto a wire can join its net.

## Controller block diagrams

From the skill's `scripts` directory (or with that directory on `PYTHONPATH`), use
`blockdiagram.layout(netlist, *, zones=None, max_wire=150, grid=5)` for a signal-flow
diagram made from supported blocks such as C-Scripts, signal sources, Scope and Output blocks,
plus Subsystem templates with explicit supported frame and terminal records.
A signal net lists its driver first. Optional `row`/`col` hints and fixed `at` positions are
preserved; fixed coordinates must lie on the 5 px grid. C-Scripts are oriented up; Scope, Input,
Output and Display blocks are oriented right. Cycles remain in the logical netlist and use
Goto/From tags for feedback.

```python
import blockdiagram
from autolayout import Netlist

netlist = Netlist()
netlist.part("Reference", "Constant", {"Value": "1"}, zone="input")
netlist.part("Controller", "Gain", {"K": "1"}, zone="control")
netlist.part("Output", "Output", {"Index": "1"}, zone="output")
netlist.net("reference", "Signal", [("Reference", 1), ("Controller", 1)])
netlist.net("result", "Signal", [("Controller", 2), ("Output", 1)])

sheet, report = blockdiagram.layout(
    netlist, zones=["input", "control", "output"], max_wire=150)
if not report["quality"]["accepted"]:
    raise ValueError(report["quality"]["findings"])
```

`report["quality"]` separates weighted counts, findings, geometry coverage, connectivity,
unrouted nets and metrics. `accepted` requires zero weighted score, supported geometry, equivalent
connectivity and no unresolved routes or tags. Review the diagnostic preview, then load and
simulate the generated sheet in PLECS. The synthetic command-line example writes a `.plecs` file
and an SVG preview. From `skills/plecs-layout`, run:

```powershell
python scripts/example_blockdiagram.py --out controller.plecs
```

The controller path accepts only measured kind/variant/orientation combinations and plain,
single-line displayed text. For a C-Script with code, pass its parsed `Component` as
`component=` and matching parameters to `Netlist.part` so the function fields are preserved.
C-Script parameter expressions are unsupported. For a Subsystem, pass an inspected parsed
`Component` template to `Netlist.part`; geometry requires a valid `Frame` and ordered `Terminal
Position` records, and currently supports only `Direction up` with `Flipped off`. Missing records
and other orientations remain unsupported. Adjacent multiport terminals that need overlapping
local tag symbols or labels raise `LayoutError` with `tag_spacing_conflict`; direct wires remain
eligible. The text estimate uses 8 px per character,
12 px line height, 2 px margin and 8 px clearance. It is a layout estimate, not a PLECS renderer.
A rejected report must not be treated as a finished drawing.

## Procedure

1. **For electrical circuits, split the sheet into zones**, left to right, top to bottom. Use one `Zone` each in `scripts/layout.py`:

   | Zone | Holds |
   |------|-------|
   | Sources | grid or DC sources and their impedance |
   | Power stage | converter topology, drawn left to right |
   | Load / DC link | capacitors, loads |
   | Measurement | meters, probes, one column |
   | Control | reference, error, controller chain, left to right by signal flow |
   | Outputs | scopes, `Output` ports, To File blocks |

   Space blocks 40 to 80 px apart. Every coordinate is a multiple of 5.
2. **Decide wire or tag for every net:**

   | Net | Use |
   |-----|-----|
   | Main power path inside one zone | wire |
   | Electrical node needed in another zone (meter, second stage) | electrical `Label` pair |
   | Measured value, reference, gate or PWM signal leaving its zone | `Goto` next to the source, `From` next to each user |
   | Signal between neighbouring blocks in one row | short wire |
   | Anything that would cross another wire | tag |
| Rail shared by many densely packed parts (DC+, DC-, neutral) | electrical `Label` at each part |
3. **Build the model with `scripts/layout.py`** (`Sheet`, `Zone`, `goto`, `from_`, `label`, `wire`, `signal`, `model`). Or write the text by hand under the same rules. The module docstring shows a complete example.
4. **Route every wire.** Give `Points` to every connection whose two ends are not on one horizontal or vertical line. Consecutive `Points`, including a branch's first point after its junction, share x or y. Keep wires at least 15 px away from blocks that are not their own ends.
5. **Preview:** run `python scripts/preview.py model.plecs` and look at the SVG (convert it to PNG if your viewer needs one). Dashed red legs are inferred by the legacy preview; the strict controller path rejects non-straight connections.
6. **Lint:** run `python scripts/lint_schematic.py model.plecs`. Fix every error. Review geometry and text coverage warnings; unsupported estimates cannot establish controller acceptance.
7. **Simulate once in PLECS** (XML-RPC `plecs.load`, then `plecs.simulate`, then `plecs.close`). Loading alone does not catch missing wires. The simulation's topology check does, and it names overlapping, unconnected terminals.

## Drawing conventions

The electrical placer increases automatic row spacing when grounded pins need room for local Ground symbols.
Fixed positions remain unchanged. Series meters use their electrical terminals to select orientation.
Generated names use a side without terminals, and generated Ground symbols hide their names.
Routing reserves displayed text rectangles. New tags must also clear existing wires.
These checks do not establish native PLECS visual acceptance.

Use `role="rail"` in `Netlist.net` for shared electrical rails. The router reserves these nets before other connections.
Use `row`, `col`, and `direction` hints to align bridge legs and vertical DC-link shunts.
Dense signal receivers use spaced tag banks. Vertical tags put their text beside the wire path.
An absent terminal in a calibrated block raises `ValueError`; it must not route from the block center.

| Part | Draw it |
|------|---------|
| Voltage and current sources | Vertical, terminal 1 (+) on top: `Direction up`, `Flipped off` |
| Ground | One Ground under each grounded pin, pointing down (terminal on top): `Direction up`, `Flipped off`. All Ground blocks are one node, so no ground wire crosses the sheet. |
| C-Script | `Direction up` puts inputs on the left and outputs on the right. `Direction right` puts inputs on top. |
| Passive parts | Terminal 1 is on top at `Direction up` and on the right at `Direction right`. |

Terminal positions for every orientation are in `scripts/geometry.json`, measured from PLECS 4.9.

## Tag rules

| Parameter | Rule |
|-----------|------|
| `Visibility "2"` | This schematic only. Use by default. |
| `Visibility "1"` | Global: the whole model. Use only for tags that must cross sheet boundaries. Make the name unique across the model. |
| `Tag` | Short engineering name: `Vdc`, `Idc`, `ia`, `ib`, `ic`, `is_abc`, `gate_S1`, `m_a`, `Vdc_ref`. Never `Signal1`. |
| One Goto per tag per scope | Any number of Froms. |
| Electrical `Label` | Same tag in two or more places joins the nodes. A single Label is an error. |

Block keywords: `Goto`, `From`, `Label` (electrical), `PlecsProbe` (reads a component's probe signals by name, no wire needed). The exact text for each is in `references/conventions.md`.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Connections between far-apart blocks with no `Points` | Route with `Points`, or use a tag |
| Measurement wires running back to one scope | `Goto` at the meter, `From` at the scope |
| A shared bus drawn through the middle of other blocks | Route the bus on its own row, or use Labels |
| `Visibility "1"` used as "local" | `"1"` is global; local is `"2"` |
| Checking the file by eye only | Run the linter. The drawing looks fine in text and wrong in the GUI. |
| Stopping at a clean lint | The linter checks geometry, not connectivity. Simulate. |

## Limits

PLECS files do not store built-in terminal offsets. The geometry table has measured entries for
specific variants and orientations; the generic electrical path can show a marked fallback for
unknown entries, while the controller path rejects them. The legacy linter recognizes
PLECS-inferred bends in existing electrical models. Controller acceptance requires measured
terminals, supported rendered text, no lint errors and equivalent connectivity. See
`references/conventions.md` for geometry and text assumptions.
