"""One analysis run told as reasoning steps, read only from the run's records (shown under Reasoning)."""

import json
import re

from sqlalchemy import select

from app.models.db import MetricRow, RunRow, StepRow

_LOG_LINE = re.compile(r"^- \*\*(\d\d:\d\d:\d\d) · ([^*]+)\*\* — (.*)$")


def log_entries(store, run_id: str) -> list[dict]:
    key = f"runs/{run_id}/experiment_log.md"
    if not store.exists(key):
        return []
    out = []
    for ln in store.get(key).decode(errors="replace").splitlines():
        m = _LOG_LINE.match(ln)
        if m:
            out.append({"time": m.group(1), "agent": m.group(2), "note": m.group(3)})
    return out


def run_story(db, store, r: RunRow) -> dict:
    """Plan, each step with its goal, attempts and errors, the notes every agent or program logged, and the
    result compared with the certificate."""
    ms = {m.name: {"value": m.value, "uncertainty": m.uncertainty, "unit": m.unit}
          for m in db.scalars(select(MetricRow).where(MetricRow.run_id == r.id))}
    steps = [{"idx": s.idx, "name": s.name, "status": s.status, "attempts": s.attempts, "error": s.error}
             for s in db.scalars(select(StepRow).where(StepRow.run_id == r.id).order_by(StepRow.idx))]
    goals = {st["idx"]: st.get("goal") for st in ((r.plan or {}).get("steps") or [])}
    for s in steps:
        s["goal"] = goals.get(s["idx"])
    engine_result = {}
    key = f"runs/{r.id}/outputs/result.json"
    if store.exists(key):
        res = json.loads(store.get(key))
        engine_result = {"stages": res.get("stages"), "settings": res.get("settings"), "warnings": res.get("warnings")}
    return {
        "run": r.id, "engine": r.engine or "agents", "status": r.status, "prompt": r.prompt,
        "datasets": r.dataset_ids, "group_id": r.group_id, "error": r.error,
        "plan_title": (r.plan or {}).get("title"), "plan_summary": (r.plan or {}).get("summary"),
        "steps": steps, "log": log_entries(store, r.id), "classification": r.classification,
        "claim": {k: (r.claim_check or {}).get(k) for k in ("passed", "checked")} if r.claim_check else None,
        "result": {k: ms[k] for k in ("a_refined", "c_refined", "a_certified", "c_certified", "difference_from_certified",
                                      "c_difference_from_certified", "Rwp") if k in ms},
        **engine_result}
