# Block-diagram layout for PLECS sheets made of C-Scripts and subsystems

Date: 2026-09-27. Status: initial implementation complete; PLECS verification pending.

Implementation boundary recorded 2026-10-02: `blockdiagram.layout()` and `score.score()` are
implemented in the public skill repository with table-backed geometry, plain-text envelopes,
connectivity comparison and an authored synthetic C-Script example. The electrical
`Netlist.layout()` path remains separate. PLECS Standalone 4.9.8 loaded and simulated the example;
its final unit-reference output was `1.0` within `1e-6` absolute tolerance. A GUI capture was not
retained, so visual acceptance and text-estimate calibration remain unverified. Subsystem geometry
now supports explicit `Frame` and ordered `Terminal Position` records for the verified
`Direction up` / `Flipped off` form, based on PLECS's `enabled_subsystem.plecs` fixture; GUI
capture and screen-scale calibration remain unverified. The separate power-stage milestone and
Riello project retrofit are not part of this implementation.

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
- **Pitch from occupied geometry.** Placement reserves measured bodies, displayed plain text and
  every candidate tag envelope, including its 20 px stub, even when a net may later be a direct
  wire. Columns and rows are separated by at least 40 px and 30 px. This leaves unused tag space
  rather than running an iterative compaction pass.
- **Fixed orientation.** C-Script at `Direction up`; Scope, Output, Input and Display at `right`.
  Subsystems use explicit frame and terminal records for the verified `Direction up` /
  `Flipped off` template form. Other Subsystem transforms remain unsupported. No automatic
  rotation on supported controller sheets.
- **Zones optional.** With zones, columns run zone by zone left to right; without, one zone.
- **Hints.** `row`/`col` constrain automatic slots. Fixed `at` positions are preserved and rejected
  when off-grid or inconsistent with row/column constraints.

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
- Visibility `"2"` by default. `Visibility "1"` is understood by the connectivity checker as
  model-global, but `blockdiagram.layout()` lays out one sheet at a time and does not create
  subsystem boundaries.
- Mux and Demux are ordinary blocks with their own tags.
- Unconnected terminals get nothing; the score reports unconnected inputs.

The maze router is not used on these sheets. A wire that fails a rule becomes Goto/From tags.
Generated helper names are deterministic. Final lint, connectivity and routing findings remain in
the report; a rejected report is not a completed layout, and the placer does not retry to hide a
final conflict.

## 3. Terminal geometry

- **C-Script variants are table-backed.** Scalar `NumInputs`/`NumOutputs` values select one port
  regardless of signal width; literal vectors select one port per entry. Only calibrated variants
  and orientations resolve. Expressions and uncalibrated counts are unmeasured. The proposed
  general edge-length/10 px pitch formula is not used as a geometry fallback.
- **Subsystems** use only explicit `Frame` and ordered `Terminal Position` records; nested
  Schematic content is never used to guess geometry. The PLECS 4.9.8
  `enabled_subsystem.plecs` fixture confirms the serialized frame and port records. The runtime
  adapter currently accepts only `Direction up` and `Flipped off`; missing/malformed records and
  other orientations remain unsupported. The retained GUI capture and screen-scale calibration
  are separate visual-acceptance evidence and are still pending.
- Scope, Output, Input, Display, Mux, Goto, From and other blocks resolve only for calibrated table
  variants. `geometry.json` is the source of supported entries.
- Blocks the calibration could not read (ThreePhaseMeter, ToFile, SignalSwitch) stay unmeasured
  and are reported.

## 4. Score

`score(model_text, netlist)` returns per-item counts and one total; 0 is the target.

| Item | Weight |
|---|---|
| Lint errors: overlap, wire through block or displayed text, wire over terminal, off-grid, component order | 100 |
| Connectivity differences from the netlist: missing, joined or extra nets, two connections on one terminal | 100 |
| Stub or wire not straight; tag not on its terminal's line; undeclared tag names | 10 |
| Wire longer than `max_wire` | 10 |
| Direct connections left untagged when `max_wire=0` | 10 |
| Unconnected block input | 5 |
| Crossing | 5 |

The placer scores its own output under `report["quality"]`. The result includes counts, weighted
score, findings, coverage, connectivity, unrouted nets, crossings, bends, tag count, wire length,
occupied area and optional displacement. `accepted` requires zero weighted score, complete
supported geometry, equivalent connectivity and no unresolved routing or tags. Tests assert score
0 for the accepted synthetic controller; faulty and unsupported layouts stay rejected.

## 5. Proof on Riello

The approved Riello retrofit remains a separate project task. This public repository contains an
authored synthetic C-Script controller. Its integration test loads and simulates it when PLECS
XML-RPC is running; a skipped integration test does not count as verification.

## Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `blockdiagram.py` (`skills/plecs-layout/scripts`) | deterministic layering, measured-envelope spacing, fixed orientations, straight-wire/tag decision and report | `geometry`, `layout`, `lint_schematic`, `autolayout.check_connectivity` |
| `geometry.py` | variant lookup, C-Script variant parsing, explicit Subsystem frame/port adapter and text estimates | `geometry.json`; Subsystem records restricted to the verified up/off form |
| `score.py` | weighted diagnostics and strict accepted status | `lint_schematic`, `autolayout.check_connectivity` |
| `preview.py` | unchanged | |
| `plecs-layout/SKILL.md` | tells an agent when to use the block-diagram placer and how to read the score | |

## Testing

- Unit: layering with feedback, wire-or-tag rules, tag placement on terminal lines, C-Script
  port rule against the demos, score on constructed faults.
- Integration (skipped without PLECS): a test loads the synthetic controller and compares its
  final output to 1.0 with `1e-6` absolute tolerance. Unit tests or skipped integration tests do
  not prove actual PLECS behavior.
- Riello (local): milestone-3 fixture retrofit as in section 5.
