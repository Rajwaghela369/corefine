"""End to end: a chosen material -> plan (rules, or Claude when a key is set) -> inputs + checks -> local runs -> summary.

A LangGraph graph. It pauses before the runs so the request can answer with the plan and the input checks at once;
the runs then resume in a background thread, one code after another so a laptop never runs two DFT codes at once:

    plan ─▶ prepare (inputs + checks) ─┬─▶ ⏸ run codes in turn ─▶ summary
                                       └─▶ end (not asked to run, or checks failed)

Every step writes into the set folder (plan.json, provenance, checks, runs/<code>.json, summary.json), which is the
record; the graph's own state lives only for the duration of one workflow.
"""

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.dft import execute, materials, pipeline, planner, sources, structure
from app.dft.codes import REGISTRY, available

log = logging.getLogger("corefine.dft.workflow")


def plan_for(material_id: str, goal: str | None = None, functional: str = "PBE", kmesh: tuple | None = None,
             codes: list[str] | None = None) -> tuple[planner.Plan, dict]:
    entry = materials.get(material_id)
    cell = structure.standard_primitive(sources.load(f"mp:{material_id}").atoms)
    plan = planner.rule_plan(entry, cell.lattice, functional, kmesh, codes)
    if goal and get_settings().ANTHROPIC_API_KEY and not plan.blocked:
        plan = planner.agent_plan(goal, plan, entry, available(get_settings()))
    return plan, entry


class WorkflowState(TypedDict, total=False):
    set_dir: str
    material_id: str
    goal: str | None
    functional: str
    kmesh: list[int] | None
    codes: list[str] | None
    run: bool
    plan: dict            # planner.Plan as a dict, so the checkpointer stores plain data
    material: dict
    checks_passed: bool
    runnable: list[str]


def _plan_node(state: WorkflowState) -> WorkflowState:
    kmesh = tuple(state["kmesh"]) if state.get("kmesh") else None
    plan, entry = plan_for(state["material_id"], state.get("goal"), state["functional"], kmesh, state.get("codes"))
    set_dir = Path(state["set_dir"])
    set_dir.mkdir(parents=True, exist_ok=True)
    (set_dir / "plan.json").write_text(json.dumps({"material": entry, "goal": state.get("goal"), **plan.model_dump()},
                                                  indent=2, default=str))
    if plan.blocked:
        raise pipeline.RequestError("; ".join(plan.blocked))
    return {"plan": plan.model_dump(), "material": entry}


def _prepare_node(state: WorkflowState) -> WorkflowState:
    set_dir = Path(state["set_dir"])
    result = pipeline.prepare(planner.Plan.model_validate(state["plan"]).request, set_dir)
    passed = result["checks"]["passed"]
    runnable: list[str] = []
    if state["run"] and passed:
        local = (execute.load_targets().get("local") or {}).get("codes") or {}
        runnable = [c for c in result["provenance"]["generated"] if c in local]
        for c in runnable:
            execute.write_state(set_dir, c, target="local", kind="local", status="waiting", message="waiting for the previous code")
    return {"checks_passed": passed, "runnable": runnable}


def _run_codes_node(state: WorkflowState) -> WorkflowState:
    set_dir = Path(state["set_dir"])
    for c in state["runnable"]:
        try:
            execute.start(set_dir, c, "local", wait=True)
        except execute.ComputeConfigError as e:
            execute.write_state(set_dir, c, status="failed", message=str(e))
    return {}


def _summary_node(state: WorkflowState) -> WorkflowState:
    write_summary(Path(state["set_dir"]))
    return {}


def build_workflow_graph():
    g = StateGraph(WorkflowState)
    for name, fn in [("plan", _plan_node), ("prepare", _prepare_node), ("run_codes", _run_codes_node), ("summary", _summary_node)]:
        g.add_node(name, fn)
    g.add_edge(START, "plan")
    g.add_edge("plan", "prepare")
    g.add_conditional_edges("prepare", lambda s: "run_codes" if s["run"] and s["checks_passed"] else END,
                            {"run_codes": "run_codes", END: END})
    g.add_edge("run_codes", "summary")
    g.add_edge("summary", END)
    # a fresh in-memory checkpointer per workflow: it only has to bridge the pause before the runs
    return g.compile(checkpointer=InMemorySaver(), interrupt_before=["run_codes"])


def start(set_dir: Path, material_id: str, goal: str | None = None, functional: str = "PBE",
          kmesh: tuple | None = None, codes: list[str] | None = None, run: bool = True, wait: bool = False) -> dict:
    graph = build_workflow_graph()
    config = {"configurable": {"thread_id": f"{set_dir.name}-{uuid.uuid4().hex[:8]}"}}
    graph.invoke({"set_dir": str(set_dir), "material_id": material_id, "goal": goal, "functional": functional,
                  "kmesh": list(kmesh) if kmesh else None, "codes": codes, "run": run}, config)
    snapshot = graph.get_state(config)
    v = snapshot.values
    if "run_codes" in snapshot.next:
        def resume():
            try:
                graph.invoke(None, config)
            except Exception:
                log.exception("DFT runs for %s failed", set_dir.name)

        t = threading.Thread(target=resume, daemon=True)
        t.start()
        if wait:
            t.join()
    return {"plan": planner.Plan.model_validate(v["plan"]), "material": v["material"],
            "checks_passed": v["checks_passed"], "runs": v["runnable"]}


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
