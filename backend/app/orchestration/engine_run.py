"""A run in which an established program (GSAS-II, MAUD) refines the scan instead of agent-written code.

The plan is fixed and written by code; the recorder, metrics, comparison with the certificate and the claim check
are the same as for agent runs. The report is written by the Analyst when a key is configured, otherwise by code
from the metrics alone, so every number in it is traceable either way.

    prepare inputs ─▶ refine (engine stages) ─▶ compare with reference ─▶ report
"""

import json
import logging
import math
import traceback

from app.agents import checks
from app.config import get_settings
from app.models.contracts import Metric, Plan, PlanStep, RunRequest
from app.models.db import utcnow
from app.orchestration.recorder import Recorder
from app.storage import datasets
from app.storage.objects import get_store
from app.xrd import engines

log = logging.getLogger("corefine.engine_run")


def _plan(engine: str, measured: str, reference: str) -> Plan:
    label = engines.ENGINES[engine]["label"]
    stages = ("background and scale → cell and specimen displacement → instrument profile → size and microstrain"
              if engine == "gsas2" else "background and scale → cell and basic parameters → microstructure")
    return Plan(title=f"{label} refinement of {measured}",
                summary=f"{engines.ENGINES[engine]['about']}. Fixed recipe, written by code; no generated code.",
                steps=[PlanStep(idx=1, name="prepare_inputs", dataset_ids=[measured, reference], outputs=["scan.xye"],
                                goal="Read the measured block of the scan (answer blocks stripped), take σ from the file's "
                                     "weights, and the wavelength and Kα2 facts from the manifest.", skill="engine"),
                       PlanStep(idx=2, name=f"refine_{engine}", dataset_ids=[measured, reference],
                                uses_previous_outputs=["scan.xye"], outputs=["result.json"],
                                goal=f"{label}: {stages}.", skill="engine"),
                       PlanStep(idx=3, name="compare", dataset_ids=[measured], uses_previous_outputs=["result.json"],
                                outputs=["comparison.json"], skill="engine",
                                goal="Compare the refined lattice parameters with the certified values (code).")])


def _metrics(r: dict, pr: engines.Prepared, manifest) -> list[Metric]:
    label = engines.ENGINES[r["engine"]]["label"]
    cell, esd = r["cell"], r["cell_esd"]
    out = [Metric(name="a_refined", value=cell["length_a"], unit="angstrom", uncertainty=esd.get("length_a"),
                  method=f"{label} Rietveld refinement")]
    if cell.get("length_c") is not None and abs(cell["length_c"] - cell["length_a"]) > 1e-6:
        out.append(Metric(name="c_refined", value=cell["length_c"], unit="angstrom", uncertainty=esd.get("length_c"),
                          method=f"{label} Rietveld refinement"))
    out.append(Metric(name="Rwp", value=r["Rwp_percent"], unit="percent", method=f"{label}, final stage"))
    if r.get("zero_deg") is not None:
        out.append(Metric(name="zero_shift", value=r["zero_deg"], unit="degree", method=f"{label}"))
    if r.get("displacement_um") is not None:
        out.append(Metric(name="specimen_displacement", value=r["displacement_um"], unit="micrometre", method=f"{label}"))
    if r.get("size_um") is not None:
        out.append(Metric(name="crystallite_size", value=r["size_um"], unit="micrometre", method=f"{label}, isotropic"))
    if r.get("microstrain") is not None:
        out.append(Metric(name="microstrain", value=r["microstrain"], unit="dimensionless", method=f"{label}, isotropic"))
    if r.get("B_iso_A2") is not None:
        out.append(Metric(name="B_iso", value=r["B_iso_A2"], unit="angstrom^2", method=f"{label}, isotropic displacement"))
    out.append(Metric(name="wavelength", value=pr.wavelength_A, unit="angstrom",
                      method=f"manifest: {manifest.instrument.wavelength_source}"))
    return out


def _code_report(engine: str, metrics: list[Metric], r: dict, pr: engines.Prepared, rule_class: str) -> str:
    label = engines.ENGINES[engine]["label"]
    by = {m.name: m for m in metrics}

    def fmt(name):
        m = by.get(name)
        if not m:
            return None
        if isinstance(m.value, bool) or not isinstance(m.value, (int, float)):
            return f"{m.value} {m.unit or ''}".strip()
        if m.uncertainty:  # round both to two significant figures of the uncertainty
            dec = max(0, 1 - int(math.floor(math.log10(abs(m.uncertainty)))))
            return f"{m.value:.{dec}f} ± {m.uncertainty:.{dec}f} {m.unit or ''}".strip()
        return f"{m.value:.6g} {m.unit or ''}".strip()

    lines = [f"# {label}: a = {fmt('a_refined')}", "",
             f"{label} refined `{pr.measured_file}` against the reference structure `{pr.reference_id}`. "
             f"Classification (code): **{rule_class}**.", "", "| Quantity | Value |", "| --- | --- |"]
    for name in ("a_refined", "c_refined", "a_certified", "difference_from_certified", "c_certified",
                 "c_difference_from_certified", "Rwp", "zero_shift", "specimen_displacement", "crystallite_size",
                 "microstrain", "wavelength"):
        if fmt(name):
            lines.append(f"| {name.replace('_', ' ')} | {fmt(name)} |")
    lines += ["", "## Refinement stages", "", "| Stage | Rwp (%) |", "| --- | --- |"]
    lines += [f"| {s['stage']} | {s['Rwp_percent']:.2f} |" for s in r["stages"]]
    lines += ["", "## Settings", ""] + [f"- **{k}**: {v}" for k, v in r["settings"].items() if isinstance(v, str)]
    lines += [f"- **data**: {n}" for n in pr.notes]
    if r["warnings"]:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in r["warnings"]]
    lines += ["", "_Written by code from the metrics (no language model)._"]
    return "\n".join(lines) + "\n"


def execute_engine_run(run_id: str, req: RunRequest) -> None:
    """Never raises: the run ends in a recorded state."""
    s, store = get_settings(), get_store()
    rec = Recorder(run_id, store)
    engine = req.engine
    try:
        manifests = [datasets.load_manifest(i, store) for i in req.dataset_ids]
        measured = next(m for m in manifests if m.role == "measured_pattern")
        reference = engines.reference_for(measured.id, req.dataset_ids)
        ok, why = engines.available(engine)
        if not ok:
            raise engines.EngineError(why)
        plan = _plan(engine, measured.id, reference)
        rec.run_update(status="planning", started_at=utcnow(), plan=plan.model_dump())
        rec.put("plan.json", plan.model_dump_json(indent=2))
        rec.steps_init([(st.idx, st.name) for st in plan.steps])
        rec.log("orchestrator", f"engine {engines.ENGINES[engine]['label']}: fixed recipe, no generated code; "
                                f"reference structure {reference}")
        rec.run_update(status="running")

        rec.step_update(1, status="running", attempts=1)
        workdir = s.LOCAL_DATA_DIR / "engine_runs" / run_id
        pr = engines.prepare(measured.id, reference, workdir)
        rec.put("outputs/scan.xye", pr.scan.read_bytes(), 1)
        rec.log("inputs", f"{pr.measured_file}: λ = {pr.wavelength_A} Å ({'Kα1 + Kα2' if pr.ka2 else 'single line'}, "
                          f"{pr.source}); " + "; ".join(pr.notes))
        rec.step_update(1, status="done")

        rec.step_update(2, status="running", attempts=1)
        r = engines.RUNNERS[engine](pr)
        for st in r["stages"]:
            rec.log(engine, f"stage {st['stage']}: Rwp {st['Rwp_percent']:.2f} %")
        for w in r["warnings"]:
            rec.log(engine, f"warning: {w}")
        slim = {k: v for k, v in r.items() if k != "curve"}
        rec.put("outputs/result.json", json.dumps(slim, indent=1, default=float), 2)
        if r.get("curve"):
            rec.put("outputs/fit_curve.json", json.dumps(r["curve"]), 2)
        for logname in ("gsas2.log", "maud.log"):
            if (workdir / logname).is_file():
                rec.put(f"logs/{logname}", (workdir / logname).read_bytes(), 2)
        metrics = _metrics(r, pr, measured)
        mkey = rec.put("outputs/metrics.json", json.dumps([m.model_dump() for m in metrics], indent=2), 2)
        rec.ingest_metrics(mkey)
        rec.step_update(2, status="done")

        rec.step_update(3, status="running", attempts=1)
        rec.run_update(status="analysing")
        comparison = checks.comparison_metrics(metrics, measured.reference_values or {}, s.SUCCESS_TARGET_A)
        if comparison:
            ckey = rec.put("outputs/comparison.json", json.dumps([m.model_dump() for m in comparison], indent=2), 3)
            rec.ingest_metrics(ckey)
        all_metrics = metrics + comparison
        rule_class, reasons = checks.rule_classification(all_metrics, None, pr.wavelength_A)
        rec.log("rules", f"classification {rule_class}: " + "; ".join(reasons))
        rec.step_update(3, status="done")

        allowed = checks.allowed_values(all_metrics, [m.model_dump(exclude_none=True) for m in manifests])
        classification, report = rule_class, None
        if s.ANTHROPIC_API_KEY:
            from app.agents import analyst
            from app.agents.llm import LLMError

            try:
                out = analyst.write_report(req.prompt + f"\n\n(This run used {engines.ENGINES[engine]['label']}, not generated code.)",
                                           all_metrics, None, None, manifests, rule_class, reasons)
                report, classification = out.report_markdown, out.classification
                rec.log("analyst", f"classification {out.classification}")
            except LLMError as e:  # the refinement stands; only the prose falls back to code
                rec.log("orchestrator", f"analyst unavailable ({str(e).splitlines()[0][:120]}); report written by code")
        if report is None:
            report = _code_report(engine, all_metrics, r, pr, rule_class)
            if not s.ANTHROPIC_API_KEY:
                rec.log("orchestrator", "report written by code (no ANTHROPIC_API_KEY)")
        claim = checks.claim_check(report, allowed + [st["Rwp_percent"] for st in r["stages"]])
        rec.log("claim_checker", f"{claim['checked']} numbers checked, {len(claim['untraced'])} untraced")
        rec.put("report.md", report)
        rec.finish("done", classification=classification, claim_check=claim)
    except Exception as e:  # noqa: BLE001 — recorded for the UI
        log.exception("engine run %s failed", run_id)
        msg = str(e) if isinstance(e, (engines.EngineError, datasets.ManifestError)) else \
            f"internal error: {e}\n{traceback.format_exc(limit=3)}"
        try:
            rec.log("orchestrator", f"run failed: {msg.splitlines()[0]}")
        except Exception:
            pass
        rec.finish("failed", error=msg)


def group_view(group_id: str) -> dict:
    """Every run of a comparison group with its refined values, the measured scan, GSAS-II's calculated curve, and the
    reflection positions each engine's refined cell predicts (computed here from that cell, not taken from the engine)."""
    import numpy as np
    from pymatgen.analysis.diffraction.xrd import XRDCalculator
    from pymatgen.core import Lattice, Structure
    from sqlalchemy import select

    from app.models.db import MetricRow, RunRow, get_sessionmaker
    from app.xrd import patterns

    with get_sessionmaker()() as db:
        runs = list(db.scalars(select(RunRow).where(RunRow.group_id == group_id).order_by(RunRow.id)))
        metrics = {r.id: {m.name: {"value": m.value, "uncertainty": m.uncertainty, "unit": m.unit}
                          for m in db.scalars(select(MetricRow).where(MetricRow.run_id == r.id))} for r in runs}
    if not runs:
        return {"group_id": group_id, "runs": []}
    store = get_store()
    measured_id = next((i for i in runs[0].dataset_ids if datasets.load_manifest(i).role == "measured_pattern"), None)
    out = {"group_id": group_id, "dataset": measured_id, "runs": []}
    x, y, wl, file, _ = patterns.measured_full(measured_id)
    step = max(1, len(x) // 4000)
    out["measured"] = {"file": file, "x": x[::step].tolist(), "y": y[::step].tolist(), "wavelength_A": wl}
    ref_id = engines.reference_for(measured_id, runs[0].dataset_ids)
    ref = datasets.load_manifest(ref_id)
    base = Structure.from_str(store.get(datasets.dataset_files(ref)[0]).decode(), fmt="cif")
    for r in runs:
        m = metrics[r.id]
        entry = {"id": r.id, "engine": r.engine or "agents", "label": engines.ENGINES[r.engine or "agents"]["label"],
                 "status": r.status, "metrics": m, "error": r.error}
        key = f"runs/{r.id}/outputs/fit_curve.json"
        if store.exists(key):
            c = json.loads(store.get(key))
            n = max(1, len(c["x"]) // 4000)
            entry["curve"] = {k: v[::n] for k, v in c.items()}
        a = (m.get("a_refined") or {}).get("value")
        if a:
            cc = (m.get("c_refined") or {}).get("value")
            lat = base.lattice
            ratio_c = (cc / lat.c) if cc else a / lat.a
            s2 = Structure(Lattice.from_parameters(lat.a * a / lat.a, lat.b * a / lat.a, lat.c * ratio_c, *lat.angles),
                           base.species, base.frac_coords)
            zero = (m.get("zero_shift") or {}).get("value") or 0.0
            pat = XRDCalculator(wavelength=wl).get_pattern(s2, two_theta_range=(float(np.min(x)), float(np.max(x))))
            entry["reflections"] = [{"two_theta": float(t) + zero, "intensity": float(i),
                                     "hkl": " ".join(str(abs(v)) for v in h[0]["hkl"])}
                                    for t, h, i in zip(pat.x, pat.hkls, pat.y) if i >= 0.5]
        out["runs"].append(entry)
    cert = datasets.load_manifest(measured_id).reference_values or {}
    out["certified"] = {k: cert.get(k) for k in ("a_A", "a_uncertainty_A", "c_A", "c_uncertainty_A", "source") if cert.get(k)}
    return out
