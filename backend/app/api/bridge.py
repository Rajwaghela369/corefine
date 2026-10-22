"""Theory <-> experiment for one material: what the measurements say next to what each DFT code predicts.

Experiment: XRD refinements (a_refined metrics of finished runs) and certified values from dataset manifests.
Theory: every DFT set of the same material with an equation of state (a0 per code, B0) or Raman modes.
Numbers come from run metrics, manifests and study files; nothing is computed here except differences.
"""

import json
import re

from fastapi import APIRouter
from sqlalchemy import select

from app.dft.materials import optimade_formula
from app.models.db import MetricRow, RunRow, StepRow, get_sessionmaker
from app.storage import datasets

router = APIRouter(prefix="/bridge", tags=["bridge"])


def _same(formula_a: str, formula_b: str) -> bool:
    try:
        return optimade_formula(formula_a) == optimade_formula(formula_b)
    except Exception:
        return False


@router.get("")
def bridge(material: str):
    from app.api.dft import jobs_dir

    experiment, certified = [], []
    measured_ids = []
    for row in datasets.list_indexed():
        if _same(row.material, material) and row.role == "measured_pattern":
            measured_ids.append(row.id)
            ref = (row.manifest or {}).get("reference_values") or {}
            if ref.get("a_A") is not None:
                certified.append({"dataset": row.id, "a_A": ref["a_A"], "uncertainty_A": ref.get("a_uncertainty_A"),
                                  **({"c_A": ref["c_A"], "c_uncertainty_A": ref.get("c_uncertainty_A")} if ref.get("c_A") else {}),
                                  "temperature_C": ref.get("a_reference_temperature_C"), "source": ref.get("source")})
    with get_sessionmaker()() as db:
        runs = [r for r in db.scalars(select(RunRow).where(RunRow.status == "done")) if set(r.dataset_ids or []) & set(measured_ids)]
        for r in sorted(runs, key=lambda r: r.id, reverse=True):
            m = db.scalar(select(MetricRow).where(MetricRow.run_id == r.id, MetricRow.name == "a_refined"))
            t = db.scalar(select(MetricRow).where(MetricRow.run_id == r.id, MetricRow.name == "scan_temperature"))
            if m and m.value is not None:
                experiment.append({"run": r.id, "a_A": m.value, "uncertainty_A": m.uncertainty,
                                   "temperature_C": t.value if t else None, "classification": r.classification})
    theory, raman = [], []
    for d in sorted(jobs_dir().glob("dft-*"), reverse=True):
        try:
            prov = json.loads((d / "provenance.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not _same(prov["cell"]["formula"], material):
            continue
        eos = d / "studies" / "eos" / "study.json"
        if eos.is_file():
            st = json.loads(eos.read_text())
            for code, e in st.get("codes", {}).items():
                f = e.get("fit") or {}
                if any(t["code"] == code and t["functional"] == prov["request"]["functional"] for t in theory):
                    continue  # newest set per code and functional only (sets are visited newest first)
                if f.get("a0_conventional_A"):
                    theory.append({"set": d.name, "code": code, "functional": prov["request"]["functional"],
                                   "a0_A": f["a0_conventional_A"], "B0_GPa": f.get("B0_GPa"), "kmesh": e["settings"]["kmesh"]})
            ref = st.get("reference")
            if ref and ref.get("a0_conventional_A") and not any(t["code"] == "wien2k" for t in theory):
                theory.append({"set": d.name, "code": "wien2k", "functional": "PBE", "a0_A": ref["a0_conventional_A"],
                               "B0_GPa": ref.get("B0_GPa"), "kmesh": None, "reference": ref.get("source")})
        for p in sorted((d / "studies" / "raman").glob("*/study.json")):
            st = json.loads(p.read_text())
            if any(r["code"] == p.parent.name and r["functional"] == prov["request"]["functional"] for r in raman):
                continue
            for m in st.get("modes", []):
                if m.get("raman_active") or m.get("ir_active"):
                    raman.append({"set": d.name, "code": p.parent.name, "functional": prov["request"]["functional"],
                                  "frequency_cm1": m["frequency_cm1"], "label": m["label"], "raman_active": m["raman_active"],
                                  "ir_active": m["ir_active"]})
    exp_a = experiment[0]["a_A"] if experiment else (certified[0]["a_A"] if certified else None)
    for t in theory:
        t["vs_experiment_percent"] = 100 * (t["a0_A"] / exp_a - 1) if exp_a else None
        if exp_a and t.get("B0_GPa"):
            t["pressure_equivalent_GPa"] = -t["B0_GPa"] * ((exp_a / t["a0_A"]) ** 3 - 1)
    return {"material": material, "experiment": experiment, "certified": certified, "theory": theory, "raman": raman,
            "experiment_reference": "latest XRD refinement" if experiment else ("certified value" if certified else None),
            "notes": ["DFT lattice constants are static (no zero-point motion or thermal expansion); the measurements are at "
                      "room temperature, so part of the difference is physical, not error.",
                      "Pressure equivalent: the pressure that would bring the DFT volume to the measured one, first order."]}


# --- story: what each side did, step by step -------------------------------------------------

_LOG_LINE = re.compile(r"^- \*\*(\d\d:\d\d:\d\d) · ([^*]+)\*\* — (.*)$")
_CENTRING = {"F": 4, "I": 2, "C": 2, "A": 2, "B": 2, "R": 3, "P": 1}


def _log_entries(store, run_id: str) -> list[dict]:
    key = f"runs/{run_id}/experiment_log.md"
    if not store.exists(key):
        return []
    out = []
    for ln in store.get(key).decode(errors="replace").splitlines():
        m = _LOG_LINE.match(ln)
        if m:
            out.append({"time": m.group(1), "agent": m.group(2), "note": m.group(3)})
    return out


def _conventional(cell: dict) -> dict:
    """Lattice parameters of the cell a DFT set used, in the conventional setting where that is unambiguous."""
    sg = cell.get("spacegroup", "")
    lengths = cell.get("lattice_lengths_A") or []
    m = re.match(r"([A-Z])", sg)
    if m and len(lengths) == 3:
        if re.search(r"\((19[5-9]|2[0-2]\d|230)\)", sg):  # cubic space groups 195-230
            return {"a_A": (cell["volume_A3"] * _CENTRING.get(m.group(1), 1)) ** (1 / 3)}
        if re.search(r"\((1[6-9]\d)\)", sg) and m.group(1) == "P":  # hexagonal P groups 168-194
            return {"a_A": lengths[0], "c_A": lengths[2]}
    return {}


@router.get("/story")
def story(material: str, limit: int = 3):
    """For one material: what the experiment runs and the DFT sets did, step by step, with the reasons recorded at
    the time (plans, attempts, checks, self-heals, results). Everything is read from run and set files."""
    from app.api.dft import jobs_dir
    from app.storage.objects import get_store

    store = get_store()
    measured = [r.id for r in datasets.list_indexed() if r.role == "measured_pattern" and _same(r.material, material)]
    experiment = []
    with get_sessionmaker()() as db:
        runs = [r for r in db.scalars(select(RunRow).order_by(RunRow.id.desc())) if set(r.dataset_ids or []) & set(measured)]
        for r in runs[:limit]:
            ms = {m.name: {"value": m.value, "uncertainty": m.uncertainty, "unit": m.unit}
                  for m in db.scalars(select(MetricRow).where(MetricRow.run_id == r.id))}
            steps = [{"idx": s.idx, "name": s.name, "status": s.status, "attempts": s.attempts, "error": s.error}
                     for s in db.scalars(select(StepRow).where(StepRow.run_id == r.id).order_by(StepRow.idx))]
            goals = {st["idx"]: st.get("goal") for st in ((r.plan or {}).get("steps") or [])}
            for s in steps:
                s["goal"] = goals.get(s["idx"])
            experiment.append({
                "run": r.id, "engine": r.engine or "agents", "status": r.status, "prompt": r.prompt,
                "datasets": r.dataset_ids, "group_id": r.group_id, "error": r.error,
                "plan_title": (r.plan or {}).get("title"), "plan_summary": (r.plan or {}).get("summary"),
                "steps": steps, "log": _log_entries(store, r.id), "classification": r.classification,
                "claim": {k: (r.claim_check or {}).get(k) for k in ("passed", "checked")} if r.claim_check else None,
                "result": {k: ms[k] for k in ("a_refined", "c_refined", "a_certified", "c_certified", "difference_from_certified",
                                              "c_difference_from_certified", "Rwp") if k in ms}})
    theory = []
    for d in sorted(jobs_dir().glob("dft-*"), reverse=True):
        try:
            prov = json.loads((d / "provenance.json").read_text())
            chk = json.loads((d / "checks.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not _same(prov["cell"]["formula"], material):
            continue
        plan = json.loads((d / "plan.json").read_text()) if (d / "plan.json").is_file() else None
        summary = json.loads((d / "summary.json").read_text()) if (d / "summary.json").is_file() else None
        runs = {}
        for p in sorted((d / "runs").glob("*.json")):
            st = json.loads(p.read_text())
            res = st.get("results") or {}
            runs[p.stem] = {"label": prov["generated"].get(p.stem, {}).get("label", p.stem), "status": st.get("status"),
                            "converged": res.get("converged"), "iterations": res.get("scf_iterations"),
                            "gap_eV": res.get("gap_eV"), "healed": st.get("healed"), "message": st.get("message"),
                            "attempts": st.get("attempts")}
        results = chk.get("results", [])
        theory.append({
            "set": d.name, "created": prov["created"], "goal": (plan or {}).get("goal"),
            "request": {k: prov["request"].get(k) for k in ("structure", "functional", "kmesh", "codes")},
            "cell": prov["cell"], "lattice": _conventional(prov["cell"]),
            "decisions": (plan or {}).get("decisions") or [], "warnings": (plan or {}).get("warnings") or [],
            "planner": (plan or {}).get("planner"),
            "checks": {"passed": chk.get("passed"), "n_passed": sum(1 for x in results if x.get("ok") is True),
                       "n_not_run": sum(1 for x in results if x.get("ok") is None),
                       "failed": [x for x in results if x.get("ok") is False]},
            "codes": {c: g.get("label", c) for c, g in prov["generated"].items()}, "runs": runs,
            "reference": (summary or {}).get("reference")})
        if len(theory) >= limit:
            break
    return {"material": material, "experiment": experiment, "theory": theory}
