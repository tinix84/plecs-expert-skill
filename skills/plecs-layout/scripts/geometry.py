"""Symbol boxes and terminal positions of PLECS blocks.

PLECS does not store built-in terminal offsets in .plecs files. They are measured
once per PLECS version from a printed calibration sheet (see the repository's
maintainer/geometry/) and stored in `geometry.json` next to this file. A parsed
Subsystem is a narrow exception: its explicit Frame and Terminal Position offsets
can be read directly from the component record for the supported orientation.

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
import re
from dataclasses import dataclass
from pathlib import Path

import plecs_file as pf

TABLE_PATH = Path(__file__).resolve().parent / "geometry.json"
FALLBACK_HALF = 15
TEXT_CHAR_WIDTH = 8
TEXT_HEIGHT = 12
TEXT_MARGIN = 2
TEXT_GAP = 8


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


def _cscript_port_count(value: str | None) -> int | None:
    """Count literal C-Script ports; a scalar width is one port, not its width."""
    if value is None:
        return None
    value = value.strip()
    if re.fullmatch(r"\d+", value):
        return 0 if int(value) == 0 else 1
    if value.startswith("[") and value.endswith("]"):
        entries = value[1:-1].split()
        if not entries:
            return 0
        if all(re.fullmatch(r"[1-9]\d*", entry) for entry in entries):
            return len(entries)
    return None


def variant_of(kind: str, params: dict) -> str:
    """Variant key for blocks whose size depends on a parameter (as in the calibration sheet)."""
    if kind == "Sum":
        inputs = params.get("Inputs", "|++")
        if params.get("IconShape", "2") == "2":
            # round icon: port positions follow the pattern, "|" marks an empty position
            return "round_" + "".join("|" if ch == "|" else "+" for ch in inputs)
        return f"{sum(ch in '+-' for ch in inputs)}in"
    if kind == "Product":
        return f"{params.get('Inputs', '2')}in"
    if kind in ("SignalMux", "SignalDemux"):
        return f"w{params.get('Width', '2')}"
    if kind == "Scope":
        return f"{params.get('@Axes', '1')}in"
    if kind == "CScript":
        inputs = _cscript_port_count(params.get("NumInputs"))
        outputs = _cscript_port_count(params.get("NumOutputs"))
        if inputs is None or outputs is None:
            return ""
        # Geometry remains table-backed: counts without a calibration entry
        # resolve to a variant name but shape() still marks them unmeasured.
        return f"{inputs}in{outputs}out"
    return ""


def coverage_issue(kind: str, params: dict | None = None, direction: str = "right",
                   flipped: bool = False) -> dict | None:
    """Describe why this exact kind/variant/orientation lacks measured geometry."""
    params = params or {}
    variant = variant_of(kind, params)
    orientation = f"{direction}/{'on' if flipped else 'off'}"
    variants = _TABLE.get(kind)
    if kind == "CScript" and not variant:
        reason = "C-Script port parameters must be literal widths or vectors"
    elif variants is None:
        reason = "component kind has no calibrated geometry"
    elif variant not in variants:
        reason = f"variant {variant!r} is not calibrated"
    elif orientation not in variants[variant]:
        reason = f"orientation {orientation!r} is not calibrated"
    else:
        return None
    return {
        "kind": kind,
        "variant": variant,
        "direction": direction,
        "flip": flipped,
        "reason": reason,
    }


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


def component_params(component) -> dict:
    """Extract geometry-relevant parameters from a parsed Component block."""
    params = {parameter.get("Variable"): parameter.get("Value")
              for parameter in component.children_of("Parameter")
              if parameter.get("Variable") is not None}
    if component.get("Axes") is not None:
        params["@Axes"] = component.get("Axes")
    return params


def _subsystem_offsets(component):
    """Read PLECS 4.9 Subsystem frame and ordered terminal offsets.

    PLECS serializes these offsets relative to the component Position. The initial
    adapter supports the verified controller orientation (Direction up, Flipped off);
    other transforms remain uncovered until independently checked.
    """
    direction = component.get("Direction") or "right"
    flipped = component.get("Flipped") == "on"
    if direction != "up" or flipped:
        return None, None, "Subsystem geometry is verified only for Direction up, Flipped off"

    frame = pf.parse_points(component.raw("Frame"))
    if len(frame) != 2:
        return None, None, "Subsystem Frame must contain two corners"
    (ax, ay), (bx, by) = frame
    x0, x1 = sorted((ax, bx))
    y0, y1 = sorted((ay, by))
    if x0 == x1 or y0 == y1:
        return None, None, "Subsystem Frame must have nonzero width and height"

    terminals = {}
    # PLECS numbers the external component pins by Terminal child order; each
    # child Index refers to the corresponding internal Input/Output block.
    for index, terminal_block in enumerate(component.children_of("Terminal"), 1):
        points = pf.parse_points(terminal_block.raw("Position"))
        if len(points) != 1:
            return None, None, f"Subsystem Terminal {index} must have one Position"
        terminals[str(index)] = points[0]
    return (x0, y0, x1, y1), terminals, None


def component_shape(component, at=None) -> Shape:
    """Resolve a parsed component using measured table entries or explicit records.

    Subsystem `Frame` and ordered `Terminal Position` values are direct serialized
    geometry, not inferred from nested sheet contents. Offsets are relative to the
    component Position and are currently accepted only for the verified up/off form.
    """
    pos = at if at is not None else (component.position or (0, 0))
    kind = component.get("Type")
    if kind == "Subsystem":
        frame, terminals, reason = _subsystem_offsets(component)
        if reason is None:
            x, y = pos
            x0, y0, x1, y1 = frame
            absolute = {number: (x + dx, y + dy)
                        for number, (dx, dy) in terminals.items()}
            return Shape((x + x0, y + y0, x + x1, y + y1), absolute, True)
        h = FALLBACK_HALF
        x, y = pos
        return Shape((x - h, y - h, x + h, y + h), {}, False)
    return shape(kind, pos, component.get("Direction") or "right",
                 component.get("Flipped") == "on", component_params(component))


def component_coverage_issue(component) -> dict | None:
    """Return the exact geometry gap for a parsed component, including Subsystems."""
    kind = component.get("Type")
    params = component_params(component)
    direction = component.get("Direction") or "right"
    flipped = component.get("Flipped") == "on"
    if kind == "Subsystem":
        _, _, reason = _subsystem_offsets(component)
        if reason is None:
            return None
        return {"kind": kind, "variant": "frame/terminals", "direction": direction,
                "flip": flipped, "reason": reason}
    return coverage_issue(kind, params, direction, flipped)


def terminal(s: Shape, number, pos) -> tuple[float, float]:
    """Absolute terminal position, or the block centre when unmeasured."""
    return s.terminals.get(str(number), tuple(pos))


def estimate_text_box(text: str, center) -> tuple[float, float, float, float]:
    """Conservative single-line text bounds at PLECS schematic scale.

    Assumes a fixed 8 px character advance and 12 px line height; these values
    are layout reservations, not a substitute for checking PLECS rendering.
    """
    width = max(TEXT_CHAR_WIDTH, len(text) * TEXT_CHAR_WIDTH) + 2 * TEXT_MARGIN
    x, y = center
    return (x - width / 2, y - TEXT_HEIGHT / 2 - TEXT_MARGIN,
            x + width / 2, y + TEXT_HEIGHT / 2 + TEXT_MARGIN)


def supports_plain_text(text: str) -> bool:
    """Whether text fits the supported single-line, unformatted estimate."""
    return not any(char in text for char in "\r\n\t\\{}") and all(ord(char) >= 32 for char in text)


def is_measured(kind: str) -> bool:
    """Whether the table contains any entries for this kind, not this instance."""
    return kind in _TABLE
