"""request -> structure -> standard cell -> inputs for each code -> read-back checks -> provenance.

Writes, under the output folder:
  structure/   the source file (CIF or OPTIMADE JSON summary) and the standardized cell
  exciting/    input.xml + species files
  questaal/    init.<ext>, ctrl.<ext>, site.<ext>, basp, atm and the blm/lmfa/lmchk logs
  provenance.json, checks.json, SUMMARY.md
"""

import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from ase.io import write as ase_write

from app.config import get_settings
from app.dft import checks, exciting, questaal, sources, structure
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
    problems = req.unsupported()
    if problems:
        raise RequestError("; ".join(problems))
    s = get_settings()
    outdir.mkdir(parents=True, exist_ok=True)

    src = sources.load(req.structure, cache_dir=s.LOCAL_DATA_DIR / "structures")
    cell = structure.standard_primitive(src.atoms)
    # Questaal file extension from the empirical formula: Si2 -> si, Al4O6 -> al2o3
    empirical = cell.atoms.get_chemical_formula(mode="metal", empirical=True).lower()
    ext = "".join(c for c in empirical if c.isalnum())[:12] or "crystal"
    title = f"{cell.atoms.get_chemical_formula(mode='metal')} {req.functional} {req.task} from {req.structure}"

    sdir = outdir / "structure"
    sdir.mkdir(exist_ok=True)
    ase_write(sdir / "source_cell.cif", src.atoms, format="cif")
    ase_write(sdir / "primitive_standard.cif", cell.atoms, format="cif")

    generated, e_back, e_schema, q_back = {}, None, None, None
    if "exciting" in req.codes:
        if not s.EXCITING_ROOT:
            raise RequestError("EXCITING_ROOT is not set; cannot find exciting species files and schema")
        generated["exciting"] = exciting.write(cell, req, outdir / "exciting", s.EXCITING_ROOT, title)
        e_schema = exciting.validate(outdir / "exciting", s.EXCITING_ROOT)
        e_back = exciting.read_back(outdir / "exciting")
    if "questaal" in req.codes:
        if not s.QUESTAAL_BIN:
            raise RequestError("QUESTAAL_BIN is not set; cannot run blm")
        generated["questaal"] = questaal.write(cell, req, outdir / "questaal", s.QUESTAAL_BIN, s.QUESTAAL_LIB_ROOT, ext, title)
        q_back = questaal.read_back(outdir / "questaal", ext)

    report = checks.run_checks(cell, req, src.declared_spacegroup, e_back, e_schema, q_back)
    provenance = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "request": req.model_dump(),
        "source": {"source": src.source, "url": src.url, "sha256": src.sha256,
                   "declared_spacegroup": src.declared_spacegroup, "notes": src.notes},
        "cell": cell.summary(),
        "codes": {"exciting": {"tree": str(s.EXCITING_ROOT) if s.EXCITING_ROOT else None,
                               "version": _git_describe(s.EXCITING_ROOT)},
                  "questaal": {"bin": str(s.QUESTAAL_BIN) if s.QUESTAAL_BIN else None,
                               "version": _git_describe(s.QUESTAAL_BIN.parent if s.QUESTAAL_BIN else None)}},
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
        lines += ["", f"## {code}", "", f"Set explicitly: {g['set_explicitly']}", ""]
        if code == "exciting":
            defaults = ", ".join(f"{k}={v}" for k, v in g["defaults_from_schema"].items())
            lines.append(f"Left at exciting's schema defaults: {defaults}")
        if code == "questaal":
            lines.append(f"{g['defaults']}; gmax = {g['gmax']['value']} ({g['gmax']['source']})")
    for n in prov["source"]["notes"]:
        lines += ["", f"> Note: {n}"]
    return "\n".join(lines) + "\n"
