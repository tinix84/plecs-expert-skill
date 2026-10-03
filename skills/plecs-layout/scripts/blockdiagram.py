"""Place controller block diagrams using measured PLECS geometry.

This path is deliberately separate from the electrical schematic placer. It uses
only the standard library and rejects geometry or port roles it cannot verify.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import asdict
import sys
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geometry  # noqa: E402
import lint_schematic  # noqa: E402
from layout import LOCAL, Sheet, snap  # noqa: E402


FIXED_ORIENTATION = {
    "CScript": ("up", False),
    "Subsystem": ("up", False),
    "Scope": ("right", False),
    "Output": ("right", False),
    "Input": ("right", False),
    "Display": ("right", False),
}
MIN_COLUMN_GAP = 40
MIN_ROW_GAP = 30
TAG_STUB = 20


class LayoutError(ValueError):
    """A controller layout request violates a geometry or placement constraint."""

    def __init__(self, findings):
        self.findings = list(findings)
        super().__init__("; ".join(finding["message"] for finding in self.findings))


def _fail(code, message, **where):
    raise LayoutError([{"code": code, "message": message, **where}])


def _port_roles(kind, params, shape, component=None):
    """Return the calibrated logical role of each supported signal terminal."""
    terminals = {str(term) for term in shape.terminals}
    if kind == "Subsystem":
        if component is None:
            return None
        interface = component.children_of("Terminal")
        if len(interface) != len(terminals):
            return None
        roles = {}
        for index, terminal in enumerate(interface, 1):
            terminal_type = terminal.get("Type")
            if terminal_type == "Input":
                roles[str(index)] = "in"
            elif terminal_type == "Output":
                roles[str(index)] = "out"
            else:
                return None
        return roles
    if kind == "CScript":
        inputs = geometry._cscript_port_count(params.get("NumInputs"))
        outputs = geometry._cscript_port_count(params.get("NumOutputs"))
        if inputs is None or outputs is None:
            return None
        return {**{str(term): "in" for term in range(1, inputs + 1)},
                **{str(term): "out" for term in range(inputs + 1, inputs + outputs + 1)}}
    if kind == "Scope":
        try:
            count = int(params.get("@Axes", "1"))
        except (TypeError, ValueError):
            return None
        return {str(term): "in" for term in range(1, count + 1)}
    if kind in {"Input", "Constant", "Step", "SineGenerator", "PulseGenerator",
                "TriangleGenerator", "RandomNumber", "RepeatingSequence", "From", "Goto"}:
        return {"1": "out"} if "1" in terminals else None
    if kind in {"Output", "Display", "Scope", "ToFile"}:
        return {term: "in" for term in terminals}
    if kind in {"Gain", "Offset", "Saturation", "Abs", "Integrator", "TransferFunction",
                "ZeroOrderHold", "Delay", "Function", "Relay", "RateLimiter",
                "DeadZone", "LookupTable", "UnitDelay", "Memory"}:
        return {"1": "in", "2": "out"} if {"1", "2"} <= terminals else None
    if kind in {"Sum", "Product"}:
        if "1" not in terminals:
            return None
        return {term: ("out" if term == "1" else "in") for term in terminals}
    if kind == "SignalMux":
        return {term: ("out" if term == "1" else "in") for term in terminals}
    if kind == "SignalDemux":
        return {term: ("in" if term == "1" else "out") for term in terminals}
    return None


def _port_normal(shape, terminal):
    x0, y0, x1, y1 = shape.box
    x, y = terminal
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x - cx, y - cy
    if abs(dx) >= abs(dy):
        return (1 if dx >= 0 else -1, 0)
    return (0, 1 if dy >= 0 else -1)


def _vector_direction(vector):
    return {(1, 0): "right", (-1, 0): "left", (0, 1): "down", (0, -1): "up"}[vector]


def _opposite(vector):
    return (-vector[0], -vector[1])


def _part_shape(part, at=None):
    position = part.pos if at is None else at
    if part.kind == "Subsystem" and part.component is not None:
        return geometry.component_shape(part.component, at=position)
    return geometry.shape(part.kind, position, part.direction, part.flipped, part.params)


def _template_text(part, box, pos=(0, 0)):
    records = []
    x0, y0, x1, y1 = box
    center_x = (x0 + x1) / 2
    if part.component is None:
        show_name, label_position, shown = True, "north", []
    else:
        show_name = part.component.get("Show") != "off"
        label_position = part.component.get("LabelPosition") or "north"
        shown = [p.get("Value") or "" for p in part.component.children_of("Parameter")
                 if p.get("Show") == "on"]
    if show_name:
        records.append((part.name, label_position, 0))
    records.extend((value, "south", index) for index, value in enumerate(shown))
    boxes = []
    for text, side, line in records:
        if not geometry.supports_plain_text(text):
            _fail("unsupported_text", f"{part.name} has displayed text the controller layout cannot measure",
                  component=part.name, text=text)
        pitch = geometry.TEXT_HEIGHT + geometry.TEXT_GAP
        if side == "north":
            text_center = (center_x, y0 - geometry.TEXT_GAP - geometry.TEXT_HEIGHT / 2 - line * pitch)
        elif side == "south":
            text_center = (center_x, y1 + geometry.TEXT_GAP + geometry.TEXT_HEIGHT / 2 + line * pitch)
        elif side == "east":
            sample = geometry.estimate_text_box(text, (0, 0))
            half_width = (sample[2] - sample[0]) / 2
            text_center = (x1 + geometry.TEXT_GAP + half_width,
                           (y0 + y1) / 2 + line * pitch)
        elif side == "west":
            sample = geometry.estimate_text_box(text, (0, 0))
            half_width = (sample[2] - sample[0]) / 2
            text_center = (x0 - geometry.TEXT_GAP - half_width,
                           (y0 + y1) / 2 + line * pitch)
        else:
            _fail("unsupported_text", f"{part.name} has unsupported LabelPosition {side!r}",
                  component=part.name)
        boxes.append(geometry.estimate_text_box(text, text_center))
    return boxes


def _tag_placement(part, shape, terminal, role, tag_name, grid=5):
    if not geometry.supports_plain_text(tag_name):
        _fail("unsupported_text", f"net {tag_name!r} cannot be displayed as a plain tag",
              net=tag_name)
    normal = _port_normal(shape, terminal)
    tag_kind = "Goto" if role == "out" else "From"
    tag_direction = _vector_direction(normal if role == "out" else _opposite(normal))
    label_side = {(0, -1): "north", (0, 1): "south",
                  (1, 0): "east", (-1, 0): "west"}[normal]
    tag_shape = geometry.shape(tag_kind, (0, 0), tag_direction, False, {})
    if not tag_shape.measured or "1" not in tag_shape.terminals:
        _fail("unsupported_tag_geometry", f"measured {tag_kind} geometry is unavailable",
              component=part.name, net=tag_name)
    desired_terminal = (terminal[0] + normal[0] * TAG_STUB,
                        terminal[1] + normal[1] * TAG_STUB)
    terminal_offset = tag_shape.terminals["1"]
    tag_center = (desired_terminal[0] - terminal_offset[0],
                  desired_terminal[1] - terminal_offset[1])
    tag_center = (snap(tag_center[0], grid), snap(tag_center[1], grid))
    tag_shape = geometry.shape(tag_kind, tag_center, tag_direction, False, {})
    actual_terminal = geometry.terminal(tag_shape, 1, tag_center)
    if (abs(actual_terminal[0] - terminal[0]) + abs(actual_terminal[1] - terminal[1]) != TAG_STUB
            or (actual_terminal[0] != terminal[0] and actual_terminal[1] != terminal[1])):
        _fail("tag_stub_alignment", f"{part.name} terminal cannot reach its {tag_name!r} tag with a 20 px grid-aligned stub",
              component=part.name, net=tag_name)
    box = tag_shape.box
    tx0, ty0, tx1, ty1 = box
    if label_side == "north":
        text_center = ((tx0 + tx1) / 2,
                       ty0 - geometry.TEXT_GAP - geometry.TEXT_HEIGHT / 2)
    elif label_side == "south":
        text_center = ((tx0 + tx1) / 2,
                       ty1 + geometry.TEXT_GAP + geometry.TEXT_HEIGHT / 2)
    elif label_side == "east":
        sample = geometry.estimate_text_box(tag_name, (0, 0))
        half_width = (sample[2] - sample[0]) / 2
        text_center = (tx1 + geometry.TEXT_GAP + half_width,
                       (ty0 + ty1) / 2)
    else:
        sample = geometry.estimate_text_box(tag_name, (0, 0))
        half_width = (sample[2] - sample[0]) / 2
        text_center = (tx0 - geometry.TEXT_GAP - half_width,
                       (ty0 + ty1) / 2)
    text_box = geometry.estimate_text_box(tag_name, text_center)
    reserved = (min(box[0], text_box[0], terminal[0], actual_terminal[0]),
                min(box[1], text_box[1], terminal[1], actual_terminal[1]),
                max(box[2], text_box[2], terminal[0], actual_terminal[0]),
                max(box[3], text_box[3], terminal[1], actual_terminal[1]))
    return {
        "kind": tag_kind,
        "direction": tag_direction,
        "label": label_side,
        "center": tag_center,
        "terminal": actual_terminal,
        "box": box,
        "text_box": text_box,
        "reserved": reserved,
    }


def _candidate_tag_box(part, shape, terminal, role, tag_name):
    return _tag_placement(part, shape, terminal, role, tag_name)["reserved"]


def _expanded_bounds(part, shape, roles, pin_tags):
    x0, y0, x1, y1 = shape.box
    bounds = [x0, y0, x1, y1]
    for box in _template_text(part, shape.box):
        bounds[0] = min(bounds[0], box[0])
        bounds[1] = min(bounds[1], box[1])
        bounds[2] = max(bounds[2], box[2])
        bounds[3] = max(bounds[3], box[3])
    for term, tag_name in pin_tags:
        point = shape.terminals[term]
        tag_box = _candidate_tag_box(part, shape, point, roles[term], tag_name)
        bounds[0] = min(bounds[0], tag_box[0])
        bounds[1] = min(bounds[1], tag_box[1])
        bounds[2] = max(bounds[2], tag_box[2])
        bounds[3] = max(bounds[3], tag_box[3])
    return tuple(bounds)


def _net_edges(netlist):
    return [(net_index, source, destination)
            for net_index, net in enumerate(netlist.nets)
            if net.kind == "Signal" and net.pins
            for source, _ in net.pins[:1]
            for destination, _ in net.pins[1:]]


def _feedback_edges(names, edges):
    outgoing = defaultdict(set)
    for net_index, source, destination in edges:
        outgoing[source].add(destination)
    state, feedback = {}, set()

    def visit(node):
        state[node] = 1
        for destination in sorted(outgoing[node]):
            if state.get(destination, 0) == 0:
                visit(destination)
            elif state[destination] == 1:
                feedback.add((node, destination))
        state[node] = 2

    for name in sorted(names):
        if state.get(name, 0) == 0:
            visit(name)
    return feedback


def _longest_path_layers(names, edges, feedback):
    successors = defaultdict(set)
    indegree = {name: 0 for name in names}
    for _, source, destination in edges:
        if (source, destination) in feedback or destination in successors[source]:
            continue
        successors[source].add(destination)
        indegree[destination] += 1
    ready = [name for name in names if indegree[name] == 0]
    heapq.heapify(ready)
    layers = {name: 0 for name in names}
    visited = 0
    while ready:
        source = heapq.heappop(ready)
        visited += 1
        for destination in sorted(successors[source]):
            layers[destination] = max(layers[destination], layers[source] + 1)
            indegree[destination] -= 1
            if indegree[destination] == 0:
                heapq.heappush(ready, destination)
    if visited != len(names):
        _fail("cycle_resolution", "feedback edge removal did not produce an acyclic graph")
    return layers, successors


def _barycentre_orders(parts, columns, successors, row_hints, sweeps=4):
    by_column = defaultdict(list)
    for name, col in columns.items():
        by_column[col].append(name)
    orders = {col: sorted(names) for col, names in by_column.items()}
    predecessors = defaultdict(set)
    for source, destinations in successors.items():
        for destination in destinations:
            predecessors[destination].add(source)

    def sweep(col, neighbours, use_predecessors):
        rank = {name: index for index, name in enumerate(neighbours)}
        def key(name):
            if row_hints[name] is not None:
                return (0, row_hints[name], 0.0, name)
            linked = predecessors[name] if use_predecessors else successors[name]
            values = [rank[other] for other in linked if other in rank]
            bary = sum(values) / len(values) if values else float("inf")
            return (1, 0, bary, name)
        return sorted(orders[col], key=key)

    column_ids = sorted(orders)
    for _ in range(sweeps):
        for col in column_ids:
            prev = orders.get(col - 1, [])
            if prev:
                orders[col] = sweep(col, prev, True)
        for col in reversed(column_ids):
            following = orders.get(col + 1, [])
            if following:
                orders[col] = sweep(col, following, False)
    rows = {}
    for col, names in orders.items():
        used = set()
        for name in names:
            hint = row_hints[name]
            if hint is not None:
                if hint in used:
                    _fail("row_hint_conflict", f"multiple blocks in column {col} request row {hint}",
                          column=col, row=hint, component=name)
                rows[name] = hint
                used.add(hint)
        next_row = 0
        for name in names:
            if name in rows:
                continue
            while next_row in used:
                next_row += 1
            rows[name] = next_row
            used.add(next_row)
    return rows


def _validate(netlist, grid):
    findings = []
    resolved = {}
    roles = {}
    for name, part in sorted(netlist.parts.items()):
        direction, flipped = FIXED_ORIENTATION.get(part.kind, (part.direction, part.flipped))
        if part.direction_explicit and part.direction != direction:
            findings.append({"code": "orientation_conflict", "component": name,
                             "message": f"{name} requests Direction {part.direction}; controller layout requires {direction}"})
        if part.flipped_explicit and part.flipped != flipped:
            findings.append({"code": "orientation_conflict", "component": name,
                             "message": f"{name} requests Flipped {part.flipped}; controller layout requires {flipped}"})
        # Geometry must match the controller orientation that will be emitted.
        # Subsystems are the exception: their explicit frame/terminal records
        # are only verified for their serialized up/off orientation.
        shape = (geometry.component_shape(part.component, at=(0, 0))
                 if part.kind == "Subsystem" and part.component is not None
                 else geometry.shape(part.kind, (0, 0), direction, flipped, part.params))
        if not shape.measured:
            issue = (geometry.component_coverage_issue(part.component)
                     if part.kind == "Subsystem" and part.component is not None
                     else geometry.coverage_issue(part.kind, part.params, direction, flipped))
            reason = issue["reason"] if issue else "terminal geometry is unavailable"
            findings.append({"code": "unsupported_geometry", "component": name,
                             "message": f"{name} ({part.kind}, variant {geometry.variant_of(part.kind, part.params)!r}): {reason}"})
            continue
        port_roles = _port_roles(part.kind, part.params, shape, part.component)
        if port_roles is None:
            findings.append({"code": "unsupported_port_roles", "component": name,
                             "message": f"{name} ({part.kind}) has no verified controller signal port-role rule"})
            continue
        missing_roles = set(shape.terminals) - set(port_roles)
        if missing_roles:
            findings.append({"code": "unsupported_port_roles", "component": name,
                             "message": f"{name} has no verified role for terminals {', '.join(sorted(missing_roles))}"})
            continue
        if part.row is not None and (not isinstance(part.row, int) or part.row < 0):
            findings.append({"code": "invalid_row_hint", "component": name,
                             "message": f"{name} row hint must be a non-negative integer"})
        if part.col is not None and (not isinstance(part.col, int) or part.col < 0):
            findings.append({"code": "invalid_column_hint", "component": name,
                             "message": f"{name} column hint must be a non-negative integer"})
        requested = part.requested_pos
        if requested is not None and (requested[0] % grid or requested[1] % grid):
            findings.append({"code": "off_grid_fixed_position", "component": name,
                             "message": f"{name} fixed position {requested} is off the {grid} px grid"})
        resolved[name] = (direction, flipped, shape)
        roles[name] = port_roles
    names = set(netlist.parts)
    net_names = set()
    pin_owners = {}
    for net in netlist.nets:
        if net.name in net_names:
            findings.append({"code": "duplicate_net_name", "net": net.name,
                             "message": f"net name {net.name!r} is used more than once"})
        net_names.add(net.name)
        if net.kind != "Signal":
            findings.append({"code": "unsupported_net_kind", "net": net.name,
                             "message": f"controller net {net.name!r} has unsupported kind {net.kind!r}; expected 'Signal'"})
            continue
        if len(net.pins) < 2:
            findings.append({"code": "incomplete_net", "net": net.name,
                             "message": f"signal net {net.name!r} must have a driver and at least one receiver"})
            continue
        source_name, source_term = net.pins[0]
        source_term = str(source_term)
        if source_name not in names:
            findings.append({"code": "unknown_component", "net": net.name,
                             "message": f"net {net.name!r} refers to unknown component {source_name}"})
            continue
        if source_name in resolved:
            if source_term not in resolved[source_name][2].terminals:
                findings.append({"code": "unknown_terminal", "component": source_name, "net": net.name,
                                 "message": f"net {net.name!r} refers to unknown terminal {source_name}:{source_term}"})
            elif roles[source_name].get(source_term) != "out":
                findings.append({"code": "invalid_driver", "component": source_name, "net": net.name,
                                 "message": f"{source_name}:{source_term} is an input terminal and cannot drive net {net.name!r}"})
        for receiver_name, receiver_term in net.pins[1:]:
            receiver_term = str(receiver_term)
            if receiver_name not in names:
                findings.append({"code": "unknown_component", "net": net.name,
                                 "message": f"net {net.name!r} refers to unknown component {receiver_name}"})
                continue
            pin = (receiver_name, receiver_term)
            if pin in pin_owners:
                findings.append({"code": "duplicate_terminal", "component": receiver_name, "net": net.name,
                                 "message": f"terminal {receiver_name}:{receiver_term} is assigned to nets {pin_owners[pin]!r} and {net.name!r}"})
            else:
                pin_owners[pin] = net.name
            if receiver_name in resolved:
                if receiver_term not in resolved[receiver_name][2].terminals:
                    findings.append({"code": "unknown_terminal", "component": receiver_name, "net": net.name,
                                     "message": f"net {net.name!r} refers to unknown terminal {receiver_name}:{receiver_term}"})
                elif roles[receiver_name].get(receiver_term) != "in":
                    findings.append({"code": "invalid_receiver", "component": receiver_name, "net": net.name,
                                     "message": f"{receiver_name}:{receiver_term} is an output terminal and cannot receive net {net.name!r}"})
        source_pin = (source_name, source_term)
        if source_pin in pin_owners:
            findings.append({"code": "duplicate_terminal", "component": source_name, "net": net.name,
                             "message": f"terminal {source_name}:{source_term} is assigned to nets {pin_owners[source_pin]!r} and {net.name!r}"})
        else:
            pin_owners[source_pin] = net.name
    if findings:
        raise LayoutError(findings)
    return resolved, roles


def _ordered_zones(netlist, zones):
    present = {part.zone for part in netlist.parts.values()}
    ordered = list(zones) if zones is not None else sorted(present)
    if len(set(ordered)) != len(ordered):
        _fail("duplicate_zone", "zone order contains a duplicate zone")
    ordered.extend(sorted(present - set(ordered)))
    return ordered


def _assign_columns(netlist, layers, successors, feedback, zones):
    zone_index = {zone: index for index, zone in enumerate(zones)}
    columns = {}
    for zone in zones:
        members = [name for name, part in netlist.parts.items() if part.zone == zone]
        if not members:
            continue
        base = min(layers[name] for name in members)
        for name in members:
            part = netlist.parts[name]
            columns[name] = part.col if part.col is not None else layers[name] - base
    conflicts = []
    for source, destinations in successors.items():
        for destination in destinations:
            if (source, destination) in feedback:
                continue
            source_zone = zone_index[netlist.parts[source].zone]
            destination_zone = zone_index[netlist.parts[destination].zone]
            if source_zone > destination_zone:
                conflicts.append({"code": "zone_order_conflict", "component": source,
                                  "message": f"signal {source} -> {destination} goes against the requested zone order"})
            elif source_zone == destination_zone and columns[source] >= columns[destination]:
                conflicts.append({"code": "column_hint_conflict", "component": source,
                                  "message": f"column hints place {source} at {columns[source]} and {destination} at {columns[destination]} despite signal flow"})
    if conflicts:
        raise LayoutError(conflicts)
    return columns


def _place(netlist, resolved, roles, zones, x0, y0, grid, zone_gap):
    names = set(netlist.parts)
    edges = _net_edges(netlist)
    feedback_pairs = _feedback_edges(names, edges)
    layers, successors = _longest_path_layers(names, edges, feedback_pairs)
    columns = _assign_columns(netlist, layers, successors, feedback_pairs, zones)
    row_hints = {name: part.row for name, part in netlist.parts.items()}
    rows = _barycentre_orders(netlist.parts, columns, successors, row_hints)

    by_pin_tags = defaultdict(list)
    for net in netlist.nets:
        for name, term in net.pins:
            by_pin_tags[(name, str(term))].append(net.name)
    bounds = {}
    for name, part in netlist.parts.items():
        _, _, zero_shape = resolved[name]
        tags = [(str(term), sorted(tag_names)[0])
                for (owner, term), tag_names in by_pin_tags.items() if owner == name]
        bounds[name] = _expanded_bounds(part, zero_shape, roles[name], tags)

    row_up, row_down = defaultdict(float), defaultdict(float)
    for name, (left, top, right, bottom) in bounds.items():
        row_up[rows[name]] = max(row_up[rows[name]], -top)
        row_down[rows[name]] = max(row_down[rows[name]], bottom)
    row_y = {}
    highest = max(rows.values(), default=0)
    cursor = y0
    for row in range(highest + 1):
        up, down = row_up[row], row_down[row]
        row_y[row] = snap(cursor + up, grid)
        cursor = row_y[row] + down + MIN_ROW_GAP

    zone_columns = defaultdict(list)
    for name, col in columns.items():
        zone_columns[netlist.parts[name].zone].append(col)
    groups = []
    for zone in zones:
        for col in sorted(set(zone_columns[zone])):
            members = [name for name in netlist.parts
                       if netlist.parts[name].zone == zone and columns[name] == col]
            left = max(-bounds[name][0] for name in members)
            right = max(bounds[name][2] for name in members)
            fixed_x = {netlist.parts[name].requested_pos[0] for name in members
                       if netlist.parts[name].requested_pos is not None}
            if len(fixed_x) > 1:
                _fail("fixed_column_conflict", f"fixed components in zone {zone!r}, column {col} request different x coordinates",
                      zone=zone, column=col)
            groups.append((zone, col, members, left, right, next(iter(fixed_x)) if fixed_x else None))

    x_centres = {}
    previous = None
    previous_right = 0
    previous_zone = None
    occupied_until = None
    for zone, col, members, left, right, fixed_x in groups:
        gap = zone_gap if previous_zone is not None and previous_zone != zone else MIN_COLUMN_GAP
        gap_steps = max(1, col - previous[1]) if previous_zone == zone and previous is not None else 1
        needed = (x0 + left if previous is None and fixed_x is None
                  else occupied_until + gap * gap_steps + left if previous is not None
                  else fixed_x)
        candidate = fixed_x if fixed_x is not None else math.ceil(needed / grid) * grid
        if fixed_x is not None and candidate < needed:
            _fail("fixed_column_conflict", f"fixed x={candidate} for zone {zone!r}, column {col} conflicts with preceding geometry",
                  zone=zone, column=col)
        x_centres[(zone, col)] = candidate
        occupied_until = candidate + right
        previous = (zone, col)
        previous_zone = zone

    positions = {}
    for name, part in netlist.parts.items():
        target = (x_centres[(part.zone, columns[name])], row_y[rows[name]])
        if part.requested_pos is not None:
            if part.row is not None and part.requested_pos[1] != target[1]:
                _fail("fixed_row_conflict", f"{name} fixed y={part.requested_pos[1]} conflicts with row {part.row} at y={target[1]}",
                      component=name, row=part.row)
            target = tuple(part.requested_pos)
        positions[name] = target

    # Fixed y coordinates can collide with another block in the same row; preserving them is
    # safer than moving them. The full obstacle checks run after wire/tag emission.
    for name, part in netlist.parts.items():
        part.pos = positions[name]
        part.direction, part.flipped = resolved[name][:2]
    return {
        "layers": {name: layers[name] for name in sorted(names)},
        "columns": {name: columns[name] for name in sorted(names)},
        "rows": {name: rows[name] for name in sorted(names)},
        "positions": {name: positions[name] for name in sorted(names)},
        "feedback_edges": sorted((netlist.nets[i].name, source, destination)
                                  for i, source, destination in edges
                                  if (source, destination) in feedback_pairs),
        "zones": list(zones),
    }


def _segment_hits_rect(a, b, rect):
    if a[1] == b[1]:
        return rect[1] < a[1] < rect[3] and min(a[0], b[0]) < rect[2] and max(a[0], b[0]) > rect[0]
    if a[0] == b[0]:
        return rect[0] < a[0] < rect[2] and min(a[1], b[1]) < rect[3] and max(a[1], b[1]) > rect[1]
    return True


def _point_on_segment(point, a, b):
    if a[1] == b[1] == point[1]:
        return min(a[0], b[0]) <= point[0] <= max(a[0], b[0])
    if a[0] == b[0] == point[0]:
        return min(a[1], b[1]) <= point[1] <= max(a[1], b[1])
    return False


def _segments_conflict(a, b, c, d):
    if a[1] == b[1] and c[0] == d[0]:
        return min(a[0], b[0]) < c[0] < max(a[0], b[0]) and min(c[1], d[1]) < a[1] < max(c[1], d[1])
    if c[1] == d[1] and a[0] == b[0]:
        return min(c[0], d[0]) < a[0] < max(c[0], d[0]) and min(a[1], b[1]) < c[1] < max(a[1], b[1])
    if a[1] == b[1] == c[1] == d[1]:
        return max(min(a[0], b[0]), min(c[0], d[0])) < min(max(a[0], b[0]), max(c[0], d[0]))
    if a[0] == b[0] == c[0] == d[0]:
        return max(min(a[1], b[1]), min(c[1], d[1])) < min(max(a[1], b[1]), max(c[1], d[1]))
    return False


def _wire_clear(net_name, source, destination, shapes, text_boxes, candidate_tags, emitted_segments):
    a, b = source[2], destination[2]
    if a[0] != b[0] and a[1] != b[1]:
        return False
    for name, shape in shapes.items():
        if _segment_hits_rect(a, b, shape.box):
            return False
        for terminal in shape.terminals.values():
            if tuple(terminal) not in (a, b) and _point_on_segment(tuple(terminal), a, b):
                return False
    for box in text_boxes:
        if _segment_hits_rect(a, b, box):
            return False
    for tag_net, pin, box in candidate_tags:
        if tag_net != net_name and _segment_hits_rect(a, b, box):
            return False
    for other_net, start, end in emitted_segments:
        if other_net != net_name and _segments_conflict(a, b, start, end):
            return False
    return True


def _rectangles_overlap(left, right):
    return (left[0] < right[2] and right[0] < left[2]
            and left[1] < right[3] and right[1] < left[3])


def _register_emitted_tags(net, pins, placements, occupied_tags):
    for pin, placement in zip(pins, placements):
        name, terminal, _ = pin
        rectangles = (placement["box"], placement["text_box"])
        for previous in occupied_tags:
            if previous["component"] != name:
                continue
            if any(_rectangles_overlap(current, other)
                   for current in rectangles for other in previous["rectangles"]):
                _fail(
                    "tag_spacing_conflict",
                    f"signal tags {previous['net']!r} at {name}:{previous['terminal']} "
                    f"and {net.name!r} at {name}:{terminal} overlap; this multiport "
                    "layout needs more port spacing",
                    component=name,
                    terminals=(previous["terminal"], terminal),
                    nets=(previous["net"], net.name),
                )
        occupied_tags.append({"component": name, "terminal": terminal,
                              "net": net.name, "rectangles": rectangles})


def _emit_tags(sheet, net, net_index, pins, placements, used_names):
    goto_name = f"__blockdiagram_{net_index}_goto"
    while goto_name in used_names:
        goto_name += "_"
    used_names.add(goto_name)
    goto = placements[0]
    sheet.goto(goto_name, net.name, goto["center"], LOCAL, goto["direction"], goto["label"])
    sheet.signal(pins[0][:2], (goto_name, "1"))
    segments = [(net.name, pins[0][2], goto["terminal"])]
    for receiver_index, (pin, placement) in enumerate(zip(pins[1:], placements[1:]), start=1):
        from_name = f"__blockdiagram_{net_index}_from_{receiver_index}"
        while from_name in used_names:
            from_name += "_"
        used_names.add(from_name)
        sheet.from_(from_name, net.name, placement["center"], LOCAL, placement["direction"],
                    placement["label"])
        sheet.signal((from_name, "1"), pin[:2])
        segments.append((net.name, placement["terminal"], pin[2]))
    return segments


def _emit_connections(sheet, netlist, roles, grid, max_wire, feedback_nets):
    from autolayout import check_connectivity
    import plecs_file as pf

    text = sheet.model("controller")
    schematic = pf.schematic(pf.parse(text))
    components = {component.get("Name"): component for component in schematic.children_of("Component")}
    shapes = {name: lint_schematic._shape(component) for name, component in components.items()}
    text_boxes = [record["box"] for component in components.values()
                  for record in lint_schematic.text_envelopes(component, shapes[component.get("Name")])[0]]
    placed_parts = netlist.parts
    tag_candidates = []
    per_net_placements = {}
    for net in netlist.nets:
        placements = []
        for index, (name, term) in enumerate(net.pins):
            part_shape = _part_shape(placed_parts[name])
            point = geometry.terminal(part_shape, term, placed_parts[name].pos)
            role = roles[name][str(term)]
            placement = _tag_placement(placed_parts[name], part_shape, point, role, net.name, grid)
            placements.append(placement)
            tag_candidates.append((net.name, (name, str(term)), placement["reserved"]))
        per_net_placements[id(net)] = placements

    emitted_segments = []
    occupied_tags = []
    report = {"routed": [], "tagged": [], "unrouted": []}
    used_names = set(components)
    for ordered_index, net in enumerate(sorted(netlist.nets, key=lambda item: item.name)):
        placements = per_net_placements[id(net)]
        pins = [(name, str(term), geometry.terminal(_part_shape(placed_parts[name]),
                                                      term, placed_parts[name].pos))
            for name, term in net.pins]
        source_point = pins[0][2]
        same_horizontal = all(pin[2][1] == source_point[1] for pin in pins[1:])
        same_vertical = all(pin[2][0] == source_point[0] for pin in pins[1:])
        max_span = max((abs(pin[2][0] - source_point[0]) + abs(pin[2][1] - source_point[1])
                        for pin in pins[1:]), default=0)
        has_feedback = net.name in feedback_nets
        clear = (max_wire > 0 and max_span <= max_wire and (same_horizontal or same_vertical)
                 and all(_wire_clear(net.name, pins[0], pin, shapes, text_boxes,
                                     tag_candidates, emitted_segments) for pin in pins[1:]))
        if clear and not has_feedback:
            destinations = [pin[:2] for pin in pins[1:]]
            sheet.signal(pins[0][:2], destinations)
            emitted_segments.extend((net.name, pins[0][2], pin[2]) for pin in pins[1:])
            report["routed"].append(net.name)
        else:
            _register_emitted_tags(net, pins, placements, occupied_tags)
            segments = _emit_tags(sheet, net, ordered_index, pins, placements, used_names)
            emitted_segments.extend(segments)
            report["tagged"].append(net.name)

    text = sheet.model("controller")
    report["connectivity"] = check_connectivity(text, netlist)
    report["lint"] = [asdict(finding) for finding in lint_schematic.lint_text(text, grid)]
    return report


def layout(netlist, *, zones=None, max_wire=150, grid=5, x0=100, y0=100, zone_gap=80):
    """Return a deterministically placed controller ``Sheet`` and diagnostics.

    The input netlist is copied. This first placement stage reserves space for every
    candidate per-port tag; wire and tag emission is performed by the next pipeline step.
    """
    if grid != 5:
        _fail("unsupported_grid", "controller layout currently supports only grid=5")
    if zone_gap < MIN_COLUMN_GAP:
        _fail("invalid_zone_gap", f"zone_gap must be at least {MIN_COLUMN_GAP} px")
    if max_wire < 0:
        _fail("invalid_max_wire", "max_wire cannot be negative")
    placed = deepcopy(netlist)
    ordered_zones = _ordered_zones(placed, zones)
    resolved, roles = _validate(placed, grid)
    placement = _place(placed, resolved, roles, ordered_zones, x0, y0, grid, zone_gap)
    sheet = Sheet(grid)
    for name in sorted(placed.parts):
        part = placed.parts[name]
        if part.component is not None:
            sheet.add_component(part.component, at=part.pos, direction=part.direction, flipped=part.flipped)
        else:
            sheet.add(part.kind, name, part.pos, part.direction, part.flipped, part.params)
    feedback_nets = {name for name, _, _ in placement["feedback_edges"]}
    report = {
        "placement": placement,
        "geometry_coverage": [],
        "unmeasured": [],
        "max_wire": max_wire,
        "routed": [],
        "tagged": [],
        "unrouted": [],
        "connectivity": [],
    }
    report.update(_emit_connections(sheet, placed, roles, grid, max_wire, feedback_nets))
    import score as score_module
    result = score_module.score(sheet.model("controller"), placed, max_wire=max_wire,
                                grid=grid, layout_report=report)
    report["quality"] = result
    report["accepted"] = result["accepted"]
    return sheet, report
