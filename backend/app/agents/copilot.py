"""Chat co-pilot (LangChain Deep Agent) with read-only tools plus start_run, which only *proposes* a
run: the UI shows a confirm button, and nothing starts until the user clicks it.

Any number in an answer must appear in a tool result from the same turn; the claim checker runs on
every answer before it is shown, and untraced numbers are listed with the answer.
"""

import json
from collections.abc import Iterator
from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel
from sqlalchemy import select

from app.agents import checks, llm
from app.config import get_settings
from app.models.db import MessageRow, MetricRow, RunRow, StepRow, get_sessionmaker
from app.orchestration.events import bus
from app.retrieval import index
from app.storage import datasets
from app.storage.objects import get_store

MAX_ARTIFACT_CHARS = 20_000
HISTORY_TURNS = 12

SYSTEM = """You are the CoRefine co-pilot. You help two kinds of users:
- research data managers and curators: is a dataset documented, licensed, traceable and reproducible?
- scientists: does a measurement agree with simulation, which model explains it, what to do next?

What CoRefine holds: measured powder XRD datasets with manifests (list_datasets, get_dataset), agent
refinement runs on them (list_runs, get_run, query_metrics, read_artifact, compare_runs), DFT sets from
several codes with equations of state and Raman modes (list_dft_sets, get_dft_set), and tools that put
the two side by side (theory_vs_experiment, compare_pattern, identify_phase).

Rules:
- Answer from tool results, not memory. Fetch before you answer.
- Every number you state must appear in a tool result from this turn, copied with the same or
  fewer decimals. Do not compute new numbers. If you need a comparison, call compare_runs,
  theory_vs_experiment or compare_pattern.
- For metadata, licence or reproducibility questions call check_dataset_metadata and report each
  check as found or missing; do not declare a dataset "FAIR" or not, list what is and is not there.
- Say plainly what CoRefine cannot answer: it has no ARPES or band-structure comparison, no surface
  slabs or supercells, and no defect models. When a question needs those, say so and say what data or
  calculation would be needed instead.
- Suggestions for next measurements or calculations are allowed, but mark them as suggestions and do
  not attach numbers that no tool returned.
- When the user asks for a new or follow-up run, call start_run. It only proposes the run; tell the
  user to confirm it with the button that appears.
- Be brief: two to six sentences unless asked for more. Explain physics in plain language.
"""


def _clip(obj) -> str:
    text = json.dumps(obj, default=str)
    return text[:MAX_ARTIFACT_CHARS] + ("…(truncated)" if len(text) > MAX_ARTIFACT_CHARS else "")


def _metric_dict(m: MetricRow) -> dict:
    v = m.value if m.value is not None else (json.loads(m.value_text) if m.value_text else None)
    return {"name": m.name, "value": v, "unit": m.unit, "uncertainty": m.uncertainty, "source": m.source_key}


@tool
def list_runs(status: str | None = None, limit: int = 10) -> str:
    """List runs, newest first, with status, classification and refined lattice parameter."""
    with get_sessionmaker()() as db:
        q = select(RunRow).order_by(RunRow.started_at.desc().nulls_last()).limit(limit)
        if status:
            q = q.where(RunRow.status == status)
        out = []
        for r in db.scalars(q):
            a = db.scalar(select(MetricRow).where(MetricRow.run_id == r.id, MetricRow.name == "a_refined"))
            out.append({"id": r.id, "status": r.status, "prompt": r.prompt[:120], "parent_run_id": r.parent_run_id,
                        "classification": r.classification, "a_refined": _metric_dict(a) if a else None})
    return json.dumps(out, default=str)


@tool
def get_run(run_id: str) -> str:
    """Plan, step statuses, classification, claim-check result and report of one run."""
    store = get_store()
    with get_sessionmaker()() as db:
        r = db.get(RunRow, run_id)
        if r is None:
            return json.dumps({"error": f"no run {run_id}"})
        steps = [{"idx": s.idx, "name": s.name, "status": s.status, "attempts": s.attempts, "error": s.error}
                 for s in db.scalars(select(StepRow).where(StepRow.run_id == run_id).order_by(StepRow.idx))]
    key = f"runs/{run_id}/report.md"
    report = store.get(key).decode() if store.exists(key) else None
    return json.dumps({"id": r.id, "status": r.status, "prompt": r.prompt, "plan": r.plan, "steps": steps,
                       "classification": r.classification, "claim_check": r.claim_check, "error": r.error,
                       "report": report}, default=str)


@tool
def query_metrics(run_ids: list[str], names: list[str] | None = None) -> str:
    """Metric rows (name, value, unit, uncertainty, source file) for one or more runs."""
    with get_sessionmaker()() as db:
        q = select(MetricRow).where(MetricRow.run_id.in_(run_ids))
        if names:
            q = q.where(MetricRow.name.in_(names))
        rows = [{"run_id": m.run_id, **_metric_dict(m)} for m in db.scalars(q)]
    return json.dumps(rows)


@tool
def read_artifact(run_id: str, path: str) -> str:
    """Read a text file of a run, e.g. outputs/peaks.csv, plan.md, experiment_log.md, code/<file>.py, logs/<file>."""
    if ".." in path or path.startswith("/"):
        return "error: path must be relative to the run folder"
    key = f"runs/{run_id}/{path}"
    store = get_store()
    if not store.exists(key):
        return f"error: {path} not found in run {run_id}"
    if path.endswith(".png"):
        return "error: images are not readable as text"
    text = store.get(key).decode(errors="replace")
    return text[:MAX_ARTIFACT_CHARS] + ("\n…(truncated)" if len(text) > MAX_ARTIFACT_CHARS else "")


@tool
def search_knowledge(query: str, collection: str = "run_reports", material: str | None = None,
                     status: str | None = None) -> str:
    """Filtered semantic search. collection: run_reports | dataset_docs | reference_notes.
    Use for finding which runs or notes discuss something; read numbers with query_metrics."""
    filters = {k: v for k, v in {"material": material, "status": status}.items() if v}
    if collection != "run_reports":
        filters.pop("status", None)
    return json.dumps(index.search(collection, query, filters, limit=5))


@tool
def compare_runs(run_a: str, run_b: str) -> str:
    """Diff two runs: plan steps that changed, and every shared metric side by side with its difference."""
    with get_sessionmaker()() as db:
        ra, rb = db.get(RunRow, run_a), db.get(RunRow, run_b)
        if not ra or not rb:
            return json.dumps({"error": "run not found"})
        ma = {m.name: m for m in db.scalars(select(MetricRow).where(MetricRow.run_id == run_a))}
        mb = {m.name: m for m in db.scalars(select(MetricRow).where(MetricRow.run_id == run_b))}
    rows = []
    for name in sorted(ma.keys() & mb.keys()):
        a, b = ma[name], mb[name]
        diff = (b.value - a.value) if a.value is not None and b.value is not None else None
        rows.append({"name": name, "unit": a.unit, run_a: a.value, run_b: b.value, "difference_b_minus_a": diff,
                     "uncertainty_a": a.uncertainty, "uncertainty_b": b.uncertainty})
    steps_a = [(s["name"], s["goal"]) for s in (ra.plan or {}).get("steps", [])]
    steps_b = [(s["name"], s["goal"]) for s in (rb.plan or {}).get("steps", [])]
    changed = [{"a": a, "b": b} for a, b in zip(steps_a, steps_b) if a != b]
    return json.dumps({"metrics": rows, "plan_changes": changed,
                       "steps_only_in_a": steps_a[len(steps_b):], "steps_only_in_b": steps_b[len(steps_a):]})


@tool
def list_datasets() -> str:
    """Datasets in Storage: id, role (measured_pattern, reference_structure, ...), technique, material, format."""
    return _clip([{"id": r.id, "role": r.role, "technique": r.technique, "material": r.material, "format": r.format}
                  for r in datasets.list_indexed()])


@tool
def get_dataset(dataset_id: str) -> str:
    """Full manifest of one dataset (instrument, wavelength and its source, licence, checksums, reference
    values with their source), its README and the list of its files."""
    store = get_store()
    try:
        m = datasets.load_manifest(dataset_id, store)
    except datasets.ManifestError as e:
        return json.dumps({"error": str(e)})
    key = f"{datasets.PREFIX}{dataset_id}/README.md"
    files = [k.rsplit("/", 1)[-1] for k in datasets.dataset_files(m, store)]
    return _clip({"manifest": m.model_dump(exclude_none=True), "files": files, "n_files": len(files),
                  "readme": store.get(key).decode(errors="replace") if store.exists(key) else None})


@tool
def check_dataset_metadata(dataset_id: str) -> str:
    """Code-run metadata checks for one dataset: persistent identifier, licence, checksum, files, README,
    radiation, wavelength and its source, temperature, reference-value source and uncertainty."""
    from app.storage import fair

    try:
        m = datasets.load_manifest(dataset_id)
    except datasets.ManifestError as e:
        return json.dumps({"error": str(e)})
    results = fair.check(m)
    return json.dumps({"dataset": dataset_id, "checks": results,
                       "missing": [r["check"] for r in results if not r["ok"]]})


@tool
def list_dft_sets(material: str | None = None) -> str:
    """DFT input sets, newest first: id, formula, functional, k-mesh, codes, whether input checks passed.
    material: a formula such as Si or ZnO to filter by."""
    from app.api.bridge import _same
    from app.api.dft import list_jobs

    rows = list_jobs()
    if material:
        rows = [r for r in rows if _same(r["formula"], material)]
    return _clip(rows[:30])


@tool
def get_dft_set(set_id: str) -> str:
    """One DFT set: the request (structure source, functional, k-mesh), per-code inputs and the defaults
    they rely on, input checks, run results (energy, gap, convergence) and study results (convergence,
    equation of state, Raman). Use for provenance and reproducibility questions about simulations."""
    from fastapi import HTTPException

    from app.api.dft import get_job

    try:
        job = get_job(set_id)
    except (HTTPException, OSError, ValueError) as e:
        return json.dumps({"error": getattr(e, "detail", str(e))})
    prov = job["provenance"]
    checks_ = job["checks"]
    studies = job.get("studies") or {}
    for st in studies.values():  # drop curves; keep fits and settings
        if isinstance(st, dict):
            for c in (st.get("codes") or {}).values():
                if isinstance(c, dict):
                    c.pop("points", None)
            st.pop("spectrum", None)
    return _clip({"id": set_id, "provenance": prov, "checks_passed": checks_.get("passed"),
                  "failed_checks": [r for r in checks_.get("results", []) if not r.get("ok")],
                  "runs": job.get("runs"), "summary": job.get("summary"), "studies": studies,
                  "n_files": len(job.get("files", []))})


@tool
def theory_vs_experiment(material: str) -> str:
    """For one material (formula, e.g. Si): refined lattice parameters from XRD runs, certified values from
    dataset manifests, DFT a0 and B0 per code and functional with the percentage difference to experiment
    and the pressure equivalent, and Raman-active modes."""
    from app.api.bridge import bridge

    return _clip(bridge(material))


@tool
def compare_pattern(dataset_id: str, structure: str, file: str | None = None) -> str:
    """Match the peaks of a measured scan to the reflections of a model structure. structure: dataset:<id>
    (a reference or DFT structure in Storage), mp:<mp-id> or cod:<id>. Returns matched reflections, the best
    lattice scale, implied lattice parameters, strain, zero shift and unmatched peaks."""
    from fastapi import HTTPException

    from app.api.xrd import CompareBody, compare

    try:
        r = compare(CompareBody(dataset=dataset_id, structure=structure, file=file))
    except HTTPException as e:
        return json.dumps({"error": e.detail})
    for k in ("profile", "measured_peaks", "model_reflections"):
        r.pop(k, None)
    return _clip(r)


@tool
def identify_phase(dataset_id: str, file: str | None = None, formula: str | None = None) -> str:
    """Rank Materials Project polymorphs of the dataset's material (or `formula`) by how well their
    reflections explain the measured peaks."""
    from fastapi import HTTPException

    from app.api.xrd import IdentifyBody, identify

    try:
        return _clip(identify(IdentifyBody(dataset=dataset_id, file=file, formula=formula)))
    except HTTPException as e:
        return json.dumps({"error": e.detail})


@tool
def start_run(prompt: str, dataset_ids: list[str], parent_run_id: str | None = None) -> str:
    """Propose a new run. Does not start it: the user must confirm in the UI. A run needs at least one
    dataset with role measured_pattern; a reference structure alone cannot be refined."""
    # Same checks as POST /runs, so the user is told now instead of getting a 400 on confirm
    try:
        roles = {datasets.load_manifest(i).role for i in dataset_ids}
    except datasets.ManifestError as e:
        return json.dumps({"error": str(e)})
    if "measured_pattern" not in roles:
        return json.dumps({"error": "no dataset with role measured_pattern selected; ask the user to add a "
                                    "measured scan (e.g. nist-srm-640f, nist-srm-660c, nist-srm-1979-60nm) to the inputs"})
    return json.dumps({"proposed_run": {"prompt": prompt, "dataset_ids": dataset_ids, "parent_run_id": parent_run_id},
                       "note": "Waiting for the user to confirm in the UI."})


TOOLS = [list_runs, get_run, query_metrics, read_artifact, search_knowledge, compare_runs, list_datasets, get_dataset,
         check_dataset_metadata, list_dft_sets, get_dft_set, theory_vs_experiment, compare_pattern, identify_phase,
         start_run]


@lru_cache
def get_agent():
    from deepagents import create_deep_agent

    s = get_settings()
    model = ChatAnthropic(model=s.MODEL_FAST, max_tokens=8000, api_key=s.ANTHROPIC_API_KEY or None,
                          thinking={"type": "adaptive"}, output_config={"effort": "low"})
    return create_deep_agent(model=model, tools=TOOLS, system_prompt=SYSTEM, name="corefine-copilot")


def _history(session_id: str) -> list:
    with get_sessionmaker()() as db:
        rows = list(db.scalars(select(MessageRow).where(MessageRow.session_id == session_id)
                               .order_by(MessageRow.id.desc()).limit(HISTORY_TURNS)))
    msgs = []
    for r in reversed(rows):
        msgs.append(HumanMessage(r.content) if r.role == "user" else AIMessage(r.content))
    return msgs


def _save(session_id: str, role: str, content: str, run_id: str | None = None) -> None:
    with get_sessionmaker()() as db, db.begin():
        db.add(MessageRow(session_id=session_id, role=role, content=content, run_id=run_id))


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def chat(session_id: str, message: str, selected_dataset_ids: list[str] | None = None) -> Iterator[dict]:
    """Yields events: tool_call, tool_result, answer (with claim check and any proposed run)."""
    if not get_settings().ANTHROPIC_API_KEY:
        raise RuntimeError("The co-pilot needs ANTHROPIC_API_KEY in backend/.env; nothing was sent or saved.")
    history = _history(session_id)
    user = message if not selected_dataset_ids else f"{message}\n\n(Datasets selected in the UI: {selected_dataset_ids})"
    config = {"recursion_limit": 40}
    lf_handler = _langfuse_handler()
    if lf_handler:
        config["callbacks"] = [lf_handler]

    tool_texts: list[str] = []
    proposed = None
    final = ""
    for update in get_agent().stream({"messages": [*history, HumanMessage(user)]}, config, stream_mode="updates"):
        for node in update.values():
            for msg in (node or {}).get("messages", []) if isinstance(node, dict) else []:
                if isinstance(msg, AIMessage):
                    for tc in msg.tool_calls or []:
                        yield {"type": "tool_call", "name": tc["name"], "args": tc["args"]}
                    if not msg.tool_calls and _text(msg.content).strip():
                        final = _text(msg.content)
                elif isinstance(msg, ToolMessage):
                    text = _text(msg.content)
                    tool_texts.append(text)
                    if msg.name == "start_run":
                        try:
                            proposed = json.loads(text).get("proposed_run")
                        except json.JSONDecodeError:
                            pass
                    yield {"type": "tool_result", "name": msg.name, "chars": len(text)}
    allowed = [v for t in tool_texts for v in checks.numbers_in(t)]
    claim = checks.claim_check(final, allowed)
    # Saved only once the agent has answered, so a failed call (no key, API error) leaves no orphan question
    _save(session_id, "user", message)
    _save(session_id, "assistant", final)
    yield {"type": "answer", "content": final, "claim_check": claim, "proposed_run": proposed}


def _langfuse_handler():
    if not get_settings().langfuse_enabled:
        return None
    llm.get_langfuse()
    from langfuse.langchain import CallbackHandler

    return CallbackHandler()


class _Summary(BaseModel):
    text: str


def post_run_summary(run_id: str, session_id: str | None) -> None:
    """Open the conversation with a short summary of a finished run (from its metrics and report)."""
    if not session_id:
        return
    store = get_store()
    with get_sessionmaker()() as db:
        run = db.get(RunRow, run_id)
        metrics = [_metric_dict(m) for m in db.scalars(select(MetricRow).where(MetricRow.run_id == run_id))]
    report_key = f"runs/{run_id}/report.md"
    report = store.get(report_key).decode() if store.exists(report_key) else ""
    if run.status == "failed":
        text = f"Run {run_id} failed: {(run.error or 'unknown error').splitlines()[0]}"
    else:
        out = llm.parse(
            agent="run_summary", model=get_settings().MODEL_FAST, effort="low", max_tokens=2000,
            system="Summarise a finished analysis run in two or three sentences for the researcher. Copy numbers "
                   "exactly from the metrics; do not compute new ones. Mention the classification.",
            content=f"Run {run_id}, classification {run.classification}.\nMetrics: {json.dumps(metrics)}\n\nReport:\n{report}",
            output=_Summary,
        )
        text = out.text
        claim = checks.claim_check(text, [v for m in metrics for v in (m["value"], m["uncertainty"])
                                          if isinstance(v, (int, float)) and not isinstance(v, bool)])
        if not claim["passed"]:
            text += "\n\n_Claim check: untraced numbers " + ", ".join(u["number"] for u in claim["untraced"]) + "._"
    _save(session_id, "assistant", text, run_id)
    bus.publish(run_id, "chat_message", session_id=session_id, role="assistant", content=text)
