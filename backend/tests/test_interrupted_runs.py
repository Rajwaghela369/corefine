from app.api.runs import fail_interrupted_runs
from app.models.db import RunRow, StepRow, get_sessionmaker


def test_active_runs_are_failed_on_startup():
    with get_sessionmaker()() as db, db.begin():
        for rid, status in [("run-a", "running"), ("run-b", "queued"), ("run-c", "done"), ("run-d", "failed")]:
            db.add(RunRow(id=rid, prompt="p", dataset_ids=[], status=status))
        db.add(StepRow(run_id="run-a", idx=1, name="s1", status="done"))
        db.add(StepRow(run_id="run-a", idx=2, name="s2", status="running"))
        db.add(StepRow(run_id="run-a", idx=3, name="s3", status="pending"))

    assert sorted(fail_interrupted_runs()) == ["run-a", "run-b"]

    with get_sessionmaker()() as db:
        assert {r.id: r.status for r in db.query(RunRow)} == {
            "run-a": "failed", "run-b": "failed", "run-c": "done", "run-d": "failed"}
        a = db.get(RunRow, "run-a")
        assert "interrupted" in a.error and a.finished_at is not None
        assert db.get(RunRow, "run-c").error is None
        assert [s.status for s in db.query(StepRow).order_by(StepRow.idx)] == ["done", "failed", "pending"]
    assert fail_interrupted_runs() == []
