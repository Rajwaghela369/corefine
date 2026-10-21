"""Every side effect of a run: files to the bucket, rows to the database, events to the bus.

Bucket layout per run (spec):
  runs/<id>/plan.json, plan.md, report.md, experiment_log.md
  runs/<id>/code/step_02_fit.py, step_02_fit.v2.py ...
  runs/<id>/logs/step_02.stdout, step_02.stderr (.v2 ...)
  runs/<id>/outputs/step_02/<file>   per-step outputs
  runs/<id>/outputs/<file>           latest version of each output, for the UI tabs
"""

import json
import mimetypes
from datetime import datetime

from sqlalchemy import delete

from app.models.contracts import Metric
from app.models.db import ArtifactRow, MetricRow, RunRow, StepRow, get_sessionmaker, utcnow
from app.orchestration.events import bus
from app.storage.objects import ObjectStore


def artifact_kind(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower()
    return {"png": "plot", "csv": "csv", "json": "json", "md": "report", "py": "code"}.get(ext, "text")


class Recorder:
    def __init__(self, run_id: str, store: ObjectStore):
        self.run_id, self.store = run_id, store
        self.prefix = f"runs/{run_id}/"
        self._log: list[str] = [f"# Experiment log — {run_id}", ""]

    # --- files ---
    def put(self, rel: str, data: bytes | str, step_idx: int | None = None, record: bool = True) -> str:
        data = data.encode() if isinstance(data, str) else data
        key = self.prefix + rel
        digest = self.store.put(key, data, mimetypes.guess_type(rel)[0])
        if record:
            with get_sessionmaker()() as db, db.begin():
                db.add(ArtifactRow(run_id=self.run_id, step_idx=step_idx, kind=artifact_kind(rel), key=key, sha256=digest))
        return key

    def log(self, agent: str, note: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._log.append(f"- **{stamp} · {agent}** — {note}")
        self.put("experiment_log.md", "\n".join(self._log) + "\n", record=False)
        bus.publish(self.run_id, "log", agent=agent, note=note)

    # --- rows ---
    def run_update(self, **fields) -> None:
        with get_sessionmaker()() as db, db.begin():
            row = db.get(RunRow, self.run_id)
            for k, v in fields.items():
                setattr(row, k, v)
        if "status" in fields:
            bus.publish(self.run_id, "run_status", status=fields["status"])

    def steps_init(self, steps: list[tuple[int, str]]) -> None:
        with get_sessionmaker()() as db, db.begin():
            db.execute(delete(StepRow).where(StepRow.run_id == self.run_id))
            for idx, name in steps:
                db.add(StepRow(run_id=self.run_id, idx=idx, name=name, status="pending"))
        bus.publish(self.run_id, "steps", steps=[{"idx": i, "name": n, "status": "pending"} for i, n in steps])

    def step_update(self, idx: int, **fields) -> None:
        with get_sessionmaker()() as db, db.begin():
            row = db.get(StepRow, (self.run_id, idx))
            for k, v in fields.items():
                setattr(row, k, v)
            snapshot = {"idx": idx, "name": row.name, "status": row.status, "attempts": row.attempts,
                        "error": row.error, "code_key": row.code_key, "stdout_key": row.stdout_key}
        bus.publish(self.run_id, "step", step=snapshot)

    def ingest_metrics(self, source_key: str) -> list[Metric]:
        """Metrics rows come only from a metrics file in the bucket, read back from the bucket."""
        items = [Metric.model_validate(m) for m in json.loads(self.store.get(source_key))]
        with get_sessionmaker()() as db, db.begin():
            for m in items:
                numeric = isinstance(m.value, (int, float)) and not isinstance(m.value, bool)
                db.add(MetricRow(
                    run_id=self.run_id, name=m.name,
                    value=float(m.value) if numeric else None,
                    value_text=None if numeric else json.dumps(m.value),
                    unit=m.unit, uncertainty=m.uncertainty, method=m.method, source_key=source_key,
                ))
        return items

    def finish(self, status: str, **fields) -> None:
        self.run_update(status=status, finished_at=utcnow(), **fields)
