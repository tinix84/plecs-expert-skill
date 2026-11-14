# Repository guidance

- `skills/` must stay agent-agnostic: plain `SKILL.md` per the Agent Skills spec (agentskills.io), no tool names of one particular agent, scripts invoked as `python scripts/<name>.py`, standard library only.
- Every skill must pass `agentskills validate skills/<name>` and `pytest -q` before a commit.
- Do not commit Plexim demo models, manual text, or the generated calibration sheet (`maintainer/geometry/build/`). Commit only our own prose, facts, and measured numbers.
- Do not commit models or data from client projects.
- PLECS Goto/From/Label `Visibility`: `"2"` is schematic-local, `"1"` is global (verified in PLECS 4.9).
