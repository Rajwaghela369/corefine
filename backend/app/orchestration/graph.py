"""The fixed run graph. What varies per prompt is the plan and the code, never the graph.

    plan ─▶ code ─▶ execute ─▶ check ─┬─▶ code        (retry: same step, attempt + 1, max 2 retries)
                                      ├─▶ code        (next step)
                                      ├─▶ analyse ─▶ claims ─▶ finalize
                                      └─▶ fail
"""

import json
import logging
import traceback
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents import analyst, checks, coder, planner
from app.agents.llm import LLMError, trace_span
from app.config import get_settings
from app.models.contracts import Manifest, Metric, Plan, RunRequest
from app.models.db import utcnow
from app.orchestration.events import bus
from app.orchestration.recorder import Recorder
from app.sandbox.base import OutputLimitError, SandboxSession, get_runner
from app.storage import datasets
from app.storage.objects import get_store

log = logging.getLogger("corefine.run")


class RunState(TypedDict, total=False):
    run_id: str
    request: dict
    plan: dict
    cursor: int            # index into plan.steps
    attempt: int           # 1-based attempt for the current step
    last_code: str | None
    last_error: str | None
    check_ok: bool
    retryable: bool
    produced: dict         # file name -> bucket key of its latest version
    metric_keys: list      # bucket keys of every accepted metrics.json, in order
    error: str | None
    report: str | None
    classification: str | None
    claim: dict | None


class _Ctx:
    """Things that must not live in graph state: open sandbox, recorder, manifests."""

    def __init__(self, run_id: str, req: RunRequest):
        self.settings = get_settings()
        self.store = get_store()
        self.rec = Recorder(run_id, self.store)
        self.req = req
        self.manifests: list[Manifest] = [datasets.load_manifest(i, self.store) for i in req.dataset_ids]
        self.sandbox: SandboxSession | None = None
        self.last_result = None


def _step_file(step, attempt: int, ext: str) -> str:
    v = "" if attempt == 1 else f".v{attempt}"
    return f"step_{step.idx:02d}_{step.name}{v}.{ext}"


def build_graph(ctx: _Ctx):
    s, rec = ctx.settings, ctx.rec

    def plan_node(state: RunState) -> RunState:
        rec.run_update(status="planning", started_at=utcnow())
        parent_ctx = None
        if ctx.req.parent_run_id:
            parent_ctx = _parent_context(ctx.store, ctx.req.parent_run_id)
        plan = planner.make_plan(ctx.req.prompt, ctx.manifests, s.MAX_STEPS, parent_ctx)
        rec.put("plan.json", plan.model_dump_json(indent=2))
        rec.put("plan.md", planner.plan_markdown(plan))
        rec.run_update(plan=plan.model_dump(), status="running")
        rec.steps_init([(st.idx, st.name) for st in plan.steps])
        rec.log("planner", f"planned {len(plan.steps)} steps: " + ", ".join(st.name for st in plan.steps))
        ctx.sandbox = get_runner().open(state["run_id"])
        ctx.sandbox.stage_inputs(datasets.staged_inputs(ctx.req.dataset_ids, ctx.store))
        return {"plan": plan.model_dump(), "cursor": 0, "attempt": 1, "last_code": None, "last_error": None,
                "produced": {}, "metric_keys": []}

    def code_node(state: RunState) -> RunState:
        plan = Plan.model_validate(state["plan"])
        step = plan.steps[state["cursor"]]
        attempt = state["attempt"]
        rec.step_update(step.idx, status="running" if attempt == 1 else "retrying", attempts=attempt, error=None)
        out = coder.write_step(plan, step, ctx.manifests, step.uses_previous_outputs,
                               last_code=state.get("last_code") if attempt > 1 else None,
                               last_error=state.get("last_error") if attempt > 1 else None)
        key = rec.put(f"code/{_step_file(step, attempt, 'py')}", out.code, step.idx)
        rec.step_update(step.idx, code_key=key)
        rec.log("coder", f"step {step.idx} attempt {attempt}: {out.notes}")
        return {"last_code": out.code}

    def execute_node(state: RunState) -> RunState:
        plan = Plan.model_validate(state["plan"])
        step = plan.steps[state["cursor"]]
        prev = {f"previous/{name}": ctx.store.get(state["produced"][name]) for name in step.uses_previous_outputs}
        if prev:
            ctx.sandbox.stage_inputs(prev)
        try:
            ctx.last_result = ctx.sandbox.run(state["last_code"], _step_file(step, state["attempt"], "py"),
                                              s.STEP_TIMEOUT_S)
        except OutputLimitError as e:
            return {"check_ok": False, "retryable": False, "last_error": str(e)}
        r = ctx.last_result
        out_key = rec.put(f"logs/{_step_file(step, state['attempt'], 'stdout')}", r.stdout, step.idx)
        rec.put(f"logs/{_step_file(step, state['attempt'], 'stderr')}", r.stderr, step.idx)
        rec.step_update(step.idx, stdout_key=out_key)
        return {"check_ok": True}

    def check_node(state: RunState) -> RunState:
        plan = Plan.model_validate(state["plan"])
        step = plan.steps[state["cursor"]]
        if not state.get("check_ok", True) and state.get("last_error"):
            res = checks.CheckResult(False, state["last_error"], retryable=False)
        else:
            res = checks.check_step_outputs(step, ctx.last_result)
        if not res.ok:
            can_retry = res.retryable and state["attempt"] < s.MAX_ATTEMPTS
            rec.step_update(step.idx, status="retrying" if can_retry else "failed", error=res.message)
            rec.log("checker", f"step {step.idx} attempt {state['attempt']} failed: {res.message.splitlines()[0]}")
            return {"check_ok": False, "retryable": can_retry, "last_error": res.message}
        produced = dict(state["produced"])
        for name, data in ctx.last_result.files.items():
            rec.put(f"outputs/step_{step.idx:02d}/{name}", data, step.idx)
            produced[name] = rec.put(f"outputs/{name}", data, step.idx, record=False)
        metrics_key = rec.prefix + f"outputs/step_{step.idx:02d}/metrics.json"
        rec.ingest_metrics(metrics_key)
        rec.step_update(step.idx, status="done", error=None)
        rec.log("runner", f"step {step.idx} done: {res.message}")
        return {"check_ok": True, "produced": produced, "metric_keys": [*state["metric_keys"], metrics_key],
                "cursor": state["cursor"] + 1, "attempt": 1, "last_code": None, "last_error": None}

    def route_after_check(state: RunState) -> str:
        if not state["check_ok"]:
            return "retry" if state.get("retryable") else "fail"
        n = len(state["plan"]["steps"])
        return "next" if state["cursor"] < n else "analyse"

    def retry_node(state: RunState) -> RunState:
        return {"attempt": state["attempt"] + 1}

    def analyse_node(state: RunState) -> RunState:
        rec.run_update(status="analysing")
        metrics = _merged_metrics(ctx.store, state["metric_keys"])
        measured = next((m for m in ctx.manifests if m.role == "measured_pattern"), None)
        reference = (measured.reference_values if measured else None) or {}
        comparison = checks.comparison_metrics(metrics, reference, s.SUCCESS_TARGET_A)
        if comparison:
            key = rec.put("outputs/comparison.json", json.dumps([m.model_dump() for m in comparison], indent=2))
            rec.ingest_metrics(key)
        all_metrics = metrics + comparison
        peaks = ctx.store.get(state["produced"]["peaks.csv"]) if "peaks.csv" in state["produced"] else None
        plot = ctx.store.get(state["produced"]["fit.png"]) if "fit.png" in state["produced"] else None
        wl = measured.instrument.wavelength_A if measured and measured.instrument else None
        rule_class, reasons = checks.rule_classification(all_metrics, peaks, wl)
        rec.log("rules", f"classification {rule_class}: " + "; ".join(reasons))

        allowed = checks.allowed_values(all_metrics, [m.model_dump(exclude_none=True) for m in ctx.manifests])
        report, claim = None, None
        for attempt in (1, 2):
            note = None if attempt == 1 else (
                "Your previous report contained numbers the claim checker could not trace: "
                + json.dumps(claim["untraced"]) + ". Remove or replace them with values from the metrics.")
            out = analyst.write_report(ctx.req.prompt + (f"\n\n{note}" if note else ""), all_metrics,
                                       peaks.decode() if peaks else None, plot, ctx.manifests, rule_class, reasons)
            report = out.report_markdown
            claim = checks.claim_check(report, allowed)
            rec.log("analyst", f"attempt {attempt}: classification {out.classification}"
                    + ("" if out.agrees_with_rule else f" (rule said {rule_class})"))
            rec.log("claim_checker", f"{claim['checked']} numbers checked, {len(claim['untraced'])} untraced")
            if claim["passed"]:
                break
        rec.put("report.md", report)
        return {"report": report, "classification": out.classification, "claim": claim}

    def finalize_node(state: RunState) -> RunState:
        rec.finish("done", classification=state["classification"], claim_check=state.get("claim"))
        return {}

    def fail_node(state: RunState) -> RunState:
        rec.finish("failed", error=state.get("last_error") or state.get("error"))
        return {}

    g = StateGraph(RunState)
    for name, fn in [("plan", plan_node), ("code", code_node), ("execute", execute_node), ("check", check_node),
                     ("retry", retry_node), ("analyse", analyse_node), ("finalize", finalize_node), ("fail", fail_node)]:
        g.add_node(name, fn)
    g.add_edge(START, "plan")
    g.add_edge("plan", "code")
    g.add_edge("code", "execute")
    g.add_edge("execute", "check")
    g.add_conditional_edges("check", route_after_check,
                            {"retry": "retry", "next": "code", "analyse": "analyse", "fail": "fail"})
    g.add_edge("retry", "code")
    g.add_edge("analyse", "finalize")
    g.add_edge("finalize", END)
    g.add_edge("fail", END)
    return g.compile()


def _merged_metrics(store, keys: list[str]) -> list[Metric]:
    out: list[Metric] = []
    for k in keys:
        out += [Metric.model_validate(m) for m in json.loads(store.get(k))]
    return out


def _parent_context(store, parent_id: str) -> str:
    parts = []
    for name in ("plan.md", "experiment_log.md", "report.md"):
        key = f"runs/{parent_id}/{name}"
        if store.exists(key):
            parts.append(f"### {name}\n{store.get(key).decode()}")
    return "\n\n".join(parts) or "(parent run has no files)"


def execute_run(run_id: str, req: RunRequest) -> None:
    """Run the whole graph synchronously (call from a worker thread). Never raises."""
    ctx = None
    if req.engine != "agents":
        from app.orchestration.engine_run import execute_engine_run

        try:
            execute_engine_run(run_id, req)
        finally:
            _after_run(run_id, req)
            bus.publish(run_id, "run_finished")
        return
    try:
        ctx = _Ctx(run_id, req)
        graph = build_graph(ctx)
        with trace_span(f"run {run_id}", input=req.model_dump()):
            graph.invoke({"run_id": run_id, "request": req.model_dump()}, {"recursion_limit": 200})
    except (LLMError, datasets.ManifestError, ValueError) as e:
        _fail(ctx, run_id, str(e))
    except Exception as e:  # noqa: BLE001 — a run must end in a recorded state whatever happens
        log.exception("run %s crashed", run_id)
        _fail(ctx, run_id, f"internal error: {e}\n{traceback.format_exc(limit=3)}")
    finally:
        if ctx and ctx.sandbox:
            ctx.sandbox.close()
        _after_run(run_id, req)
        bus.publish(run_id, "run_finished")


def _fail(ctx, run_id: str, message: str) -> None:
    rec = ctx.rec if ctx else Recorder(run_id, get_store())
    try:
        rec.log("orchestrator", f"run failed: {message.splitlines()[0]}")
    except Exception:
        pass
    rec.finish("failed", error=message)


def _after_run(run_id: str, req: RunRequest) -> None:
    """Index the report and post a summary into the chat. Failures here never fail the run."""
    from app.agents import copilot
    from app.retrieval import index

    try:
        index.index_run(run_id)
    except Exception as e:
        log.warning("indexing run %s failed: %s", run_id, e)
        bus.publish(run_id, "log", agent="retrieval", note=f"indexing skipped: {e}")
    try:
        copilot.post_run_summary(run_id, req.session_id)
    except Exception as e:
        log.warning("run summary for %s failed: %s", run_id, e)


def headline(metrics_rows) -> dict[str, Any] | None:
    a = next((m for m in metrics_rows if m.name == "a_refined"), None)
    return {"a_refined": a.value, "uncertainty": a.uncertainty, "unit": a.unit} if a else None
