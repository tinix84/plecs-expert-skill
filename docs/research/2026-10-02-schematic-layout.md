# Improving PLECS schematic layout

Research date: 2026-10-02. Sources below are primary documentation. Recommendations are proposals, not measured improvements. No external layout engine was installed or benchmarked in this investigation.

Scope: current-state investigation, not a completed formal diff review against an agreed baseline. The problematic user schematic was not supplied or inspected in the PLECS GUI; reproductions below use synthetic cases. The coordinating review ran the existing suite in `D:\codex-envs\plecs-expert-skill`: **36 passed, 3 skipped** (PLECS integration tests). All four skills passed `agentskills validate`. These results establish the existing automated baseline; they do not validate actual PLECS rendering or contradict the uncovered cases.

## Finding

The main missing piece is a drawing policy implemented end to end, rather than another wire-routing heuristic. The [September design](../superpowers/specs/2026-09-27-block-diagram-layout-design.md) already specifies a dedicated controller-sheet placer, measured terminals, geometry-dependent spacing, and a quality score. Its proposed `blockdiagram.py` and `score.py` are absent from the current checkout. The existing [autolayout.py](../../skills/plecs-layout/scripts/autolayout.py) instead combines fixed-pitch placement, orientation, routing, and tag fallback. Its `_place` computes coordinates from `dx` and `dy`; its `_layers` iteratively increases levels without an explicit feedback-edge decomposition.

The [router](../../skills/plecs-layout/scripts/router.py) already uses orthogonal A*, inflated symbol obstacles, bend penalties, crossing penalties, and fanout trees. More tuning here cannot by itself correct unreadable grouping, insufficient label space, or inappropriate conversion of visible topology into tags. The [skill](../../skills/plecs-layout/SKILL.md) says tags have no geometry, but their symbols and displayed names occupy space. The [linter](../../skills/plecs-layout/scripts/lint_schematic.py) checks component geometry and connectivity-related hazards, but does not model rendered text envelopes. These are code/documentation observations, not claims that every generated model exhibits every problem.

## Immediate correctness work identified during review

The coordinating review reproduced these cases; source inspection here confirms the relevant implementation paths. Fix these before interpreting an aesthetic benchmark:

1. **Geometry coverage can claim success while using fallback geometry.** In [geometry.py](../../skills/plecs-layout/scripts/geometry.py), `variant_of` does not select the calibrated C-Script variants, while `is_measured` only tests the component kind. The reproduced C-Script call returned an empty variant despite table variants `1in1out`, `2in2out`, and `4in2out`. Coverage must identify the actual kind/variant/orientation lookup used by `shape`, and unsupported combinations must be visible to callers.
2. **Overlap lint does not use the measured rectangles.** Its component-overlap loop uses centre separation. Two Gain blocks at `(100, 100)` and `(120, 100)` have measured rectangles overlapping by 20 px but escape the 15 px centre-distance check. Use transformed body envelopes, then add separate text envelopes.
3. **Tag fallback does not deliver the proposed per-port tag policy.** `_tag` creates one tag per zone and routes that zone's full pin group. A forced same-zone signal tag therefore adds a Goto with no From instead of removing the long local route. Define the intended policy explicitly and test same-zone as well as cross-zone fanout.
4. **Connectivity checks alone cannot certify a drawing.** The review produced an empty connectivity-difference list together with an `unrouted` report: endpoint semantics and explicitly routed geometry are different gates. Completion must require both; do not discard the unrouted status because logical endpoints match.

## What the primary sources support

| Evidence | Consequence for this repository |
|---|---|
| ELK Layered supports orthogonal routing with explicit port constraints, edge labels, and compound graphs. It separates layering, crossing reduction, coordinate assignment, and routing. [ELK Layered](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html) | Model blocks, terminals, labels, and hierarchy before choosing coordinates. A port-aware layered approach is a good benchmark for controller sheets. |
| ELK defines `FIXED_SIDE`, `FIXED_ORDER`, `FIXED_RATIO`, and `FIXED_POS` constraints. [Port constraints](https://eclipse.dev/elk/reference/options/org-eclipse-elk-portConstraints.html) | Measured PLECS terminals need fixed positions relative to their block. A layout engine must not silently reorder ports to improve its drawing. |
| libavoid separates object-avoiding routing from placement and exposes routing penalties and orthogonal path spacing controls. [Router API](https://www.adaptagrams.org/documentation/classAvoid_1_1Router.html) | Compare routing on identical placements. Routing quality and placement quality are different experimental variables. Bend/crossing penalties alone are not the whole routing problem; separation of nearby routes matters. |
| PLECS Goto scope can be schematic, global, masked-subsystem, or code-generation-subsystem scope; matching tag names establish signal connections. [Signal Goto](https://docs.plexim.com/plecs/latest/components-by-category/goto/) | Scope is connectivity semantics, not a cosmetic layout setting. Default to schematic scope; test name reuse in separate hierarchies. Do not globalize tags just to hide a difficult boundary. |
| Electrical Labels connect equal names in the same scope. [PLECS manual, Electrical Label](https://www.plexim.com/sites/default/files/plecsmanual-5-0.pdf) | Replacing a wire with labels requires connectivity equivalence checking, including scope and duplicate names. |
| Plexim's introductory tutorial demonstrates dividing circuit and control into subsystems with explicit ports and movable subsystem terminals. [Standalone tutorial](https://www.plexim.com/sites/default/files/tutorials/introduction_standalone.pdf) | Hierarchy and deliberate interfaces can reduce clutter before routing. Preserve existing interface locations unless changing them is explicitly part of the layout operation. |
| Masked subsystem terminals can be moved or hidden by mask commands; mask drawings use the frame and terminals as references. [Masking subsystems](https://docs.plexim.com/plecs/5.0/using-plecs/masking-subsystems/) | Static assumptions about subsystem geometry can be wrong. Unsupported/dynamic geometry must be reported, not silently treated as calibrated. |

The online PLECS sources describe version 5.0. The repository's measured numeric mapping remains the authority for its tested PLECS 4.9 serialization: `Visibility "2"` is schematic-local and `"1"` is global. Do not infer numeric serialization from the latest manual's human-readable option order.

## Recommended implementation sequence

1. **Make the verifier trustworthy.** Separate hard failures (wrong connectivity, body/text overlap, wire through unrelated body/terminal, diagonal segments, unsupported geometry) from aesthetic measurements. A zero lint count is not proof of readability. Report unknown geometry separately so an unmeasured block cannot earn a misleading perfect score.
2. **Finish the dedicated controller-sheet path.** Implement the existing design with explicit cycle handling, fixed measured terminal positions, row/column constraints, deterministic ordering, and spacing derived from full occupied envelopes. Reserve space for tag names as well as tag symbols. Feedback classification affects drawing only; retain the original directed netlist for equivalence checks.
3. **Benchmark the tag policy before making it universal.** Compare the approved straight-wire-or-tag policy with a conservative alternative that also allows one clean orthogonal elbow between nearby blocks. Report tag count and traceability alongside crossings. Zero crossings achieved by hiding every connection is not automatically the most readable drawing. This alternative changes the approved spec and should remain an experiment until reviewed.
4. **Treat power drawings separately.** Start with explicit templates for repeated legs, rails, sources, loads, and measurement taps. Preserve recognizable power paths and phase alignment. General layered graph placement is a useful controller baseline, not evidence that it understands circuit conventions.
5. **Use actual PLECS rendering as the final visual gate.** Synthetic SVG previews are useful diagnostics, but can omit symbol details and text behavior. For each benchmark keep an original generated example, preview, actual PLECS capture/export, metric report, and simulation result. Store only project-authored synthetic material in this repository.

These priorities are engineering inferences from the current code and the cited capabilities, not prescriptions made by Plexim or ELK.

## External benchmark versus shipped dependency

The repository requires standard-library-only scripts under `skills/`. Therefore do not add ELK or libavoid as a shipped runtime dependency. A maintainer-only experiment can export an anonymous synthetic graph to JSON, run [elkjs](https://github.com/kieler/elkjs) outside the skill, and compare its returned placement/routes with the Python implementation. elkjs is a JavaScript layout package; it does not render the schematic. libavoid is a separate native routing implementation. Neither is a drop-in Python standard-library replacement.

Pin tool versions and options if conducting this experiment. Start ELK with layered/right/orthogonal layout and fixed-position ports; supply node dimensions and label dimensions. Validate the returned geometry on the PLECS grid rather than independently rounding points and assuming connections remain valid. Run libavoid only as a second experiment if routing remains limiting after placement is fixed. No engine can repair incorrect terminal metadata.

## Testable acceptance criteria

Use a small authored fixture set: controller chain; feedback loop; dense fanout; multiport C-Script; unequal-size subsystems; long tag names; duplicated local tag names in separate subsystems; and repeated three-phase power legs.

| Gate | Acceptance |
|---|---|
| Connectivity | Same canonical scoped nets before and after; no missing/extra/joined nets, duplicate drivers, or duplicate terminal attachments. |
| Geometry | Every endpoint equals the measured terminal; all segments orthogonal and on-grid; zero body-body, text-body, text-text, or foreign wire-terminal collisions. Explicitly defined endpoint/owned-label exceptions only. |
| Knowledge | Zero unmeasured geometry in accepted fixtures; unsupported blocks fail with a useful report. |
| Controller policy | All wires satisfy the selected policy; one Goto per scoped signal net; every From resolves; short aligned stubs. |
| Semantics | Supported PLECS version loads and simulates each fixture; deterministic outputs match the unchanged baseline within a declared numerical tolerance. |
| Stability | Repeated runs produce identical coordinates/routes. A local edit preserves explicit fixed positions; measure unrelated displacement. |
| Readability | Side-by-side review at the same scale in PLECS; no clipped names, collisions, or indistinguishable neighboring routes. Record crossings, bends, tags, total wire length, and sheet area separately. |

Choose aesthetic targets after recording the existing baseline. Compare only candidates that pass correctness gates; a lower weighted aesthetic score must never compensate for a connectivity defect. Completion of the missing controller path is the first useful implementation milestone, while a general schematic optimizer remains a separate project.
