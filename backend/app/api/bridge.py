"""Theory <-> experiment for one material: what the measurements say next to what each DFT code predicts.

Experiment: XRD refinements (a_refined metrics of finished runs) and certified values from dataset manifests.
Theory: every DFT set of the same material with an equation of state (a0 per code, B0) or Raman modes.
Numbers come from run metrics, manifests and study files; nothing is computed here except differences.
"""

import json

from fastapi import APIRouter
from sqlalchemy import select

from app.dft.materials import optimade_formula
from app.models.db import MetricRow, RunRow, get_sessionmaker
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
