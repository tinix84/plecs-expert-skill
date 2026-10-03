# plecs-expert-skill

Agent Skills for working with [PLECS](https://www.plexim.com/products/plecs) models. They follow the open [Agent Skills specification](https://agentskills.io/specification), so the same folders work in Claude, Claude Code, ChatGPT/Codex, Gemini CLI, GitHub Copilot and other compatible agents.

| Skill | Use it for |
|-------|-----------|
| `plecs-expert` | Entry point: picks the right PLECS skill; solver, C-Script, XML-RPC and code-generation references |
| `plecs-grammar` | Reading and writing `.plecs` file text |
| `plecs-components` | Component parameters, terminals and probe signals |
| `plecs-layout` | Readable schematics: zones, Goto/From and electrical Label tags, routed wires, automatic placement and routing, lint |

The `plecs-layout` scripts need Python 3.10 or later and use the standard library only. Loading or simulating models needs PLECS 4.7 or later with XML-RPC enabled.

## Install

**Claude Code** (plugin):

```
/plugin marketplace add tinix84/plecs-expert-skill
/plugin install plecs-expert@plecs-expert-skill
```

**Codex, Gemini CLI, GitHub Copilot CLI** (these read `~/.agents/skills`), or **Claude Code without the plugin**:

```
git clone https://github.com/tinix84/plecs-expert-skill
python plecs-expert-skill/tools/install.py                  # ~/.agents/skills
python plecs-expert-skill/tools/install.py --target claude  # ~/.claude/skills
```

For a single project, install into its skill folder instead: `--dest <project>/.agents/skills`.

**Claude.ai and other apps that take skill archives:** run `python tools/package.py` and upload a zip from `dist/`.

## Repository layout

```
skills/            the skills; nothing here is specific to one agent
.claude-plugin/    Claude Code plugin and marketplace manifests
tools/             install.py, package.py
maintainer/        docs-sync tools, PLECS geometry calibration
tests/             unit tests; PLECS integration tests run when PLECS is up on localhost:1080
```

## Layout modes

`plecs-layout` has two explicit paths. Use the existing electrical `Netlist.layout()` for
power circuits, where the router preserves rails, Ground splitting and electrical Labels. Use
`blockdiagram.layout()` for a controller sheet made from measured signal blocks, where short
clear straight wires stay as wires and other signal connections use Goto/From tags.

Generate the synthetic controller and its diagnostic SVG with:

```powershell
python skills/plecs-layout/scripts/example_blockdiagram.py --out controller.plecs
```

For an authored model, run from `skills/plecs-layout/scripts` (or put that directory on
`PYTHONPATH`), build the existing `Netlist`, add signal nets with the driver first, then call
the controller path:

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

The controller path places blocks and route points on a 5 px grid and requires fixed input
coordinates to align to that grid. The reserved `__blockdiagram_<net>_goto` and
`__blockdiagram_<net>_from_<receiver>` names identify generated tags, which may sit off-grid only
to preserve an exact 20 px orthogonal port stub. The path resolves geometry from measured variants
or explicit parsed component records, and rejects unknown geometry or port roles. It reports lint,
connectivity, routing, coverage and drawing metrics separately. C-Script parameters must resolve
to a calibrated variant; parameter expressions are unsupported. A Subsystem template must carry
valid `Frame` and ordered `Terminal Position` records and currently must use `Direction up` and
`Flipped off`; pass the parsed `Component` as `component=` to `Netlist.part` so the interface and
nested sheet are preserved. Missing fields and other Subsystem orientations remain unsupported.
Adjacent multiport terminals that need overlapping local tags raise `LayoutError` with
`tag_spacing_conflict`; direct wires remain eligible. To lay out a C-Script that carries code,
pass its parsed `Component` as `component=` and matching parameters to `Netlist.part`; this
preserves its function fields. `accepted` also requires no
estimated text collisions or unresolved routing. Text estimates assume plain single-line text
at 8 px per character and 12 px line height; inspect the exported `.plecs` drawing in PLECS
before relying on it. The integration test simulates the synthetic controller when PLECS XML-RPC
is available at `localhost:1080`.

## Development

```
pip install pytest skills-ref
for d in skills/*/; do agentskills validate "$d"; done
pytest -q
```

The skills were moved from [pyplecs](https://github.com/tinix84/pyplecs), which remains the Python tool they call when it is installed. Plexim documentation is cited, not copied; see `LICENSE-NOTES.md`.
