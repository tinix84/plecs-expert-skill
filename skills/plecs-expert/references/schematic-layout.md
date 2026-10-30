# Schematic layout - writing readable `.plecs` files by hand or by script

Lessons from rebuilding two PLECS 4.9 models by script (buck-type active ripple compensator and DC-link voltage balancer, 2026-10-30). Model simulated right from the first run; schematic looked broken. Cause and fix below, then a checklist.

## Failure seen

- Wires ran to sheet corner (0,0), crossed source symbols, blocks sat off-sheet left. Electrically correct: results identical before and after cleanup. Readability only.
- Root cause 1: `Connection` with several `Branch` children but no `Points` for the branch node. PLECS puts missing node at (0,0) and draws every branch from there.
- Root cause 2: one signal fanned out to several blocks by one connection. Same missing-node problem in signal domain.
- Root cause 3: blocks placed at x = 0 or with wide frames left of x = 0. Off-sheet.
- Root cause 4: scope inputs fed by auto-routed wires. PLECS stacks all vertical segments on one column; wires look shorted.

## Fix that worked

1. Write wires the way PLECS saves them. Node = last point of parent `Points`. Every branch node explicit:

```
Connection {
  Type          Wire
  SrcComponent  "V_dc"
  SrcTerminal   1
  Points        [60, 100; 150, 100]        <- runs along rail to first node
  Branch {
    DstComponent  "Vm_dc"                  <- straight down from node (150,100)
    DstTerminal   1
  }
  Branch {
    Points        [260, 100]               <- next node on rail
    Branch {
      DstComponent  "S1"
      DstTerminal   1
    }
    Branch {
      Points        [470, 100]
      DstComponent  "R3"
      DstTerminal   1
    }
  }
}
```

   Nested binary branches (as in files saved by PLECS) or several flat branches from one node both load fine. A `Branch` with neither `Points` nor `Dst` but child branches: avoid.
2. Put every node at the x of the vertical component it feeds (rail node at `[x_comp, y_rail]`). Wire from node to terminal is then one straight segment. Same for horizontal parts: node at `y_comp`.
3. Fan-out of signals: one `Goto` at the source, one `From` per destination next to the input. Single-destination signal wires without `Points` are auto-routed cleanly.
4. Scope / Mux inputs from far away: give explicit `Points` with a distinct column per wire; order columns so wires do not cross (top source -> rightmost column when going down to the scope, bottom sources use columns increasing left to right).
5. Keep every component at x, y >= ~40. Long annotations: position at the middle of the sheet, they are centred on `Position`.
6. Label clashes: parts on the right of a vertical stack get `LabelPosition west`; meters `west`; tags hide names (`Show off`).

## Layout rules (power electronics)

- Power stage on top, power flows left -> right: source, DC-link meters, switching cell, filter, load / aux cap.
- Rails: P rail at one y, N rail at one y, midpoint nodes at one y. All on a 5-unit grid.
- Vertical two-poles (`Direction up`): terminal 1 top, 2 bottom. Horizontal (`Direction left`): terminal 1 left, 2 right (as saved by PLECS 4.9 for ammeters and inductors).
- Measurements -> `Goto` tags right next to the meter output. Controller reads `From` tags. No long signal wires across the power stage.
- Control below power stage: inputs (From) -> Mux -> controller C-Script -> Demux -> Goto tags. Modulator (carrier + comparators) and gate tags in their own row. Scope and output port at the right.
- Gate signals: `From` tags placed left of each switch gate, same y.

## Terminal numbers that bit us

| Component | Terminals |
| --- | --- |
| `MosfetWithDiode` | 1 drain, 2 source, 3 gate (signal) |
| `Ammeter` | 1 -> 2 positive current, 3 signal out |
| `Voltmeter` | 1 = +, 2 = -, 3 signal out |
| `SignalMux` (width n) | 1 out, 2..n+1 in |
| `SignalDemux` (width n) | 1 in, 2..n+1 out |
| `RelationalOperator` | 1, 2 in, 3 out; `Operator "6"` = `>` (out = in1 > in2) |
| `CurrentSource` (controlled) | 1, 2 electrical, 3 signal in; check sign once in simulation |
| `Output` port | needs `Terminal { Type Output Index "1" }` at top level before `Schematic` |

## File order

- All `Component` blocks before all `Connection` blocks inside `Schematic`. PLECS silently drops what follows the first connection when components and connections are interleaved.

## Verification loop (do every time)

1. Load via XML-RPC (`plecs.load`), simulate a short run, read fault string.
2. Capture the model window to PNG and look at it (`tools/shot_window.ps1`: Win32 `PrintWindow`, works when the window is covered, not when minimised).
3. After a layout-only change, rerun the reference cases and compare numbers. Layout change must give identical results.

## Do not destroy the user's layout

- A model the user saved from the PLECS GUI carries his positions, zoom and new version keys (`NoMatchingCounterpartAction` etc.). Regenerating it from a generator script throws that away.
- Before writing a model file: compare its timestamp / content with what your generator produced last time. If it changed, patch in place (replace only the parameter values or blocks you need) and diff before/after.
