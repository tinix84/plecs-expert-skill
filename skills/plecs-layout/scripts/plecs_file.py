"""Minimal reader/writer for PLECS .plecs model text (standard library only).

A .plecs file is nested ``Key value`` lines with ``Name {`` ... ``}`` blocks.
A line that starts with a quote continues the previous string value.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class Block:
    kind: str
    items: list = field(default_factory=list)  # ordered: (key, raw value) tuples and child Blocks

    @property
    def fields(self) -> list[tuple[str, str]]:
        return [i for i in self.items if isinstance(i, tuple)]

    @property
    def children(self) -> list["Block"]:
        return [i for i in self.items if isinstance(i, Block)]

    def get(self, key: str, default: str | None = None) -> str | None:
        for k, v in self.fields:
            if k == key:
                return unquote(v)
        return default

    def raw(self, key: str) -> str | None:
        for k, v in self.fields:
            if k == key:
                return v
        return None

    def child(self, kind: str) -> "Block | None":
        return next((c for c in self.children if c.kind == kind), None)

    def children_of(self, kind: str) -> list["Block"]:
        return [c for c in self.children if c.kind == kind]

    @property
    def position(self) -> tuple[float, float] | None:
        pts = parse_points(self.raw("Position"))
        return pts[0] if pts else None

    def param(self, variable: str) -> str | None:
        for p in self.children_of("Parameter"):
            if p.get("Variable") == variable:
                return p.get("Value")
        return None


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def parse_points(value: str | None) -> list[tuple[float, float]]:
    """Parse ``[x1, y1; x2, y2]`` into a list of (x, y)."""
    if not value or not value.startswith("["):
        return []
    out = []
    for pair in value.strip("[]").split(";"):
        nums = [float(n) for n in _NUM.findall(pair)]
        if len(nums) == 2:
            out.append((nums[0], nums[1]))
    return out


def points(block: Block) -> list[tuple[float, float]]:
    return parse_points(block.raw("Points"))


def parse(text: str) -> Block:
    """Parse .plecs text into a ``<root>`` block holding the ``Plecs`` block and any trailing fields."""
    root = Block("<root>")
    stack = [root]
    last: tuple[Block, int] | None = None  # (block, item index) for string continuation
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s == "}":
            stack.pop()
            last = None
        elif s.startswith('"') and last is not None:
            blk, idx = last
            k, v = blk.items[idx]
            blk.items[idx] = (k, v[:-1] + s[1:])  # join "abc" + "def" -> "abcdef"
        elif s.endswith("{") and not s.startswith('"'):
            blk = Block(s[:-1].strip())
            stack[-1].items.append(blk)
            stack.append(blk)
            last = None
        else:
            key, _, value = s.partition(" ")
            stack[-1].items.append((key, value.strip()))
            last = (stack[-1], len(stack[-1].items) - 1)
    if len(stack) != 1:
        raise ValueError("unbalanced braces in .plecs text")
    return root


def model(root: Block) -> Block | None:
    return root if root.kind == "Plecs" else root.child("Plecs")


def schematic(root: Block) -> Block | None:
    m = model(root)
    return m.child("Schematic") if m else None


def dump(block: Block, indent: int = 0) -> str:
    if block.kind == "<root>":
        return "".join(_dump_item(i, 0) for i in block.items)
    return _dump_item(block, indent)


def _dump_item(item, indent: int) -> str:
    pad = "  " * indent
    if isinstance(item, tuple):
        k, v = item
        return f"{pad}{k:<13} {v}\n"
    body = "".join(_dump_item(i, indent + 1) for i in item.items)
    return f"{pad}{item.kind} {{\n{body}{pad}}}\n"
