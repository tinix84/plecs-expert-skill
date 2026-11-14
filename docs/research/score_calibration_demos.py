#!/usr/bin/env python3
"""Score-calibration data for ticket #22: what do the Plexim demo sheets score
under the layout checks in docs/superpowers/specs/2026-09-27-block-diagram-layout-design.md?

Walks every .plecs demo model under DEMO_ROOT (root sheet plus every Subsystem
sub-sheet, each counted as its own "sheet"), runs the existing schematic linter
on the whole file, and for every sheet reports:

  - lint finding counts by code and severity (from lint_schematic.lint_text)
  - the crossing count for that sheet, parsed out of the "crossing" finding's
    message ("N wire crossing(s) at ...")
  - the number of Connection blocks on the sheet, and how many of them have a
    routed length (sum of segment lengths from lint_schematic._segments) over
    150 px
  - the number of Goto/From/Label blocks and the total number of blocks
  - whether the sheet is signal-only (all its Connections are Type "Signal")

Only counts, file names and sheet paths are recorded -- no schematic content
is copied out of the demos.

Usage:
    python score_calibration_demos.py [--demo-root PATH] [--json OUT.json] [--csv OUT.csv]

Default demo root: D:/OneDrive/Documenti/Plexim/PLECS 4.9 (64 bit)/demos
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "plecs-layout" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import lint_schematic as ls  # noqa: E402
import plecs_file as pf  # noqa: E402

DEFAULT_DEMO_ROOT = Path("D:/OneDrive/Documenti/Plexim/PLECS 4.9 (64 bit)/demos")
MAX_WIRE = 150
CROSSING_RE = re.compile(r"^(\d+) wire crossing")


def _walk_sheets(sch, path: str, model: str, out: dict) -> None:
    comps = {c.get("Name"): c for c in sch.children_of("Component")}
    tags = [n for n, c in comps.items() if c.get("Type") in ("Goto", "From", "Label")]
    conns = list(sch.children_of("Connection"))
    types = [c.get("Type") for c in conns]
    signal_only = bool(conns) and all(t == "Signal" for t in types)

    long_conn = 0
    for conn in conns:
        length = 0.0
        for (a, _oa), (b, _ob) in ls._segments(conn, comps):
            length += abs(a[0] - b[0]) + abs(a[1] - b[1])
        if length > MAX_WIRE:
            long_conn += 1

    out[(model, path)] = {
        "model": model,
        "path": path,
        "n_blocks": len(comps),
        "n_tags": len(tags),
        "n_connections": len(conns),
        "n_long_connections": long_conn,
        "signal_only": signal_only,
        "n_signal_connections": sum(1 for t in types if t == "Signal"),
        "lint_errors_by_code": {},
        "lint_warns_by_code": {},
        "n_crossings": 0,
    }

    for name, c in comps.items():
        sub = c.child("Schematic")
        if sub is not None:
            _walk_sheets(sub, f"{path.rstrip('/')}/{name}", model, out)


def collect(demo_root: Path) -> list[dict]:
    files = sorted(demo_root.glob("*/*.plecs"))
    sheets: dict = {}
    for fp in files:
        model = fp.stem
        text = fp.read_text(encoding="utf-8", errors="replace")
        root = pf.parse(text)
        sch = pf.schematic(root)
        if sch is None:
            continue
        _walk_sheets(sch, "/", model, sheets)

        findings = ls.lint_text(text)
        for f in findings:
            key = (model, f.path)
            if key not in sheets:
                # finding at a path not captured by the walk (should not happen); skip
                continue
            if f.code == "crossing":
                m = CROSSING_RE.match(f.message)
                if m:
                    sheets[key]["n_crossings"] += int(m.group(1))
                continue
            bucket = "lint_errors_by_code" if f.severity == "error" else "lint_warns_by_code"
            sheets[key][bucket][f.code] = sheets[key][bucket].get(f.code, 0) + 1

    return [sheets[k] for k in sheets]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo-root", type=Path, default=DEFAULT_DEMO_ROOT)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--csv", type=Path, default=None)
    args = ap.parse_args(argv)

    rows = collect(args.demo_root)
    rows.sort(key=lambda r: (r["model"], r["path"]))

    for r in rows:
        n_errors = sum(r["lint_errors_by_code"].values())
        print(f"{r['model']}{r['path']}: blocks={r['n_blocks']} tags={r['n_tags']} "
              f"conns={r['n_connections']} long={r['n_long_connections']} "
              f"signal_only={r['signal_only']} lint_errors={n_errors} "
              f"crossings={r['n_crossings']}")

    if args.json:
        args.json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if args.csv:
        fieldnames = ["model", "path", "n_blocks", "n_tags", "n_connections",
                      "n_long_connections", "signal_only", "n_signal_connections",
                      "n_lint_errors", "n_crossings"]
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                w.writerow({
                    "model": r["model"], "path": r["path"], "n_blocks": r["n_blocks"],
                    "n_tags": r["n_tags"], "n_connections": r["n_connections"],
                    "n_long_connections": r["n_long_connections"],
                    "signal_only": r["signal_only"],
                    "n_signal_connections": r["n_signal_connections"],
                    "n_lint_errors": sum(r["lint_errors_by_code"].values()),
                    "n_crossings": r["n_crossings"],
                })
    return 0


if __name__ == "__main__":
    sys.exit(main())
