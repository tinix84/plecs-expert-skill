---
name: plecs-layout
description: Use when generating, editing, or tidying a PLECS .plecs schematic that a person will open in the PLECS GUI — especially when wires cross, the topology is hard to see, long wires run across the sheet, or blocks join the wrong net when dragged. Covers placement, Goto/From signal tags, electrical Label tags, wire routing with Points, and a lint check.
license: MIT
compatibility: Scripts need Python 3.10+ (standard library only). Loading or simulating the result needs PLECS 4.7 or later.
metadata:
  author: tinix84
  repository: https://github.com/tinix84/plecs-expert-skill
---

# PLECS schematic layout

**Core principle:** draw a wire only where it shows topology. Every other connection is a tag. A schematic is finished when the linter reports no errors.

A connection without `Points` is left to PLECS routing, which ignores other blocks. A wire that runs over a terminal joins that net when someone drags the block. Tags have no geometry, so they cannot cross anything or join anything by accident.

## Procedure

1. **Split the sheet into zones**, left to right, top to bottom. Use one `Zone` each in `scripts/layout.py`:

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
5. **Lint:** run `python scripts/lint_schematic.py model.plecs`. Fix every error. For every `crossing` or `unrouted` warning, reroute or replace the run with a tag. Run the linter again.
6. **Simulate once in PLECS** (XML-RPC `plecs.load`, then `plecs.simulate`, then `plecs.close`). Loading alone does not catch missing wires. The simulation's topology check does, and it names overlapping, unconnected terminals.

## Drawing conventions

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
| `Visibility "1"` | Global: the whole model. Only for tags that must cross into a subsystem. Make the name unique across the model. |
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

`.plecs` files do not store terminal offsets. The linter uses the block centre as its terminal, and treats the leg between a terminal and the nearest Point as bent by PLECS. So it only flags diagonals between two explicit Points. Keep blocks in rows and columns and this gap does not matter. See `references/conventions.md` for the measured conventions and their sources.
