# Refresh Procedure

Run on every PLECS minor-version bump or quarterly, whichever is sooner.

## 1. Detect drift

```bash
python maintainer/check_drift.py
```

Output is a Markdown report. Two sections:

- **Docs drift** — tables changed upstream. `sync_tables.py` will re-fetch.
- **PyPLECS drift** — wrappers or RPC methods added/removed since last snapshot. Update `references/` wrapped-vs-not-wrapped notes accordingly.

If both sections say "no drift", you're done.

## 2. Re-sync verbatim tables

```bash
python maintainer/sync_tables.py
```

Updates `<!-- BEGIN VERBATIM TABLE: ... -->` blocks in place. Prose between blocks untouched.

## 3. Re-author flagged prose

For each `DRIFT` line in step 1's report, open the listed file and re-author the surrounding caveman-style prose. Apply `style/caveman.md`.

For each `ADDED`/`REMOVED` line, update the relevant `skills/plecs-components/references/*.md` to flip its "wrapped via `pyplecs.<class>`" / "not wrapped, see SPICE map" notes.

## 4. Update pyplecs snapshot

```bash
python -c "
import json, sys
sys.path.insert(0, 'maintainer')
from check_drift import pyplecs_snapshot
m = json.load(open('maintainer/manifest.json'))
m['pyplecs_snapshot'] = pyplecs_snapshot()
json.dump(m, open('maintainer/manifest.json','w'), indent=2)
"
```

## 5. Bump version pin

Edit `manifest.json`'s `plecs_version_pinned` if PLECS minor changed.

## 6. Verify + commit

```bash
ruff check .
pytest tests/test_plecs_expert.py
git add maintainer skills
git commit -m "chore(skill): refresh plecs-expert against PLECS X.Y"
```
