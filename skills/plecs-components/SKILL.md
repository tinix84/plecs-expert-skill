---
name: plecs-components
description: Use when choosing, configuring, or wiring a PLECS component and its parameter names, defaults, units, terminals, or probe signals are needed — resistors, inductors, capacitors, transformers, voltage and current sources, MOSFET, IGBT, diode, switches, meters, scopes, control blocks, thermal and magnetic blocks, subsystems and masks.
license: MIT (skill text). Parameter tables are facts from docs.plexim.com, see LICENSE-NOTES.md in the repository.
metadata:
  author: tinix84
  repository: https://github.com/tinix84/plecs-expert-skill
---

# PLECS components

Parameter and probe tables for common PLECS components, mirrored from docs.plexim.com and kept in sync by the repository's `maintainer/` tools.

## Where to look

| Components | File |
|------------|------|
| Resistor, inductor, capacitor, transformer | `references/electrical-passive.md` |
| AC/DC voltage source, controlled voltage and current source | `references/electrical-sources.md` |
| MOSFET, IGBT, diode, ideal switch | `references/electrical-switches.md` |
| Voltmeter, ammeter, scope | `references/electrical-meters.md` |
| Magnetic permeance, MMF source, flux-rate meter | `references/magnetic.md` |
| Heat sink, thermal capacitor, ambient temperature | `references/thermal.md` |
| PID, transfer function, state machine and other control blocks | `references/control.md` |
| Subsystem, configurable subsystem, masks | `references/system.md` |

A component not listed: fetch `https://docs.plexim.com/plecs/latest/components-by-category/<type-lowercase>/`.

## Rules

- Use the exact `Variable` names from the tables as `Parameter` keys in a `.plecs` file; the GUI labels differ.
- Parameter values are strings holding MATLAB/Octave expressions; they may reference variables defined in the model's `InitializationCommands`.
- When `pyplecs` is installed, a `*PlecsMdl` wrapper class in `pyplecs.plecs_components` is the preferred way to build a component programmatically.
