import asyncio
import json
import mimetypes
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from sqlalchemy import func, select

from app.models.contracts import RunRequest
from app.models.db import ArtifactRow, MetricRow, RunRow, StepRow, get_sessionmaker
from app.orchestration.events import bus
from app.orchestration.graph import execute_run, headline
from app.storage import datasets
from app.storage.objects import get_store

router = APIRouter(prefix="/runs", tags=["runs"])
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="run")
_id_lock = threading.Lock()


ACTIVE = ("queued", "planning", "running", "analysing")


def fail_interrupted_runs() -> list[str]:
    """Runs execute in this process's threads, so any run still active at startup was cut off.
    Assumes a single backend process: a second worker starting would fail the first one's live runs."""
    from sqlalchemy import update

    with get_sessionmaker()() as db, db.begin():
        ids = list(db.scalars(select(RunRow.id).where(RunRow.status.in_(ACTIVE))))
        if ids:
            db.execute(update(RunRow).where(RunRow.id.in_(ids)).values(
                status="failed", finished_at=datetime.now(UTC),
                error="interrupted: the backend restarted while this run was in progress"))
            db.execute(update(StepRow).where(StepRow.run_id.in_(ids), StepRow.status.in_(("running", "retrying")))
                       .values(status="failed", error="interrupted by a backend restart"))
    return ids


def _new_run_id() -> str:
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    with _id_lock, get_sessionmaker()() as db:
        n = db.scalar(select(func.count()).select_from(RunRow).where(RunRow.id.like(f"run-{day}-%"))) or 0
        return f"run-{day}-{n + 1:03d}"


def start_runs(req: RunRequest) -> dict:
    """One run per selected engine. With more than one, they share a group_id so they can be compared."""
    from app.xrd import engines

    for e in req.engines:
        ok, why = engines.available(e)
        if not ok:
            raise HTTPException(400, detail=why)
    group = f"grp-{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}" if len(req.engines) > 1 else None
    ids = [start_run(req.model_copy(update={"engine": e, "group_id": group})) for e in dict.fromkeys(req.engines)]
    return {"id": ids[0], "ids": ids, "group_id": group}


def start_run(req: RunRequest) -> str:
    for ds_id in req.dataset_ids:
        try:
            datasets.load_manifest(ds_id)
        except datasets.ManifestError as e:
            raise HTTPException(400, detail=str(e)) from e
    roles = {datasets.load_manifest(i).role for i in req.dataset_ids}
    if "measured_pattern" not in roles:
        raise HTTPException(400, detail="select at least one dataset with role measured_pattern")
    with get_sessionmaker()() as db:
        if req.parent_run_id and not db.get(RunRow, req.parent_run_id):
            raise HTTPException(400, detail=f"parent run {req.parent_run_id} does not exist")
    run_id = _new_run_id()
    with get_sessionmaker()() as db, db.begin():
        db.add(RunRow(id=run_id, prompt=req.prompt, dataset_ids=req.dataset_ids, status="queued",
                      parent_run_id=req.parent_run_id, session_id=req.session_id, engine=req.engine,
                      group_id=req.group_id))
    bus.publish(run_id, "run_status", status="queued")
    _pool.submit(execute_run, run_id, req)
    return run_id


@router.post("")
def create_run(req: RunRequest):
    return start_runs(req)


@router.get("/engines")
def list_engines():
    from app.dft import tools
    from app.xrd import engines

    state = {x["name"]: x for x in tools.status()}
    return [{"name": n, **e, "available": engines.available(n)[0], "reason": engines.available(n)[1],
             "install": {k: state[e["tool"]][k] for k in ("status", "message", "size", "license")} if e["tool"] else None}
            for n, e in engines.ENGINES.items()]


@router.get("/group/{group_id}")
def group(group_id: str):
    from app.orchestration.engine_run import group_view

    return group_view(group_id)


@router.get("")
def list_runs(limit: int = 50):
    with get_sessionmaker()() as db:
        runs = list(db.scalars(select(RunRow).order_by(RunRow.id.desc()).limit(limit)))
        out = []
        for r in runs:
            ms = list(db.scalars(select(MetricRow).where(MetricRow.run_id == r.id, MetricRow.name == "a_refined")))
            out.append({"id": r.id, "prompt": r.prompt, "title": (r.plan or {}).get("title"), "status": r.status,
                        "dataset_ids": r.dataset_ids, "error": (r.error or "")[:400] or None,
                        "archived": bool(r.archived), "engine": r.engine or "agents", "group_id": r.group_id,
                        "parent_run_id": r.parent_run_id, "classification": r.classification,
                        "claim_passed": (r.claim_check or {}).get("passed"),
                        "started_at": r.started_at, "finished_at": r.finished_at, "headline": headline(ms)})
    return out


class RunPatch(BaseModel):
    archived: bool


@router.patch("/{run_id}")
def patch_run(run_id: str, body: RunPatch):
    """Archiving only hides a run from the default list; nothing is deleted."""
    with get_sessionmaker()() as db, db.begin():
        r = db.get(RunRow, run_id)
        if r is None:
            raise HTTPException(404, detail=f"no run {run_id}")
        r.archived = body.archived
    return {"id": run_id, "archived": body.archived}


@router.get("/compare")
def compare(a: str, b: str):
    from app.agents.copilot import compare_runs

    return json.loads(compare_runs.invoke({"run_a": a, "run_b": b}))


@router.get("/{run_id}")
def get_run(run_id: str):
    with get_sessionmaker()() as db:
        r = db.get(RunRow, run_id)
        if r is None:
            raise HTTPException(404, detail=f"no run {run_id}")
        steps = list(db.scalars(select(StepRow).where(StepRow.run_id == run_id).order_by(StepRow.idx)))
        metrics = list(db.scalars(select(MetricRow).where(MetricRow.run_id == run_id).order_by(MetricRow.id)))
        arts = list(db.scalars(select(ArtifactRow).where(ArtifactRow.run_id == run_id).order_by(ArtifactRow.id)))
    prefix = f"runs/{run_id}/"
    return {
        "id": r.id, "prompt": r.prompt, "status": r.status, "dataset_ids": r.dataset_ids, "plan": r.plan,
        "error": r.error, "classification": r.classification, "claim_check": r.claim_check,
        "parent_run_id": r.parent_run_id, "started_at": r.started_at, "finished_at": r.finished_at,
        "engine": r.engine or "agents", "group_id": r.group_id,
        "steps": [{"idx": s.idx, "name": s.name, "status": s.status, "attempts": s.attempts, "error": s.error,
                   "code_key": s.code_key and s.code_key.removeprefix(prefix),
                   "stdout_key": s.stdout_key and s.stdout_key.removeprefix(prefix)} for s in steps],
        "metrics": [{"name": m.name, "value": m.value if m.value is not None else m.value_text, "unit": m.unit,
                     "uncertainty": m.uncertainty, "method": m.method,
                     "source": m.source_key.removeprefix(prefix)} for m in metrics],
        "artifacts": [{"step_idx": a.step_idx, "kind": a.kind, "path": a.key.removeprefix(prefix), "sha256": a.sha256}
                      for a in arts],
        "headline": headline(metrics),
    }


@router.get("/{run_id}/events", response_class=EventSourceResponse)
async def run_events(run_id: str, request: Request):
    i = 0
    while True:
        if await request.is_disconnected():
            return
        events = bus.since(run_id, i)
        for ev in events:
            yield ServerSentEvent(data=ev, event=ev["type"])
        i += len(events)
        if events and events[-1]["type"] == "run_finished":
            return
        if not events:
            with get_sessionmaker()() as db:
                r = db.get(RunRow, run_id)
            if r is None:
                yield ServerSentEvent(data={"error": "no such run"}, event="error")
                return
            if r.status in ("done", "failed") and not bus.since(run_id, 0):
                yield ServerSentEvent(data={"type": "run_finished", "run_id": run_id}, event="run_finished")
                return
        await asyncio.sleep(0.4)


@router.get("/{run_id}/artifacts/{path:path}")
def artifact(run_id: str, path: str):
    if ".." in path:
        raise HTTPException(400, detail="bad path")
    store, key = get_store(), f"runs/{run_id}/{path}"
    if not store.exists(key):
        raise HTTPException(404, detail=f"{path} not found")
    media = mimetypes.guess_type(path)[0] or "text/plain"
    if path.endswith((".md", ".py", ".stdout", ".stderr", ".log")):
        media = "text/plain; charset=utf-8"
    return Response(store.get(key), media_type=media)
