# Score calibration on the Plexim demo sheets (ticket #22)

Date: 2026-09-28

Question: what do the hand-drawn Plexim demo sheets score under the layout checks in
`docs/superpowers/specs/2026-09-27-block-diagram-layout-design.md` section 4, and which of the
spec's score weights would punish things engineers do on purpose?

`score.py` does not exist yet, so this is not a run of the real scorer. The data below comes
from the two tools that do exist — `skills/plecs-layout/scripts/lint_schematic.py`
(`lint_text`) and `skills/plecs-layout/scripts/plecs_file.py` — applied per sheet, with the
score items reconstructed from the spec's weight table. The script that produced every number
here is `docs/research/score_calibration_demos.py`; it is checked in so the run can be repeated.

## Data

89 `.plecs` demo models under `D:/OneDrive/Documenti/Plexim/PLECS 4.9 (64 bit)/demos/*/*.plecs`,
root sheet plus every `Subsystem` sub-sheet counted separately: 490 sheets total, 346 of them
signal-only (every `Connection` on the sheet is `Type Signal`, i.e. a controller-style sheet
rather than a power stage).

## Distribution across signal-only sheets (346 sheets)

| Item | median | p90 | max |
|---|---|---|---|
| Blocks per sheet | 9 | 20 | 56 |
| Goto/From/Label blocks per sheet | 0 | 0 | 14 |
| Connections per sheet | 8 | 19 | 59 |
| Connections over 150 px per sheet | 1 | 6 | 14 |
| Crossings per sheet | 0 | 1 | 8 |
| Lint errors per sheet | 0 | 0 | 2 |

Only 2 of 346 signal-only sheets (0.6%) have any lint-error finding at all, and both are the
same code, `tag-orphan-from` (2 occurrences each): `double_fed_induction_generator_wind_turbine
/Thermal` and `wind_power_system_pmsg/Thermal`. None of the five checks the spec's lint-error
row actually names (overlap, wire-through-block, wire-over-terminal, off-grid,
component-order) fires on any signal-only demo sheet.

Wires over 150 px are common: 702 of 3349 connections (21.0%) on signal-only sheets exceed
`max_wire`; across all 490 sheets (including power stages) it is 1745 of 7015 (24.9%).

## Five highest-scoring signal-only sheets

Using `errors*100 + long_wires*10 + crossings*5` (the two items this study could compute
directly plus lint errors):

1. `double_fed_induction_generator_wind_turbine /Thermal` (score 215) — two From tags flagged
   `tag-orphan-from` with no matching Goto in scope, plus 1 long wire and 1 crossing; looks like
   a linter scope-heuristic false positive on a cross-sheet tag, not a real drawing defect.
2. `wind_power_system_pmsg /Thermal` (score 215) — identical pattern to #1 (same Thermal-sheet
   layout reused across the two wind-turbine demos).
3. `double_fed_induction_generator_wind_turbine /Inverter Control/Speed Control` (score 160) —
   13 of its wires exceed 150 px and 6 pairs cross; a dense feedback control loop drawn as direct
   wires rather than Goto/From tags.
4. `cycloconverter /Controller` (score 145) — 14 long wires and 1 crossing; many long
   point-to-point signal runs spread across a wide controller sheet.
5. `buck_converter_bcm /Controller` (score 130) — 11 long wires and 4 crossings; the same
   long-wire pattern on a more compact controller sheet.

## Weight recommendations

| Item | Spec weight | Recommendation | Reason from the data |
|---|---|---|---|
| Lint errors (overlap, wire-through-block, wire-over-terminal, off-grid, component order) | 100 | Keep | None of the five named checks fires on any of the 346 signal-only sheets; the only lint-error hits (2 sheets, `tag-orphan-from`) are outside this row's named list and look like a linter false positive on a cross-sheet global tag, not something engineers do on purpose. Worth fixing the linter's scope heuristic, not softening the weight. |
| Connectivity differences from netlist | 100 | Keep (unverified) | `score(model_text, netlist)` needs an authoritative netlist per demo, which this study did not have; not evaluated. |
| Stub or wire not straight / tag not on terminal's line | 10 | Keep (unverified) | `lint_schematic.py` has no finding code for "bent" wires or tag-terminal misalignment yet, so this item could not be computed from the demos. |
| Wire longer than `max_wire` (150 px) | 10 | Change to 5 (or scale by length, not a flat per-wire count) | 21% of connections on signal-only sheets exceed 150 px, and this is routine, not accidental: median sheet has 1, p90 has 6, and the two "Controller" sheets in the top-5 (`cycloconverter`, `buck_converter_bcm`) score 130-145 purely from long wires on sheets that are otherwise clean. A wide but well-organized controller sheet already outscores a single lint error at this weight, which is backwards. |
| Unconnected block input | 5 | Keep (not evaluated) | Not computed by this study; the ticket did not ask for it and the linter has no dedicated finding for it. |
| Crossing | 5 | Keep | Most sheets have 0 crossings (median 0, p90 1); the flat weight of 5 does not dominate the common case. The tail — feedback-heavy control loops such as Speed Control (6 crossings) or its Measurements-transformation sub-sheet (8) — racks up 30-40 points from crossings that are a normal consequence of drawing a feedback path by hand, not a layout mistake, so 0 is an aggressive target there even though the per-crossing weight itself is fine. |

## Caveats

- The linter approximates an unmeasured block's terminals by the block's centre (see
  `lint_schematic.py`'s module docstring); geometry checks against those blocks are
  correspondingly imprecise.
- Wires in the demos are hand-routed by Plexim engineers, and PLECS itself bends the leg at a
  terminal automatically, so a "straight" wire in the file can still look bent on screen, and a
  bend the tool never recorded as a Point is invisible to the lint checks used here.
- This study only reproduces the score items computable from `lint_text` and `_segments` today
  (lint errors by code, crossing count, connection length); it does not run the real
  `score.py`, which does not exist yet, and does not evaluate connectivity-vs-netlist,
  unconnected inputs, or the bent-wire/tag-alignment item.
- No schematic content was copied out of the Plexim demos — only counts, sheet paths and file
  names appear above and in the generated JSON/CSV.
