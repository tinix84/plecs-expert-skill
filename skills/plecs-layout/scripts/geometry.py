"""Symbol boxes and terminal positions of PLECS blocks.

PLECS does not store terminal offsets in .plecs files. They are measured once per
PLECS version from a printed calibration sheet (see the repository's
maintainer/geometry/) and stored in `geometry.json` next to this file:

    {"plecs_version": "4.9",
     "blocks": {"Gain": {"": {"right/off": {"box": [x0, y0, x1, y1],
                                            "terminals": {"1": [dx, dy], "2": [dx, dy]}},
                               ...8 orientations...}}}}

Offsets are relative to the component Position. A block missing from the table
falls back to a 30 x 30 box with every terminal at the centre, which is what the
linter assumed before measurement.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

TABLE_PATH = Path(__file__).resolve().parent / "geometry.json"
FALLBACK_HALF = 15


@dataclass(frozen=True)
class Shape:
    box: tuple[float, float, float, float]    # absolute x0, y0, x1, y1
    terminals: dict                           # terminal number (str) -> absolute (x, y)
    measured: bool


def _load():
    try:
        return json.loads(TABLE_PATH.read_text(encoding="utf-8")).get("blocks", {})
    except FileNotFoundError:
        return {}


_TABLE = _load()


def variant_of(kind: str, params: dict) -> str:
    """Variant key for blocks whose size depends on a parameter (as in the calibration sheet)."""
    if kind == "Sum":
        n = sum(ch in "+-" for ch in params.get("Inputs", "|++"))
        return f"{n}in" + ("_round" if params.get("IconShape", "2") == "2" else "")
    if kind == "Product":
        return f"{params.get('Inputs', '2')}in"
    if kind in ("SignalMux", "SignalDemux"):
        return f"w{params.get('Width', '2')}"
    if kind == "Scope":
        return f"{params.get('@Axes', '1')}in"
    return ""


def shape(kind: str, pos, direction: str = "right", flipped: bool = False, params: dict | None = None) -> Shape:
    entry = _TABLE.get(kind, {}).get(variant_of(kind, params or {}), {}).get(
        f"{direction}/{'on' if flipped else 'off'}")
    x, y = pos
    if entry:
        x0, y0, x1, y1 = entry["box"]
        terms = {k: (x + dx, y + dy) for k, (dx, dy) in entry["terminals"].items()}
        return Shape((x + x0, y + y0, x + x1, y + y1), terms, True)
    h = FALLBACK_HALF
    return Shape((x - h, y - h, x + h, y + h), {}, False)


def terminal(s: Shape, number, pos) -> tuple[float, float]:
    """Absolute terminal position, or the block centre when unmeasured."""
    return s.terminals.get(str(number), tuple(pos))


def is_measured(kind: str) -> bool:
    return kind in _TABLE
