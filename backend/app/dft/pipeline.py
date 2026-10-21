"""request -> structure -> standard cell -> inputs for each code -> read-back checks -> provenance.

Writes, under the output folder:
  structure/   the source file (CIF or OPTIMADE JSON summary) and the standardized cell
  <code>/      one folder per code adapter (e.g. exciting/input.xml + species, questaal/init + ctrl + logs)
  provenance.json, checks.json, SUMMARY.md
"""

import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from ase.io import write as ase_write

from app.config import get_settings
from app.dft import checks, sources, structure
from app.dft.codes import REGISTRY, available
from app.dft.request import CalcRequest


class RequestError(ValueError):
    pass


def _git_describe(path: Path | None) -> str | None:
    if not path:
        return None
    try:
        return subprocess.run(["git", "-C", str(path), "describe", "--tags", "--always", "--dirty"],
                              capture_output=True, text=True, timeout=10).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def prepare(req: CalcRequest, outdir: Path) -> dict:
    s = get_settings()
    codes = req.codes or available(s)
    req = req.model_copy(update={"codes": codes})
    problems = req.unsupported()
    if not codes:
        problems.append("no DFT code is configured on this server")
    for name in codes:
        adapter = REGISTRY.get(name)
        if adapter is None:
            problems.append(f"unknown code {name!r}; registered: {sorted(REGISTRY)}")
            continue
        ok, reason = adapter.availability(s)
        if not ok:
            problems.append(f"{adapter.label} is not available here: {reason}")
        problems += adapter.problems(req)
    if problems:
        raise RequestError("; ".join(problems))
    outdir.mkdir(parents=True, exist_ok=True)

    src = sources.load(req.structure, cache_dir=s.LOCAL_DATA_DIR / "structures")
    cell = structure.standard_primitive(src.atoms)
    if req.volume_scale != 1.0:
        cell = structure.scaled(cell, req.volume_scale)
    title = f"{cell.atoms.get_chemical_formula(mode='metal')} {req.functional} {req.task} from {req.structure}"

    sdir = outdir / "structure"
    sdir.mkdir(exist_ok=True)
    ase_write(sdir / "source_cell.cif", src.atoms, format="cif")
    ase_write(sdir / "primitive_standard.cif", cell.atoms, format="cif")

    generated, read_backs = {}, {}
    for name in codes:
        adapter = REGISTRY[name]
        generated[name] = {"label": adapter.label, "method": adapter.method, "main_file": adapter.main_file,
                           **adapter.write(cell, req, outdir / name, s, title)}
        read_backs[name] = adapter.read_back(outdir / name, req)

    report = checks.run_checks(cell, req, src.declared_spacegroup, read_backs)
    provenance = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "request": req.model_dump(),
        "source": {"source": src.source, "url": src.url, "sha256": src.sha256,
                   "declared_spacegroup": src.declared_spacegroup, "notes": src.notes},
        "cell": cell.summary(),
        "code_versions": {"exciting": _git_describe(s.EXCITING_ROOT) if "exciting" in codes else None,
                          "questaal": _git_describe(s.QUESTAAL_BIN.parent) if "questaal" in codes and s.QUESTAAL_BIN else None},
        "generated": generated,
        "host": platform.node(),
    }
    (outdir / "provenance.json").write_text(json.dumps(provenance, indent=2, default=str))
    (outdir / "checks.json").write_text(json.dumps(report, indent=2, default=str))
    (outdir / "SUMMARY.md").write_text(summary_markdown(provenance, report))
    return {"provenance": provenance, "checks": report, "outdir": str(outdir)}


def summary_markdown(prov: dict, report: dict) -> str:
    c, r = prov["cell"], prov["request"]
    lines = [f"# {c['formula']} — {r['functional']} {r['task']} inputs", "",
             f"Source: `{prov['source']['source']}` ({prov['source']['url'] or 'local file'})", "",
             f"Primitive cell: {c['natoms']} atoms, {c['spacegroup']}, V = {c['volume_A3']} Å³, "
             f"nearest neighbour {c['nearest_neighbour_A']} Å", "",
             f"k-mesh {' '.join(map(str, r['kmesh']))}; codes: {', '.join(r['codes'])}", "",
             f"## Sanity checks: {'all passed' if report['passed'] else 'FAILED'}", "", "| | check | detail |", "|---|---|---|"]
    lines += [f"| {'✓' if x['ok'] else '✗'} | {x['check']} | {x['detail']} |" for x in report["results"]]
    for code, g in prov["generated"].items():
        defaults = ", ".join(f"{k}={v}" for k, v in g["defaults"]["values"].items())
        lines += ["", f"## {g['label']} ({g['method']})", "", f"Set explicitly: {g['set_explicitly']}", "",
                  f"Code defaults ({g['defaults']['source']}): {defaults}"]
    for n in prov["source"]["notes"]:
        lines += ["", f"> Note: {n}"]
    return "\n".join(lines) + "\n"
