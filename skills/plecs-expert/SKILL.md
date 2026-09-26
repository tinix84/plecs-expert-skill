---
name: plecs-expert
description: Use when a task involves PLECS (Plexim) power-electronics simulation in any way — reading, generating, editing, laying out, scripting, or testing .plecs models, PLECS C-Script blocks, the PLECS XML-RPC interface, solver settings, or PLECS Coder — and it is not yet clear which PLECS skill applies.
license: MIT (skill text). Plexim documentation facts are cited, see LICENSE-NOTES.md in the repository.
metadata:
  author: tinix84
  repository: https://github.com/tinix84/plecs-expert-skill
  plecs-version: "4.7-4.9"
---

# PLECS Expert

Entry point for the PLECS skill family. Pick the sibling skill for the task, then follow it.

## Routing

| Task | Skill |
|------|-------|
| Read or write `.plecs` file text: blocks, keys, `Component`, `Connection`, `Points`, `Branch` | `plecs-grammar` |
| Component parameters, terminals, probes (R, L, C, sources, switches, meters, control, thermal, magnetic, subsystems) | `plecs-components` |
| Generate or tidy a schematic so it is readable: placement, Goto/From tags, electrical labels, wire routing, lint | `plecs-layout` |
| Solver settings and tolerances | `references/solver.md` |
| C-Script block | `references/cscript.md` |
| XML-RPC scripting (`plecs.simulate`, `plecs.set`, `plecs.get`) | `references/rpc-api.md` |
| PLECS Coder / code generation | `references/codegen.md` |
| Anything else | `references/url-index.md`, then fetch the listed docs.plexim.com page |

If a sibling skill is not installed, its reference files are in the same repository under `skills/<name>/references/`.

## Python tooling (optional)

When the `pyplecs` package is installed, prefer its wrappers: `pyplecs.plecs_components` for component classes and `pyplecs.pyplecs.PlecsServer` for XML-RPC. Otherwise use the reference files.

## Citation rule

Every factual answer cites a reference file path or a docs.plexim.com URL. No ungrounded claims about PLECS behaviour.

## Style

Generated prose follows `style/caveman.md`: fragments are fine, no filler.

## Out of scope

PLECS RT Box, licensing and purchasing, third-party libraries.
