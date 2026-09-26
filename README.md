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

## Development

```
pip install pytest skills-ref
for d in skills/*/; do agentskills validate "$d"; done
pytest -q
```

The skills were moved from [pyplecs](https://github.com/tinix84/pyplecs), which remains the Python tool they call when it is installed. Plexim documentation is cited, not copied; see `LICENSE-NOTES.md`.
