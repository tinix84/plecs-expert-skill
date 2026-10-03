# PLECS schematic layout implementation plan

Date: 2026-10-02. Status: reviewed against Claude's committed work through `a3d5ce7`; proposed implementation sequence. No implementation changes made by this plan. Execution tasks below are sized for Luna at xhigh; they have not yet been trial-run by that model.

Build a layout pipeline whose geometry and connectivity checks are trustworthy, then complete the dedicated controller-sheet placer. The first deliverable is a readable synthetic controller schematic that passes automated checks and an actual PLECS visual and simulation check. Power-stage layout follows as a separate milestone because readable circuit topology requires different placement rules.

This plan builds on the [current-state research](../research/2026-10-02-schematic-layout.md) and [controller layout design](../superpowers/specs/2026-09-27-block-diagram-layout-design.md). The recorded baseline is commit `a3d5ce7`, with 36 tests passing and three PLECS integration tests skipped. This baseline anchors implementation comparisons; it does not imply a completed historical diff review. The user's problematic schematic has not yet been inspected.

## Scope and decisions

- Keep scripts under `skills/` agent-agnostic and standard-library-only. Reuse the parser, model writer, geometry table, and useful router code.
- Keep the generic electrical layout API working. Add an explicit controller path instead of silently switching existing callers to new drawing rules.
- Preserve simulation parameters, component identity, port ordering, and scoped connectivity. Placement may change; behavior must not.
- For the initial controller path, retain the design's short, clear, straight wire rule, `max_wire=150`, and `max_wire=0` for tags everywhere. Feedback uses tags. Do not introduce elbow routing into this milestone.
- Keep existing hierarchy and interfaces. Do not automatically restructure models into subsystems or change local tags into global tags to solve layout problems.
- Separate correctness failures from aesthetic metrics. Retain the design's weighted score for diagnostics, but never let an attractive drawing compensate for a connectivity failure or unknown geometry.
- Use only authored synthetic fixtures in this repository. Client adaptation stays in its own repository; demo models, manual text, and calibration build products remain uncommitted.

The plan extends the earlier design in three explicit ways: text occupies layout space, the preview exposes that space, and acceptance requires independent correctness gates in addition to the score. These are proposed design refinements. External-engine comparisons and alternative wire policies are optional later experiments.

## Continuity with Claude's work

These are conclusions from the commit messages and current implementation, not a reconstruction of unavailable Claude conversations.

| Existing work | Preserve and build on | Change deliberately |
|---|---|---|
| `a5d046e`, `63561fb`: parser, writer, linter, placer and orthogonal A* router | Reuse `plecs_file.Block`, `Sheet`, `Netlist`, and `Router`; keep electrical routing available. | Add a separate controller placer, as the later design requests; do not replace the router or rewrite the parser. |
| `67bb282`: components before connections; branches inherit connection type | Preserve writer ordering and single-tree branch semantics. | Strengthen validation without emitting independent connections on the same terminal. |
| `c14be20`: parametric terminal roles in calibration | Read `maintainer/geometry/make_calibration_sheet.py` before implementing runtime C-Script port parsing; reuse verified semantics rather than inventing a second interpretation. | This calibration logic is not yet runtime geometry support. Add that support explicitly. |
| `40ca129`: measured PLECS 4.9 geometry | Keep the measured table and its provenance. Unknown variants stay visibly unknown. | Repair variant lookup and coverage reporting; do not replace measured offsets with generic guessed dimensions. |
| `50aa568`: vertical sources and per-pin downward Grounds | Preserve `_style`, `_split_grounds`, polarity and Ground connectivity in the electrical path. | Add regression coverage when shared geometry/checker changes touch these behaviors. |
| `ff98a10`: vertical shunts, one tag per zone, SVG preview | Preserve ordinary electrical nets within a zone and one electrical Label per zone for cross-zone joins. Keep the preview and extend it. | Explicitly forced signal tags get per-receiver Froms. This does not revoke the electrical policy that avoided fragmenting nearby nodes into labels. |
| `761511a`: approved controller design | Implement the missing `blockdiagram.py` and `score.py`, fixed controller orientations, short straight wires and tags, and geometry-dependent spacing. | Track the plan's refinements explicitly; do not silently rewrite the approved design. |
| `a3d5ce7`: one connection per terminal, row/column hints, series-chain rows, connectivity report | Preserve branched connections, explicit hints and phase-chain alignment. The commit explicitly acknowledges that power-stage drawing is still unacceptable. | Improve the checker and controller path; do not present controller completion as proof that the power-stage problem is solved. |

Before changing generic layout behavior, run its existing tests and add missing protection for series-chain rows, shunt orientation, Ground splitting, and one electrical tag per zone. Keep same-zone automatic electrical routing behavior out of the controller-policy changes.

## Milestone 1 Make geometry and validation reliable

### Step 1 Capture small failing cases

Files: `tests/test_autolayout.py`, `tests/test_lint.py`, and a new `tests/test_geometry.py`.

Add behavior-level regressions for the reproduced failures before fixing them:

- A calibrated C-Script variant must resolve actual terminals, not the component centre.
- A known component kind with an unsupported variant must be reported as unsupported.
- Two Gain blocks at `(100, 100)` and `(120, 100)` must produce an overlap finding using their measured boxes.
- A forced same-zone signal tag must connect its receiver through a From, rather than merely adding a Goto to existing local wiring.
- An empty connectivity-difference list must not make an unrouted result acceptable.

Keep these cases small enough that the expected geometry and connectivity can be inspected directly. Record the baseline failures; do not change existing expected results simply to obtain a green suite.

### Step 2 Resolve actual geometry consistently

Files: `skills/plecs-layout/scripts/geometry.py`, its callers in `autolayout.py` and `lint_schematic.py`, and the geometry tests.

Make coverage depend on the complete kind, variant, orientation, and relevant parameters. Callers must use the resolved shape's coverage status rather than treating presence of a kind in the table as sufficient evidence.

Implement C-Script variant selection first for existing calibrated entries. Then implement the proposed parametric port rule only after checking it against available PLECS 4.9 calibration evidence. Distinguish a scalar signal width from a vector of separate ports. Handle zero ports explicitly. Parameter expressions that cannot be resolved without PLECS must return an unsupported result; never evaluate arbitrary model expressions in Python.

Read subsystem frame and terminal data from parsed model structure through a small shared geometry adapter. Preserve explicit terminal ordering and position. Dynamic masked geometry remains unsupported unless its resolved dimensions and terminals are available. Existing generic preview behavior may retain a visibly marked fallback; accepted controller layouts must reject it.

Acceptance: table-backed and verified rule-backed terminals agree with measured cases in every supported orientation. Unsupported variants appear in the report with component identity and reason. No controller connection silently terminates at a guessed centre.

### Step 3 Check occupied rectangles and terminal legs

Files: `lint_schematic.py`, `geometry.py`, `preview.py`, and lint tests.

Replace centre-distance overlap detection with transformed body-rectangle intersection. Define intentional exceptions for containers and owned symbol details. Check every explicit segment and every terminal-to-point leg; an inferred PLECS bend is not an accepted controller route.

Represent displayed names, tag text, and shown parameter text as separate occupied rectangles. Use one conservative, documented text-size estimate shared by placement, lint, and preview. Record the font/scale assumptions and calibrate estimates against PLECS captures. Keep text collision diagnostics distinct from body collisions so estimation errors can be investigated. Unknown or unsupported rendered text must remain visible as a validation limitation.

Acceptance: catch the reproduced Gain overlap, rotated-body collisions, long-name collisions, and wires touching foreign terminals. Allow intended endpoint contacts. Diagnostic SVGs show text, tags, and their reserved space at readable scale; they remain diagnostic previews, not substitutes for PLECS rendering.

### Step 4 Verify net equivalence and fix forced signal tags

Files: `autolayout.py`, `plecs_file.py` where needed, connectivity tests, and integration tests.

Compare normalized logical nets before and after generation, projecting generated Ground and tag helpers back onto original terminals. Preserve net kind, source direction for signals, and schematic scope. Detect missing, extra, split, and accidentally joined connections, multiple signal drivers, duplicate terminal attachments, and unresolved From blocks. Reuse the same checker for both layout paths.

For supported hierarchy, resolve tags according to scope; equal local names in separate sheets must remain separate. Reject unsupported scope cases explicitly rather than merging by name. Retain the verified PLECS 4.9 mapping of local `"2"` and global `"1"`.

Fix explicitly forced signal tags in the generic path to produce one Goto at the driver and a From for each receiver, including same-zone receivers. Preserve electrical Label behavior separately. Do not broadly change automatic electrical tag policy in this step.

Acceptance: scoped-name reuse, same-zone fanout, cross-zone fanout, deliberately joined nets, missing receivers, and duplicate drivers all have independent expected outcomes. Connectivity and routing status are separate report fields. When PLECS is available, a synthetic tagged model must load and simulate.

## Milestone 2 Complete the controller layout pipeline

### Step 5 Implement deterministic placement

Files: new `skills/plecs-layout/scripts/blockdiagram.py` and `tests/test_blockdiagram.py`; extend `layout.py` only where necessary to preserve required component data.

Expose a controller layout function accepting the existing netlist representation and layout options, returning a `Sheet` and a report. Add an explicit way to carry subsystem frame/port geometry and C-Script payloads without losing them during serialization. Work from an immutable logical-netlist snapshot; generated helpers must not pollute caller data on repeated runs.

Use this sequence:

1. Resolve geometry and validate signal port roles before placement.
2. Identify cycles deterministically. Use stable traversal and record feedback edges; remove them only from the placement graph, never from the logical netlist. Self-loops are feedback too.
3. Assign longest-path layers on the remaining acyclic graph, including disconnected components with a stable order.
4. Order blocks using bounded barycentre sweeps with stable tie-breaking. Explicit row/column hints take precedence.
5. Compute column and row spacing from bodies, labels, terminal positions, tag columns, 20 px stubs, and the design's minimum gaps. Expand spacing for long names instead of squeezing them.
6. Honor fixed coordinates and detect conflicting hints. Return a useful conflict report instead of moving fixed blocks silently.

Apply fixed controller orientations from the design. Preserve zones when supplied. A synthetic subsystem with custom terminal positions must use those positions rather than assuming evenly spaced ports.

Acceptance: chains flow left to right; feedback does not inflate layers; multiport blocks and unequal-size subsystems fit; hints are honored or rejected clearly; repeated runs produce identical coordinates and leave inputs unchanged.

### Step 6 Add straight wires and per-port tags

Files: `blockdiagram.py`, `layout.py` if tree emission needs a narrow extension, and controller tests.

Reserve candidate tag space during placement. Emit a direct connection only when terminals align, the run is within `max_wire`, and it avoids foreign bodies, text, terminals, tags, and other nets. Otherwise emit aligned tag stubs, using the logical net name as the visible tag and separately generated unique component names.

For the first implementation, use an all-or-tags fanout policy: emit a direct branched net only when the entire fanout meets the straight/clear/short rule and can be represented as one connection tree; otherwise use one Goto and one From per receiver for that net. This deliberately avoids mixed direct/tag fanout complexity. Record this refinement in the design.

Reserve the full candidate tag envelopes even for nets that may become direct wires, then decide wire versus tag in stable net-name order. This deliberately spends extra space to avoid an iterative layout optimizer. Check final occupied geometry after insertion. If it still conflicts, report the conflict and reject acceptance; do not add arbitrary retry loops or fall back to implicit PLECS routing. Compacting unused tag space is deferred. The maze router is not used by this controller path.

Acceptance: one connection attachment per terminal, one Goto per tagged net, resolvable Froms, 20 px aligned stubs, no crossings or foreign collisions, and equivalent scoped connectivity. Include feedback, dense fanout, long tag names, and `max_wire=0` cases.

### Step 7 Add the quality report

Files: new `skills/plecs-layout/scripts/score.py`, `tests/test_score.py`, and report integration in `blockdiagram.py`.

Implement the earlier design's per-item score counts and weights. Also return explicit correctness and coverage status, with findings attributed to components, terminals, or nets. Unknown geometry and unrouted connections prevent acceptance even when the weighted score is zero.

Report aesthetic measurements separately: crossings, bends, tag count, wire length, occupied sheet area, and displacement of unrelated blocks after a small edit. Do not invent aggregate aesthetic targets before inspecting the baseline fixtures.

Acceptance: independently constructed faulty models trigger the intended findings. Every accepted generated controller fixture has score zero, equivalent connectivity, supported geometry, and no unresolved routing. Existing hand-drawn demos are diagnostic comparisons only; a stricter new wire policy must not be mistaken for evidence that a valid demo is incorrect.

## Milestone 3 Prove the result in PLECS and document it

### Step 8 Build a synthetic acceptance set

Files: an authored controller example under `skills/plecs-layout/scripts/`, focused test fixtures, and `tests/test_plecs_integration.py`.

Cover a simple chain, feedback loop, dense fanout, multiport C-Script, unequal-size subsystems, long names, and duplicate local tag names in separate subsystems. Use small deterministic simulations with declared numerical tolerances and a semantic reference that does not depend on the new placer.

For each representative layout, retain the generated model, diagnostic preview, report, and actual PLECS export/capture for comparison. Record PLECS version and compare at the same scale. Verify readable names, clear topology, separated routes, and correct port alignment in the application.

Acceptance: all automated gates pass and the actual drawing is visually acceptable. If PLECS is unavailable, report this milestone as unverified; skipped integration tests are not completion. Adapt the user's real schematic only after locating it and establishing its unchanged simulation baseline. Keep any client fixture and outputs in that project's repository.

### Step 9 Update usage guidance

Files: `skills/plecs-layout/SKILL.md`, `references/conventions.md`, `README.md`, and the controller design where this plan proposes refinements.

Explain how to choose controller versus electrical layout, supply geometry and hints, run scoring and previews, and interpret unsupported geometry. Correct stale claims that all terminals use centres or tags occupy no space. Define completion as passing correctness checks plus PLECS verification, rather than merely obtaining clean lint.

Acceptance: documented examples run using `python scripts/<name>.py`; all four skills validate; no agent-specific tools or third-party runtime dependencies appear in shipped skills.

## Milestone 4 Improve power schematics separately

Begin after the shared geometry and validation work is stable. Select one authored representative topology rather than building a general optimizer immediately. A three-phase source and series impedance feeding a rectifier/DC link is a candidate, not yet a chosen acceptance target.

Use explicit topology roles for phase rows, bridge legs, rails, shunt components, measurement taps, and loads. Preserve visible main power paths. Reuse Ground conventions and allow electrical Labels for remote connections without replacing every rail with labels. Prefer hints/templates over attempting to infer all circuit intent from connectivity.

Acceptance: topology is recognizable in PLECS, phase rows and rails align, no collisions occur, and simulation behavior matches the original. This milestone needs its own topology-specific fixture and detailed implementation breakdown after the representative schematic is selected.

## Optional comparisons after the first working result

Use ELK only as a maintainer-side benchmark with the same synthetic graphs, fixed ports, and label dimensions. It must not become a dependency under `skills/`. Pin its version and compare only candidates that pass the same correctness gates. Test an optional one-clean-elbow policy separately from the approved straight-or-tag policy. Consider libavoid only if routing remains the limiting factor after placement is improved.

These experiments do not block the controller milestone and do not justify rewriting the working router in advance.

## Execution and validation

The numbered steps above describe design scope, not commit boundaries. Follow the smaller execution tasks below. Write a failing regression immediately before its fix and verify the failure, but keep both in the same passing change. Do not commit a standalone red-test step. Every commit must pass the repository's skill validation and test requirements. Do not commit automatically as part of writing or executing this plan unless the user requests commits.

Use the external Python environment already created for this repository:

```powershell
D:\codex-envs\plecs-expert-skill\Scripts\python.exe -m pytest -q
Get-ChildItem skills -Directory | ForEach-Object {
    & D:\codex-envs\plecs-expert-skill\Scripts\agentskills.exe validate $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "Skill validation failed: $($_.FullName)" }
}
```

Run focused regressions during implementation and the full suite before each commit. Inspect the staged file list for client material, Plexim material, and generated calibration products. Preserve existing local outputs; this plan authorizes no deletion or cleanup.

## Concrete contracts for implementation

These are planned interfaces, not APIs that already exist. Add them only in the task that needs them.

- Preserve existing `geometry.shape` and `Shape.measured` callers. Use the resolved `Shape.measured` value as the source of truth. If retaining `is_measured(kind)` for compatibility, document it as table-kind presence only and remove it from acceptance decisions. Coverage diagnostics must include component name, kind, variant, direction and flip.
- Add `geometry.component_shape(component)` for a parsed `plecs_file.Block`, sharing parameter extraction with lint/preview. Ordinary blocks delegate to `shape`; supported subsystem frame/port records use the verified adapter. Do not invent serialized field names: derive them from an inspected authored PLECS fixture before implementing that branch.
- Add `Sheet.add_component(component, *, at=None, direction=None, flipped=None)` to copy and serialize a parsed Component while preserving all other fields and nested children. Reuse existing name-uniqueness checks and component-before-connection ordering. Compare parsed structure before/after, excluding only allowed layout fields, to protect C-Script code, subsystem contents and Scope configuration. It need not preserve whitespace byte for byte.
- Extend `Part`/`Netlist.part` with an optional parsed `component` template, appended without changing existing positional arguments. Copy templates before editing. Existing `params` must agree with a supplied template or be rejected; do not silently choose between two conflicting parameter sources. The template's Name and Type must match the part identity.
- Add `blockdiagram.layout(netlist, *, zones=None, max_wire=150, grid=5)` returning `(sheet, report)`. The first version supports `grid=5` only and rejects other values rather than rounding terminals independently. Preserve original netlist/template contents. On unsupported geometry or conflicting constraints, raise a dedicated `LayoutError` with attributable findings; never return a supposedly usable partial controller sheet.
- Keep the existing `check_connectivity(text, nl)` list-of-findings contract. Add optional sheet-path context only when hierarchical fixtures require it. Controller layout operates on one selected sheet at a time; it does not flatten subsystems. Local scope must work first. Global tag resolution and interface traversal require the hierarchy task; unsupported cases must produce findings, not guessed equivalence.
- Add `score(model_text, netlist, *, max_wire=150)` in `score.py`. Return a dictionary containing `counts`, `weighted_total`, `findings`, `coverage`, `connectivity`, `unrouted`, `metrics`, and `accepted`. `accepted` is true only for score zero, complete supported coverage, no connectivity differences, and no unresolved routing. Reuse this dictionary in the layout report under `quality`; retain the familiar `routed`, `tagged`, `unmeasured`, and `unrouted` layout keys.

For cycle breaking, use depth-first traversal in component-name order and successor-name order; mark edges to nodes currently on the traversal stack as feedback, including self-loops. Longest-path layering then runs on the remaining DAG with name-ordered topological ties. Run four barycentre sweeps, with component-name tie-breaking. This is a deterministic initial policy, not a claim of optimal feedback selection.

For hints, preserve fixed `at` positions; reject off-grid coordinates before silently snapping in the new controller API. Row/column hints constrain automatic slots. If a fixed position and hint disagree with the computed slot, report a conflict. Duplicate occupied hints also report a conflict. Do not change the legacy API's snapping behavior in the same task.

For text, initially support the controller examples' plain single-line names and tag strings with an explicit conservative width/height estimate. Treat calibration of the estimate as part of PLECS verification. Multiline, special formatting, or shown parameter text outside supported measurement rules must generate coverage findings; do not claim that arbitrary PLECS text has been validated. Keep stricter generated-controller checks separate from legacy lint policy where existing diagrams legitimately rely on PLECS-generated bends.

## Luna xhigh execution tasks

Use one task per implementation turn. The dependency column is mandatory. Every row inherits the file scope and acceptance criteria of its referenced design step; do not expand into a neighboring task just to make the report look complete. New tests below are proposed test names, not claims that those files already exist.

| Task | Depends on | Deliverable and specific verification |
|---|---|---|
| L01 | None | Steps 1/2: fix calibrated C-Script lookup and truthful variant coverage only. Add `test_cscript_calibrated_variant_has_terminals` and `test_known_kind_unknown_variant_is_unmeasured` in `tests/test_geometry.py`. Use the existing table as the expected source; no parametric extrapolation yet. |
| L02 | L01 | Protect Claude's electrical behaviors in `tests/test_autolayout.py`: series-chain row alignment, shunt orientation, Ground connectivity and one Label per zone. Add behavioral cases only where existing tests do not already cover them. Production changes are limited to regressions actually exposed by L01. |
| L03 | L01 | Step 3 body checks only: measured rectangle overlap and explicit terminal-leg checks. Reproduce the Gain overlap. Add rotated and endpoint-contact cases. Preserve legacy inferred-bend behavior; expose strict checks for later controller scoring. |
| L04 | L01 | Step 2 C-Script rule: inspect calibration generator and available local evidence; implement scalar/vector/zero-port parsing and only evidenced geometry. Add tests for scalar width `7` versus `[1 1 1]` and unresolved expressions. If rule evidence is insufficient, retain table-only support and record the blocked extension. |
| L05 | L01 | Steps 2/5 payload adapter: implement `Sheet.add_component` and optional part templates. Add parsed round-trip tests for nested subsystem content and C-Script parameters. Inspect one authored subsystem fixture, then add the frame/port geometry adapter and independent expected coordinates. Do not guess missing PLECS fields. |
| L06 | L01, L02 | Step 4 single-sheet connectivity: preserve signal direction and net kind, find extra/joined/split nets and duplicate drivers/attachments. Keep helper-terminal projection explicit. Test faults by editing emitted models independently of the generator. |
| L07 | L06 | Step 4 forced signal tags only: one source Goto and one receiver From, same-zone and cross-zone cases. Run electrical tag-policy regressions from L02. Do not rewrite automatic electrical routing. |
| L08 | L03 | Step 3 text envelopes and preview: shared plain-text estimates, visible tag strings and occupied-box diagnostics. Add long-name collision and hidden-name cases. Unsupported text gets a coverage finding. No generic font/rendering engine. |
| L09 | L04, L05, L08 | Step 5 placement only: implement the graph ordering, fixed orientation and envelope spacing helpers, with expected layer/coordinate assertions. Test cycles, disconnected blocks, unequal sizes and conflicting hints. Do not export the public successful-layout path until L10/L11 can verify it. |
| L10 | L07, L09 | Step 6 emission: straight-clear-short connections, whole-net fanout policy, tags and reserved space. Test one connection tree per driver terminal, same-zone fanout, feedback and `max_wire=0`. Reject final conflicts instead of adding layout retries. |
| L11 | L03, L06, L08, L10 | Step 7 score and accepted status; expose the public controller API. Inject one fault per score category. Repeat layout twice and compare serialized outputs and unchanged input objects. The accepted check must fail for unknown geometry and unrouted output independently of score. |
| L12 | L05, L06, L11 | Step 4 hierarchical verification: sheet paths, local-name reuse, explicit global tags and preserved subsystem interfaces. Add authored nested fixtures. Unsupported masked/code-generation scope remains an explicit finding until separately verified. This task does not introduce automatic boundary crossing. |
| L13 | L11, L12 | Step 8 authored example plus actual PLECS load/simulation and capture. Set fixture-specific tolerances before comparing outputs. Check visual text estimates; fix discrepancies in their owning modules and rerun affected tests. Missing PLECS leaves this task incomplete, not passed. |
| L14 | L13 | Step 9 documentation and spec refinements. Run every documented example, all tests and all four skill validations. Record remaining unsupported geometry and the exact PLECS version tested. |

L04 and L05 contain evidence prerequisites that code-only work cannot remove. If a prerequisite is missing, record precisely what fixture or measurement is needed and continue only independent tasks; do not replace the measurement with a plausible formula. L09 cannot be declared complete until its dependencies actually pass.

For each task, use the Python executable in the validation section. Run the focused files first, then the full suite before a commit or completed task handoff. For example, L01 runs:

```powershell
D:\codex-envs\plecs-expert-skill\Scripts\python.exe -m pytest -q tests/test_geometry.py tests/test_autolayout.py
```

Maintain progress beneath this plan or in the implementation chat with: task ID, modified files, focused/full test results, skill-validation results, remaining evidence gaps, and next eligible task. Never mark a visual/simulation gate complete because unit tests passed. No task requires another agent, an issue-tracker write, an external layout engine, a cleanup, or an automatic commit.

### Copyable execution prompt

```text
Implement the next eligible Luna xhigh task from
docs/plans/2026-10-02-schematic-layout-implementation.md.
Start with L01 if none is recorded complete. Read AGENTS.md and the plan's
Claude-continuity table, contracts, task dependencies and relevant design step.
Preserve Claude's existing electrical behaviors and public APIs. Use the
external Python environment named in the plan. Write the focused failing
regression, verify it fails for the intended reason, apply the smallest fix,
then run focused tests, the full suite and all four skill validations.
Do not implement future tasks, guess missing measured geometry, commit, or
delete files. Report evidence and the next eligible task. If blocked on
PLECS evidence, record the exact missing prerequisite rather than claiming
the task is done.
```

The first implementation slice is L01. Success for the controller milestone requires L01 through L14, including real PLECS verification. Power-stage improvement is a follow-up requiring a separate executable task breakdown after selecting its representative schematic; the broad Milestone 4 description is not yet a Luna execution task. External benchmarks remain optional.

## Closure plan for the remaining gates

The Subsystem adapter is implemented for its verified record form, but independent displayed-
coordinate evidence for L05 and the native visual acceptance evidence for L13 remain open. Close
them in this order; L09-L12 must then be rechecked because they depend on L05. Do not mark the
controller milestone complete until the evidence and acceptance checks below are recorded.

### C1 — Close L05 with measured Subsystem geometry

1. Read-only search the installed PLECS 4.9.8 examples for an authored `.plecs` file containing
   a Subsystem with visible input/output ports and a nested Schematic. Do not copy the demo model
   or its manual text into this repository. If no suitable fixture exists, author a minimal,
   synthetic Subsystem fixture in PLECS and keep the generated model outside the repository.
2. Load the fixture in PLECS at a recorded zoom. Record the Subsystem frame bounds and each
   visible port's terminal coordinate independently from the serialized fields. Preserve the
   source fixture's exact path and the measurement notes in the task report; do not infer field
   names or coordinates from the desired adapter output.
3. Implement the `component_shape` Subsystem adapter only from the inspected serialization and
   measured coordinates. Add a synthetic regression fixture with fixed expected bounds and port
   coordinates, plus round-trip assertions that nested content and interface parameters are
   preserved. Exercise the adapter through lint, preview and controller geometry validation.
4. Run the focused geometry/template tests, the full test suite and all four skill validators.
   Record the fixture source, PLECS version, independent expected coordinates and exact results.
   If neither an authored fixture nor a way to measure a synthetic one is available, stop this
   adapter task and leave L05 open with that artifact requirement.

### C2 — Close L13 with a retained PLECS drawing capture

1. Generate the accepted synthetic controller `.plecs` and SVG preview with the documented CLI.
   Call `example_blockdiagram.controller()` from a short capture helper to also serialize its
   report as JSON. Keep these generated models and captures outside the repository, for example
   under `D:\codex-envs\plecs-expert-skill\evidence\2026-10-02-layout-review\`.
2. Open that exact model in PLECS Standalone 4.9.8. Record the zoom and use a measured symbol
   dimension to convert screen pixels back to schematic coordinates. Capture the complete sheet
   with component names, tag strings and shown parameter text visible. Retain the screenshot and
   the coordinate measurements with the external evidence files.
3. Compare the observed text bounds against the 8 px-per-character, 12 px line-height estimate.
   Record the comparison and tolerance before deciding whether to change the estimate. If any
   text collides or exceeds the recorded tolerance, update the owning geometry/lint/preview code,
   conventions and regression tests, then recapture. Do not use simulation success as visual
   evidence.
4. Load and simulate the final generated model in PLECS. Record the model identifier, output
   value, expected value, tolerance and PLECS version alongside the capture.

If the current execution environment cannot retain a native PLECS window capture, prepare the
model and preview, then ask for a screenshot captured from PLECS at the recorded zoom. Keep L13
partial until that image and its scale/text measurements are available.

### C3 — Revalidate dependent tasks and close L14

After C1 passes, rerun L09-L12's focused placement, emission, scoring and hierarchy regressions
against the new Subsystem geometry. After C2 passes, rerun both documented examples, `pytest -q`,
all four `agentskills validate` commands and `git diff --check`. Update the execution record with
the fixture/evidence locations, visual measurements, simulation result, test count and any
remaining unsupported cases. Mark L05, L09-L13 and L14 complete only after their dependencies
and evidence checks pass. The power-stage follow-up remains outside this closure sequence.

## Remaining implementation sprints and merge gates

Each sprint is reviewed by GPT Sol against `main`. A sprint is committed and merged to `main`
only after that review reports no blocking findings and its exit checks pass. Generated PLECS
models, captures and simulation output stay outside the repository.

### Sprint 1 — Merge the implemented layout slice

Scope: the L01–L12 implementation and its regression suite, including independent quality gates
for orthogonal bends, displayed-text collisions, `max_wire=0` tag coverage, 40 px reserved column
gaps, and declared versus undeclared tag names. Reconcile the implementation notes and record the
verification results in this plan. Exit checks: focused and full pytest, all four skill validators,
documented API/CLI examples, `git diff --check`, and GPT Sol review of the full diff against `main`.
Merge this sprint with a fast-forward only after GPT Sol approves it.

### Sprint 2 — Complete PLECS evidence for C1 and C2

For C1, use the installed `enabled_subsystem.plecs` fixture, record its PLECS version and zoom,
and measure its frame and numbered terminal offsets from the GUI display independently of the
parser. Keep the fixture itself outside the repository. For C2, load and capture the authored
synthetic controller at a recorded zoom; measure displayed text bounds in screen pixels and map
them to schematic units using the visible grid or known component coordinates. Compare the values
with the documented 8 px-per-character and 12 px line-height estimates. Also load, simulate and
retain captures/results for representative feedback and unequal-size Subsystem layouts. If the
measurements expose a code or convention error, add a regression, update the implementation, and
rerun Sprint 1 checks. Exit only with external captures, measurement notes and simulation results
that identify PLECS version, model, zoom, expected value and tolerance. Have GPT Sol review the
evidence update and any code diff before merging the sprint.

### Sprint 3 — Close L13 and L14

Recheck L09–L12 placement, emission, scoring and hierarchy behavior against the measured
Subsystem fixture. Rerun both documented examples, `pytest -q`, all four skill validators and
`git diff --check`; update the execution record with final evidence paths, text measurements,
simulation outcomes, test count and remaining unsupported cases. Mark L05 and L09–L14 complete
only where their listed evidence exists. GPT Sol reviews the closure diff; merge it to `main` only
after approval. Power-stage work remains outside this plan.

## Execution record (2026-10-02)

| Tasks | Status | Evidence / remaining work |
|---|---|---|
| L01-L04 | Implemented | Calibrated C-Script variants, truthful coverage, electrical regression protection, rectangle/terminal-leg checks, and scalar-width/vector-port parsing. Uncalibrated counts and expressions remain unsupported. |
| L05 | Adapter implemented for the verified record form; independent GUI measurement pending | `component_shape` reads an explicit Subsystem `Frame` and ordered `Terminal Position` records for `Direction up`, `Flipped off`; lint, preview, controller placement/scoring and round-trip tests cover it. PLECS 4.9.8 model-tree values are recorded below, but the required screen-coordinate measurement against the displayed frame and ports is not yet retained. Other transforms and incomplete records remain unsupported. |
| L06-L08 | Implemented | Connectivity difference checking, same-zone forced signal tags, text envelopes and preview reservations have regression coverage. |
| L09-L11 | Implemented; dependent regressions rechecked | Deterministic controller placement, straight-wire/tag emission, report scoring and strict `accepted` status are integrated, including the verified Subsystem template form. Placement geometry uses the resolved controller orientation before reserving space; a right-oriented C-Script template regression verifies normalization to up. A connected four-port C-Script and unequal-size Subsystem chain pass layout checks. If forced local tags on adjacent multiport terminals overlap, layout raises `LayoutError` with `tag_spacing_conflict`; it does not return a colliding sheet. |
| L12 | Implemented with stated limits | Nested sheet paths and local/global tag scopes are checked. Masked/code-generation visibility and automatic subsystem boundary traversal remain unsupported. |
| L13 | Partial | The single-channel synthetic controller and connected two-channel C-Script controller were loaded and simulated in PLECS Standalone 4.9.8; final outputs were `1.0` and `[1.0, 2.0]`, respectively, within `1e-6` absolute tolerance. Sprint 2 also retained PLECS simulations for feedback and unequal-size Subsystem models. Their native GUI captures and screen-scale text comparisons remain outstanding, so visual acceptance is open. |
| L14 | Documentation complete; visual gate pending | README, skill usage, conventions and controller spec were updated. The API and CLI examples rerun on 2026-10-03 both returned accepted/quality 0. The latest full suite passed (127 tests); all four skill validations and `git diff --check` passed. The controller milestone remains open until the required PLECS captures and text-scale checks are recorded for representative layouts. |

### Closure evidence (2026-10-02)

- **C1 / L05:** Inspected the installed fixture at
  `D:\OneDrive\Documenti\Plexim\PLECS 4.9 (64 bit)\examples\component_help\enabled_subsystem.plecs`
  in PLECS Standalone 4.9.8. Its PLECS model tree reported Zoom Factor `1.00677` and, for
  `Offset calibration` at `(205, 450)`, Frame `(-25, -15; 50x30)`. PLECS reported terminals in
  connection order: 1 Input `(-25, 0)` / left, 2 Output `(29, 0)` / right, 3 Input `(0, -15)` /
  up. Absolute expected coordinates are frame `(180, 435)`–`(230, 465)` and terminals
  `(180, 450)`, `(234, 450)`, `(205, 435)`. The GUI showed the corresponding left, right and upper
  ports. These expected values came from PLECS's loaded model tree, independently of the parser
  assertions. The demo model itself was not copied into the repository.
- The adapter deliberately accepts only `Direction up`, `Flipped off`; it reads terminal offsets
  in record order and does not infer geometry from nested sheet contents. Regression tests assert
  frame bounds, terminal coordinates, explicit rejection of unsupported variants, preview/lint
  geometry, controller validation, and template round-trip preservation.
- **C2 / L13:** External evidence is in
  `D:\codex-envs\plecs-expert-skill\evidence\2026-10-02-layout-review\`:
  `synthetic_controller.plecs`, `synthetic_controller.svg`,
  `synthetic_controller.report.json`, and `synthetic_controller.simulation.json`. PLECS load
  returned `0`; simulation output was `1.0`, expected `1.0`, absolute tolerance `1e-6`.
  `documented_cli_example.plecs` and `.svg` also came from the documented CLI. The retained GUI
  capture and text-bound comparison are still outstanding: the desktop capture stopped showing
  the PLECS window while restoring it, so the user was asked to bring the model forward or provide
  a screenshot. No screen-pixel measurements are claimed.
- **C3:** After the adapter change, the focused placement/emission/scoring/hierarchy/geometry set
  passed (93 tests). The full suite passed (105 tests), the API and CLI examples both reported an
  accepted score of zero, all four `agentskills validate` commands passed, and `git diff --check`
  found no whitespace errors. The user-requested visual gate is the only remaining closure item.

### Execution update (2026-10-03)

- Fixed controller placement to reserve bodies, terminals and candidate tags using the resolved
  fixed orientation. Parsed C-Script templates may carry `Direction right`; the controller path
  emits and lays them out as `Direction up`. Subsystem templates still require the measured
  serialized `Direction up`, `Flipped off` form. A regression test exercises the stale-orientation
  case and checks the accepted result's emitted geometry.
- Added an unequal-size Subsystem chain placement regression and an accepted connected four-port
  C-Script layout case. Added `multiport_controller()` as a synthetic two-channel example with a
  deterministic identity mapping. PLECS Standalone 4.9.8 loaded and simulated it with final outputs
  `[1.0, 2.0]`, expected `[1.0, 2.0]`, and absolute tolerance `1e-6`.
- The multiport model, SVG, layout report, simulation result, and documented CLI model/preview are
  retained in `D:\codex-envs\plecs-expert-skill\evidence\2026-10-03-layout-review\`.
- Verification: `pytest -q` passed (110 tests, including the live PLECS integration tests); all
  four skill validators passed; the documented API returned accepted/score 0; the documented CLI
  returned accepted/quality 0; `git diff --check` reported no whitespace errors and the existing
  CRLF warning for `autolayout.py`.
- Remaining L13 work at that point: retain PLECS GUI captures and screen-to-schematic text
  measurements for representative layouts. Sprint 2 later added retained PLECS simulation
  evidence for feedback and unequal-size Subsystem layouts; their GUI captures and text measurements
  remain open. Keep L13 and dependent L14 partial until those artifacts and visual checks are complete.

### Execution update (2026-10-03, Sprint 1 approved and merged)

- GPT Sol's independent merge review found four acceptance gaps: orthogonal bends, wires through
  displayed text, untagged direct connections under `max_wire=0`, and column snapping below the
  reserved 40 px gap. Each now has a regression and a corresponding implementation fix. The
  follow-up also found tag-name bypasses in stub scoring; undeclared/ambiguous tag names are now
  rejected while both a logical net's name and its explicitly declared alias resolve to that net.
- The scoring table now documents the text-wire, missing-tag and unknown-tag gates. The documented
  API example and CLI example both report accepted quality `0`; the CLI model and SVG are retained
  outside the repository as `documented_cli_example-final.plecs` and `.svg`.
- Latest verification before merge: `pytest -q` passed (119 tests); all four skill validators
  passed; `git diff --check` found no whitespace errors and reported the existing `autolayout.py`
  CRLF warning. GPT Sol approved the full candidate against `main` at `6e400aa`; `a3d5ce7` was
  the feature branch's preceding HEAD. Commit `56a823a` was fast-forwarded into local `main`.
- A PLECS 4.9.8 GUI screenshot of the installed `enabled_subsystem` fixture is retained outside
  the repository as `enabled_subsystem-plecs-ui.jpg`. The capture does not yet establish
  independent screen-coordinate frame/terminal measurements. The synthetic-controller PLECS
  capture and screen-scale text measurement remained outstanding at Sprint 1 completion. Feedback
  and unequal-Subsystem simulation/capture evidence is recorded in the following update. Keep
  L13/L14 partial until the visual captures and text measurements are complete.

### Execution update (2026-10-03, Sprint 2 implementation slice merged; visual gate open)

- Corrected the authored Subsystem fixture to use the measured output terminal offset beyond the
  frame. Preserved exact 20 px orthogonal tag stubs for off-grid measured ports by serializing
  generated Goto/From positions at their required coordinates. The linter allows an off-grid
  generated tag position only when a Signal connection joins it to one component terminal through
  exactly one 20 px orthogonal leg; arbitrary off-grid tags remain errors.
- Added authored feedback and unequal-size Subsystem controller examples with unit and PLECS
  integration tests. PLECS Standalone 4.9.8 loaded and simulated both: the unequal Subsystem chain
  returned `6.0` (expected `6.0`), and the closed-loop integrator returned `0.9932620530009163`
  at 5 s (expected `1 - exp(-5) = 0.9932620530009145`); both use absolute tolerance `1e-6`.
- Models, SVG previews, layout reports and simulation results are retained outside the repository
  under `D:\codex-envs\plecs-expert-skill\evidence\2026-10-03-layout-review\` with basenames
  `unequal_subsystem_controller` and `feedback_controller`.
- Focused verification passed: `pytest -q tests/test_blockdiagram.py tests/test_lint.py
  tests/test_plecs_integration.py` (62 passed, including the live PLECS simulations). The standards
  review tightened the generated-tag name check, confined exact-position serialization to the
  internal generated-tag path, documented its reserved names and narrow exception, and added
  reserved-prefix and name/type mismatch regressions. After that review follow-up, `pytest -q`
  passed (127 tests), all four skill validators passed, the documented API and CLI examples
  returned accepted/quality `0`, and `git diff --check` passed. GPT Sol approved the implementation
  slice against `main` at `56a823a`; commit `1f1b993` was fast-forwarded into local `main`. The
  standards review found no blockers. This implementation merge does not close the separate
  C1/L13/L14 visual gates.
- CUA reports no native app surfaces, so no native PLECS screenshot or screen-to-schematic text
  measurement was captured. The user has been asked to attach the `enabled_subsystem` properties
  view and full-sheet captures of the synthetic, feedback and unequal-Subsystem models. A blank
  worksheet with model paths, expected coordinates, scale conversion and text-bound fields is
  prepared at `D:\codex-envs\plecs-expert-skill\evidence\2026-10-03-layout-review\visual-measurement-worksheet-2026-10-03.md`.
  L05 and L13/L14 remain partial until those visual checks are recorded.

The power-stage improvement remains the separate follow-up described above. No Plexim demos, client models/data or generated calibration products were added.
