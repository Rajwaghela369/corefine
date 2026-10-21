# Step contract

Every generated script must follow this contract. The output checker enforces it; a script that
breaks it fails the step and goes back to the Coder with the reason.

1. Locate the work folder with `WORK = Path(os.environ.get("COREFINE_WORK", "/work"))`.
2. Read only from `WORK / "inputs"`; write only to `WORK / "outputs"` (create it with `mkdir(exist_ok=True)`).
   - `inputs/<dataset-id>/dataset.yaml` is the manifest; data files sit beside it as it declares.
   - `inputs/previous/<file>` holds outputs of earlier steps this step declared it reads.
3. Write `outputs/metrics.json`: a JSON list of objects with exactly these keys:
   `{"name": str, "value": number|string|bool, "unit": str|null, "uncertainty": number|null, "method": str}`.
4. Write every table as CSV and every plot as PNG, with exactly the file names the plan declares.
5. Print a one-line summary as the **last** stdout line.
6. No network access (it is blocked). No `input()`. Must finish within 120 s.
7. Never hard-code a physical constant or reference value that should come from an input file or
   manifest (wavelength, lattice parameter). If a needed value is missing, `raise SystemExit("<reason>")`.

Libraries available: numpy, scipy, pandas, matplotlib (Agg backend), lmfit, gemmi, pymatgen, ase, pyyaml.

## Minimal example

```python
import json, os
from pathlib import Path

WORK = Path(os.environ.get("COREFINE_WORK", "/work"))
OUT = WORK / "outputs"; OUT.mkdir(exist_ok=True)
n = len(list((WORK / "inputs").rglob("*.cif")))
(OUT / "metrics.json").write_text(json.dumps([
    {"name": "n_scans", "value": n, "unit": "count", "uncertainty": None, "method": "files found"}
]))
print(f"found {n} CIF files")
```
