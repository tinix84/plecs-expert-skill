#!/usr/bin/env python3
"""Install the skills into agent skill folders (standard library only).

    python tools/install.py                 # copy into ~/.agents/skills (Codex, Gemini CLI, Copilot CLI)
    python tools/install.py --target claude # copy into ~/.claude/skills (Claude Code)
    python tools/install.py --target all --link   # symlink instead of copy, for skill development
    python tools/install.py --dest ./project/.agents/skills   # any folder

Claude Code users can also install the plugin instead:
    /plugin marketplace add tinix84/plecs-expert-skill
    /plugin install plecs-expert@plecs-expert-skill
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGETS = {"agents": Path.home() / ".agents/skills", "claude": Path.home() / ".claude/skills"}
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "build")


def install(dest: Path, link: bool) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for skill in sorted(p for p in (REPO / "skills").iterdir() if (p / "SKILL.md").exists()):
        target = dest / skill.name
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)
        if link:
            try:
                os.symlink(skill, target, target_is_directory=True)
            except OSError as exc:  # Windows without Developer Mode cannot create symlinks
                raise SystemExit(f"cannot symlink ({exc}); run without --link to copy") from exc
        else:
            shutil.copytree(skill, target, ignore=IGNORE)
        print(f"{'linked' if link else 'copied'} {skill.name} -> {target}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Install the PLECS skills into agent skill folders.")
    ap.add_argument("--target", choices=[*TARGETS, "all"], default="agents")
    ap.add_argument("--dest", type=Path, help="install into this folder instead of a named target")
    ap.add_argument("--link", action="store_true", help="symlink the skills instead of copying them")
    args = ap.parse_args(argv)
    dests = [args.dest] if args.dest else list(TARGETS.values()) if args.target == "all" else [TARGETS[args.target]]
    for d in dests:
        install(d, args.link)


if __name__ == "__main__":
    main()
