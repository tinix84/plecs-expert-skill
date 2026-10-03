"""Correctness gates and separate drawing-quality measurements for controller sheets."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geometry  # noqa: E402
import lint_schematic as lint  # noqa: E402
import plecs_file as pf  # noqa: E402

WEIGHTS = {
    "lint_errors": 100,
    "connectivity": 100,
    "non_straight": 10,
    "overlength_wires": 10,
    "missing_tags": 10,
    "unconnected_inputs": 5,
    "crossings": 5,
}
def _walk(schematic, path="/"):
    for component in schematic.children_of("Component"):
        yield path, component
        child = component.child("Schematic")
        if child is not None:
            name = component.get("Name") or "?"
            yield from _walk(child, f"{path.rstrip('/')}/{name}/")


def _params(component):
    return geometry.component_params(component)


def _endpoints(connection, root=True):
    result = []
    if root and connection.get("SrcComponent"):
        result.append((connection.get("SrcComponent"), str(connection.get("SrcTerminal"))))
    if connection.get("DstComponent"):
        result.append((connection.get("DstComponent"), str(connection.get("DstTerminal"))))
    for branch in connection.children_of("Branch"):
        result.extend(_endpoints(branch, False))
    return result


def _crossings(schematic, components):
    segments = []
    for index, connection in enumerate(schematic.children_of("Connection")):
        for (a, _), (b, _) in lint._segments(connection, components):
            if a == b or (a[0] != b[0] and a[1] != b[1]):
                continue
            segments.append((a, b, index))
    return sum(1 for i, (a, b, left) in enumerate(segments)
               for c, d, right in segments[i + 1:]
               if left != right and lint._cross((a, b), (c, d)))


def _candidate_metrics(schematic, components, max_wire):
    connections = schematic.children_of("Connection")
    non_straight = 0
    wire_length = 0
    overlength = 0
    missing_tags = 0
    for connection in connections:
        segments = list(lint._segments(connection, components))
        non_straight += sum(1 for (a, _), (b, _) in segments
                            if a[0] != b[0] and a[1] != b[1])
        wire_length += sum(abs(b[0] - a[0]) + abs(b[1] - a[1])
                           for (a, _), (b, _) in segments)
        ends = _endpoints(connection)
        tag_types = ("Goto", "From", "Label")
        direct_ends = [(name, terminal) for name, terminal in ends
                       if not (components.get(name)
                               and components[name].get("Type") in tag_types)]
        if max_wire == 0 and len(direct_ends) >= 2:
            missing_tags += 1
        if len(direct_ends) != len(ends):
            continue
        if max_wire > 0 and len(ends) >= 2:
            positions = [lint._terminal_point(components, name, term)
                         for name, term in ends if name in components]
            if positions and max(abs(x - positions[0][0]) + abs(y - positions[0][1])
                                 for x, y in positions) > max_wire:
                overlength += 1
    return non_straight, overlength, wire_length, missing_tags


def _tag_stub_faults(schematic, components, netlist):
    faults = []
    expected = {}
    for net in netlist.nets:
        if net.kind == "Signal":
            for tag_name in {net.name, net.tag} - {None}:
                expected.setdefault(tag_name, []).append(net)
    connections = schematic.children_of("Connection")
    for name, component in components.items():
        kind = component.get("Type")
        if kind not in ("Goto", "From"):
            continue
        tag = component.param("Tag")
        candidates = expected.get(tag, [])
        if not candidates:
            faults.append(f"tag {tag!r} at {name} does not match a logical net name or declared tag")
            continue
        if len(candidates) > 1:
            faults.append(f"tag {tag!r} at {name} is ambiguous across logical nets")
            continue
        net = candidates[0]
        if kind == "Goto":
            targets = {tuple((str(part), str(term))) for part, term in net.pins[:1]}
        else:
            targets = {tuple((str(part), str(term))) for part, term in net.pins[1:]}
        linked = False
        for connection in connections:
            ends = _endpoints(connection)
            if (name, "1") not in ends:
                continue
            other = [pin for pin in ends if pin != (name, "1") and pin in targets]
            if not other:
                continue
            linked = True
            tag_point = lint._terminal_point(components, name, "1")
            for part, terminal in other:
                part_point = lint._terminal_point(components, part, terminal)
                distance = abs(tag_point[0] - part_point[0]) + abs(tag_point[1] - part_point[1])
                if (tag_point[0] != part_point[0] and tag_point[1] != part_point[1]) or distance != 20:
                    faults.append(f"tag {tag!r} at {name} is not on a 20 px straight terminal stub")
        if not linked:
            faults.append(f"tag {tag!r} at {name} is not connected to its expected terminal")
    return faults


def _unconnected_inputs(schematic, netlist):
    components = {c.get("Name"): c for c in schematic.children_of("Component")}
    connected = {pin for connection in schematic.children_of("Connection")
                 for pin in _endpoints(connection)}
    try:
        import blockdiagram
    except ImportError:
        blockdiagram = None
    faults = []
    for name, part in sorted(netlist.parts.items()):
        component = components.get(name)
        if component is None:
            continue
        params = _params(component)
        if component.position is None:
            continue
        shape = geometry.component_shape(component)
        if not shape.measured or blockdiagram is None:
            continue
        roles = blockdiagram._port_roles(part.kind, params, shape, component)
        if roles is None:
            continue
        for term, role in roles.items():
            if role == "in" and (name, term) not in connected:
                faults.append(f"{name}:{term} is an unconnected block input")
    return faults


def _area(schematic):
    components = {c.get("Name"): c for c in schematic.children_of("Component") if c.position}
    boxes = []
    for component in components.values():
        shape = lint._shape(component)
        boxes.append(shape.box)
        records, _ = lint.text_envelopes(component, shape)
        boxes.extend(record["box"] for record in records)
    for connection in schematic.children_of("Connection"):
        for (a, _), (b, _) in lint._segments(connection, components):
            boxes.append((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))
    if not boxes:
        return 0
    return (max(box[2] for box in boxes) - min(box[0] for box in boxes)) * (
        max(box[3] for box in boxes) - min(box[1] for box in boxes))


def _path_bends(connection, components, start=None, root=True):
    if root:
        source = connection.get("SrcComponent")
        if source in components and components[source].position is not None:
            start = lint._terminal_point(components, source, connection.get("SrcTerminal"))
    points = pf.points(connection)
    chain = ([start] if start is not None else []) + points
    destination = connection.get("DstComponent")
    if destination in components and components[destination].position is not None:
        chain.append(lint._terminal_point(components, destination, connection.get("DstTerminal")))
    directions = []
    for a, b in zip(chain, chain[1:]):
        if a == b:
            continue
        directions.append("h" if a[1] == b[1] else "v" if a[0] == b[0] else "d")
    count = sum(left != right for left, right in zip(directions, directions[1:]))
    tail = points[-1] if points else start
    for branch in connection.children_of("Branch"):
        count += _path_bends(branch, components, start=tail, root=False)
    return count


def _bends(schematic, components):
    return sum(_path_bends(connection, components)
               for connection in schematic.children_of("Connection"))


def score(model_text, netlist, *, max_wire=150, grid=5, previous_positions=None, layout_report=None):
    """Score a controller model and return separate correctness and aesthetic results.

    ``previous_positions`` may be a component-name to coordinate mapping to measure
    displacement after a local edit. Without it, displacement is reported as unavailable.
    """
    try:
        root = pf.parse(model_text)
        schematic = pf.schematic(root)
    except (TypeError, ValueError) as error:
        schematic = None
        parse_error = str(error)
    else:
        parse_error = "no Plecs/Schematic block found" if schematic is None else None

    if schematic is None:
        findings = [{"code": "parse", "severity": "error", "path": "/",
                     "where": "-", "message": parse_error}]
        connectivity = [parse_error]
        components = {}
        lint_findings = findings
        unsupported = []
        total_area = 0
        crossings = non_straight = overlength = wire_length = bends = missing_tags = 0
        tag_count = 0
        unconnected = []
    else:
        components = {component.get("Name"): component for component in schematic.children_of("Component")}
        lint_findings = [finding.__dict__ for finding in lint.lint_text(model_text, grid)]
        try:
            from autolayout import check_connectivity
            connectivity = check_connectivity(model_text, netlist)
        except (ValueError, TypeError) as error:
            connectivity = [f"connectivity check failed: {error}"]
        unsupported = []
        for path, component in _walk(schematic):
            if component.position is None:
                continue
            params = _params(component)
            shape = geometry.component_shape(component)
            if not shape.measured:
                issue = geometry.component_coverage_issue(component)
                unsupported.append({"path": path, "component": component.get("Name"),
                                    **(issue or {"reason": "geometry is unavailable"})})
        for finding in lint_findings:
            if finding["code"] == "text-coverage":
                unsupported.append({"path": finding["path"], "component": finding["where"],
                                    "reason": finding["message"]})
        non_straight, overlength, wire_length, missing_tags = _candidate_metrics(
            schematic, components, max_wire
        )
        non_straight += len(_tag_stub_faults(schematic, components, netlist))
        crossings = _crossings(schematic, components)
        total_area = _area(schematic)
        bends = _bends(schematic, components)
        non_straight += bends
        tag_count = sum(component.get("Type") in ("Goto", "From")
                        for component in components.values())
        unconnected = _unconnected_inputs(schematic, netlist)

    lint_errors = [f for f in lint_findings if f["severity"] == "error"]
    unrouted = list((layout_report or {}).get("unrouted", []))
    unrouted.extend(f["message"] for f in lint_findings if f["code"] == "unrouted")
    counts = {
        "lint_errors": len(lint_errors),
        "connectivity": len(connectivity),
        "non_straight": non_straight,
        "overlength_wires": overlength,
        "missing_tags": missing_tags,
        "unconnected_inputs": len(unconnected),
        "crossings": crossings,
        "unrouted": len(unrouted),
    }
    weighted_total = sum(counts[name] * weight for name, weight in WEIGHTS.items())
    weighted_total += counts["unrouted"] * WEIGHTS["non_straight"]
    unresolved_tags = [finding for finding in lint_findings
                       if finding["code"] in ("tag-orphan-from", "tag-unused-goto")]
    connectivity_ok = not connectivity
    supported_geometry = not unsupported
    accepted = (weighted_total == 0 and connectivity_ok and supported_geometry and not unrouted
                and not unresolved_tags)
    if previous_positions is None or schematic is None:
        displacement = None
    else:
        displacement = {name: abs(component.position[0] - previous_positions[name][0])
                        + abs(component.position[1] - previous_positions[name][1])
                        for name, component in components.items()
                        if name in previous_positions and component.position is not None}
    all_findings = ([{"category": "lint", **finding} for finding in lint_findings]
                    + [{"category": "connectivity", "message": message} for message in connectivity]
                    + [{"category": "coverage", **item} for item in unsupported]
                    + [{"category": "routing", "message": str(item)} for item in unrouted]
                    + [{"category": "unconnected_inputs", "message": message} for message in unconnected])
    return {
        "counts": counts,
        "weighted_total": weighted_total,
        "findings": all_findings,
        "accepted": accepted,
        "coverage": {"supported_geometry": supported_geometry, "unsupported": unsupported},
        "connectivity": {"equivalent": connectivity_ok, "findings": connectivity},
        "unrouted": unrouted,
        "metrics": {
            "crossings": crossings,
            "bends": bends,
            "tag_count": tag_count,
            "wire_length": wire_length,
            "occupied_area": total_area,
            "displacement": displacement,
        },
    }


def _item(value, weight):
    findings = value if isinstance(value, list) else []
    count = len(findings) if isinstance(value, list) else int(value)
    return {"count": count, "weight": weight, "points": count * weight,
            "findings": findings}
