"""End to end: a chosen material -> plan (rules, or Claude when a key is set) -> inputs + checks -> local runs -> summary.

Runs go one code after another so a laptop is never running two DFT codes at once. Every step writes
into the set folder (plan.json, provenance, checks, runs/<code>.json, summary.json), which is the record.
"""

import json
import threading
from pathlib import Path

from app.config import get_settings
from app.dft import execute, materials, pipeline, planner, sources, structure
from app.dft.codes import REGISTRY, available


def plan_for(material_id: str, goal: str | None = None, functional: str = "PBE", kmesh: tuple | None = None,
             codes: list[str] | None = None) -> tuple[planner.Plan, dict]:
    entry = materials.get(material_id)
    cell = structure.standard_primitive(sources.load(f"mp:{material_id}").atoms)
    plan = planner.rule_plan(entry, cell.lattice, functional, kmesh, codes)
    if goal and get_settings().ANTHROPIC_API_KEY and not plan.blocked:
        plan = planner.agent_plan(goal, plan, entry, available(get_settings()))
    return plan, entry


def start(set_dir: Path, material_id: str, goal: str | None = None, functional: str = "PBE",
          kmesh: tuple | None = None, codes: list[str] | None = None, run: bool = True, wait: bool = False) -> dict:
    plan, entry = plan_for(material_id, goal, functional, kmesh, codes)
    set_dir.mkdir(parents=True, exist_ok=True)
    (set_dir / "plan.json").write_text(json.dumps({"material": entry, "goal": goal, **plan.model_dump()}, indent=2, default=str))
    if plan.blocked:
        raise pipeline.RequestError("; ".join(plan.blocked))
    result = pipeline.prepare(plan.request, set_dir)
    runnable = []
    if run and result["checks"]["passed"]:
        local = (execute.load_targets().get("local") or {}).get("codes") or {}
        runnable = [c for c in result["provenance"]["generated"] if c in local]
        for c in runnable:
            execute.write_state(set_dir, c, target="local", kind="local", status="waiting", message="waiting for the previous code")
        t = threading.Thread(target=_run_in_turn, args=(set_dir, runnable), daemon=True)
        t.start()
        if wait:
            t.join()
    return {"plan": plan, "material": entry, "checks_passed": result["checks"]["passed"], "runs": runnable}


def _run_in_turn(set_dir: Path, codes: list[str]) -> None:
    for c in codes:
        try:
            execute.start(set_dir, c, "local", wait=True)
        except execute.ComputeConfigError as e:
            execute.write_state(set_dir, c, status="failed", message=str(e))
    write_summary(set_dir)


def write_summary(set_dir: Path) -> dict:
    """Results side by side, plus the Materials Project reference where one exists. Numbers only from files."""
    plan = json.loads((set_dir / "plan.json").read_text()) if (set_dir / "plan.json").is_file() else {}
    mat = plan.get("material") or {}
    rows = []
    for code, st in execute.all_states(set_dir).items():
        r = st.get("results") or {}
        rows.append({"code": code, "label": REGISTRY[code].label, "status": st.get("status"), "converged": r.get("converged"),
                     "scf_iterations": r.get("scf_iterations"), "gap_eV": r.get("gap_eV"), "fermi_eV": r.get("fermi_eV"),
                     "healed": (st.get("healed") or {}).get("change")})
    summary = {"material": mat.get("id"), "formula": mat.get("formula"), "rows": rows,
               "reference": {"source": "Materials Project (PBE/GGA)", "band_gap_eV": mat.get("band_gap_eV"),
                             "is_metal": mat.get("is_metal")}}
    (set_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary
