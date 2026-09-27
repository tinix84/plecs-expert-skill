# Block-diagram layout for PLECS sheets made of C-Scripts and subsystems

Date: 2026-09-27. Status: approved in conversation, awaiting written review.

## Goal

Produce PLECS sheets that look hand-drawn when the sheet is a block diagram: C-Script blocks,
subsystems, scopes, ports and probes, joined by signals. Every connection that is not a short
straight wire between neighbours is a Goto/From pair. The placer scores its own output, so a
non-zero score is a bug, not a matter of taste.

Out of scope: power stages, templates for standard topologies, the cost-function optimiser.
They stay on the phase-1 list for later.

## Users and success

- The `plecs-layout` skill, used by any Agent-Skills client, to draw new controller sheets.
- The Riello milestone-3 generators (`plant_trace.py` and the other unit-test builders), which
  today place From blocks by hand at fixed coordinates.

Success: the retrofitted Riello fixture scores 0, previews clean, simulates in PLECS, and the
milestone-3 comparison against the stored baseline passes unchanged.

## 1. Placement grid

- **Layers by signal flow.** A block's layer is the longest path from a source (a block with no
  signal inputs on the sheet, or an Input port) through the signal nets. Layer 0 is the leftmost
  column. Feedback edges (from a higher layer back to a lower one) do not count toward layering;
  they become tag pairs.
- **One column per layer, blocks stacked top to bottom**, ordered by the barycentre of their
  neighbours in the previous column.
- **Pitch from geometry.** Column x is set so that the widest block in the column, plus a tag
  column on each side (tag 15 px + stub 20 px), plus a 40 px gap, fits before the next column.
  Row pitch is the tallest block in the row plus 30 px.
- **Fixed orientation.** C-Script and Subsystem at `Direction up` (inputs left, outputs right,
  as measured); Scope, Output, Input, Display at `right`. No automatic rotation on these sheets.
- **Zones optional.** With zones, columns run zone by zone left to right; without, one zone.
- **Hints.** `row`/`col` on a part override the automatic position.

## 2. Wire or tag

A connection is drawn as a wire only if all hold, after placement with measured terminals:

1. straight: both terminals on one horizontal or vertical line;
2. clear: no block box and no tag between them;
3. short: length at most `max_wire` px (default 150; 0 means tags everywhere).

Every other connection is a tag pair:

- From tags sit in one column on the block's input side, one per connected input, each on its
  terminal's y, joined by a 20 px straight stub. Goto tags likewise on the output side. A tag
  column reads like a pin list.
- Tag name = net name from the netlist (`Vdc`, `i_abc`, `gate_S1`), never derived from block
  names. One Goto per net, any number of Froms.
- Visibility `"2"` (this sheet) unless the net is declared as crossing into a subsystem, then `"1"`.
- Mux and Demux are ordinary blocks with their own tags.
- Unconnected terminals get nothing; the score reports unconnected inputs.

The router is not used on these sheets. A wire that fails rule 2 or 3 becomes a tag pair.

## 3. Terminal geometry

- **C-Script rule** (from the calibration of PLECS 4.9): ports on a 10 px pitch, centred on the
  edge; edge length `max(30, 10n + 10)` for n ports. At `Direction up`, input 1 is the topmost
  on the left edge and output 1 the topmost on the right. A scalar `NumInputs` such as `"7"` is
  one terminal of width 7; a vector such as `[1 1 1]` gives one terminal per entry.
- **Verification:** the 23 C-Scripts in the Plexim demos. Terminal positions from the rule must
  make the hand-drawn wire legs leave straight, the test that gave 96% on the calibration table.
  A port count that fails is marked unmeasured and reported, not guessed.
- **Subsystems** carry their frame and terminal positions in the `.plecs` file; read them.
- Scope, Output, Input, Display, Mux, Goto, From, Probe are in the measured table already.
- Blocks the calibration could not read (ThreePhaseMeter, ToFile, SignalSwitch) stay unmeasured
  and are reported.

## 4. Score

`score(model_text, netlist)` returns per-item counts and one total; 0 is the target.

| Item | Weight |
|---|---|
| Lint errors: overlap, wire through block, wire over terminal, off-grid, component order | 100 |
| Connectivity differences from the netlist: missing, joined or extra nets, two connections on one terminal | 100 |
| Stub or wire not straight; tag not on its terminal's line | 10 |
| Wire longer than `max_wire` | 10 |
| Unconnected block input | 5 |
| Crossing | 5 |

The placer scores its own output and puts the result in its report next to the SVG preview.
Tests assert score 0 for every generated model. Hand-drawn demo controller sheets are a sanity
check: a high score on a demo means the score is wrong, not the demo.

## 5. Proof on Riello

Retrofit `plant_trace.py` (milestone-3 unit tests) to build the same components through the
block-diagram placer. Required: score 0 and a clean preview; PLECS simulates it; the
milestone-3 comparison against the stored baseline passes unchanged. The retrofit stays in the
Riello repository. The public skill repository gets a synthetic C-Script sheet with the same
structure as example and test.

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `blockdiagram.py` (new, in `skills/plecs-layout/scripts`) | layers, grid, wire-or-tag decision, tag placement; returns a `Sheet` and a report with the score | `geometry`, `layout`, `lint_schematic`, `autolayout.check_connectivity` |
| `geometry.py` | C-Script port rule; Subsystem terminals from the file | `geometry.json` |
| `score.py` (new) | the score table above | `lint_schematic`, `autolayout.check_connectivity` |
| `preview.py` | unchanged | |
| `plecs-layout/SKILL.md` | tells an agent when to use the block-diagram placer and how to read the score | |

## Testing

- Unit: layering with feedback, wire-or-tag rules, tag placement on terminal lines, C-Script
  port rule against the demos, score on constructed faults.
- Integration (skipped without PLECS): the synthetic C-Script sheet simulates and scores 0.
- Riello (local): milestone-3 fixture retrofit as in section 5.
