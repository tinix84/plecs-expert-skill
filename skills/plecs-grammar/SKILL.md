---
name: plecs-grammar
description: Use when reading, parsing, generating, diffing, or hand-editing the text of a PLECS .plecs model file — the curly-brace Plecs/Schematic/Component/Connection format with Position, Direction, Flipped, Parameter, Points, Branch, and Terminal blocks.
license: MIT
metadata:
  author: tinix84
  repository: https://github.com/tinix84/plecs-expert-skill
---

# PLECS file grammar

A `.plecs` file is not XML. It is nested `Key value` text with `Name { ... }` sub-blocks. The full element table, a trimmed example file and parser notes are in `references/plecs-xml-grammar.md`.

## Quick reference

| Element | Meaning |
|---------|---------|
| `Plecs { }` | File root: model name, version, solver settings, `InitializationCommands`, `Schematic` |
| `Schematic { }` | `Location`, `ZoomFactor`, then `Component` and `Connection` children |
| `Component { }` | `Type`, `Name`, `Show`, `Position [x, y]`, `Direction`, `Flipped`, `LabelPosition`, `Parameter { Variable Value Show }` |
| `Connection { }` | `Type Signal` or `Type Wire`, `SrcComponent`, `SrcTerminal`, optional `Points [x1, y1; x2, y2]`, then `DstComponent`/`DstTerminal` or one or more `Branch { }` |
| `Branch { }` | T-junction child of a connection; same fields as a connection |

## Rules when writing files

- Quote every string value as PLECS does; keep numeric expressions as strings (`"2*pi*50"`).
- Component `Name` values must be unique inside one schematic level.
- Inside a `Schematic`, write every `Component` before the first `Connection`. A Component after a Connection is a syntax error in PLECS 4.9.
- A `Branch` does not repeat its parent's `Type`; it inherits `Wire` or `Signal` from the connection it belongs to.
- A connection without `Points` is drawn as a straight line between terminals. For a readable drawing, use the `plecs-layout` skill.
- After generating a file, open it once in PLECS (GUI or XML-RPC `plecs.load`) to confirm it parses.
