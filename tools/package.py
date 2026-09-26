#!/usr/bin/env python3
"""Zip each skill for upload to agents that take skill archives (for example claude.ai).

    python tools/package.py          # writes dist/<skill>.zip
"""
from __future__ import annotations

import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    out = REPO / "dist"
    out.mkdir(exist_ok=True)
    for skill in sorted(p for p in (REPO / "skills").iterdir() if (p / "SKILL.md").exists()):
        target = out / f"{skill.name}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(skill.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
                    z.write(f, Path(skill.name) / f.relative_to(skill))
        print(target)


if __name__ == "__main__":
    main()
