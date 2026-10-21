import json

from app.models.db import MetricRow, RunRow, get_sessionmaker


def test_filtered_search_returns_only_matching_material(local_env):
    from app.retrieval import index

    index.index_note("si-note", "xrd_powder", "Si", "Silicon lattice parameter refinement note")
    index.index_note("ge-note", "xrd_powder", "Ge", "Germanium lattice parameter refinement note")
    hits = index.search("reference_notes", "lattice parameter refinement", {"material": "Si"})
    assert hits and {h["material"] for h in hits} == {"Si"}


def _run_with_a(run_id: str, a: float):
    with get_sessionmaker()() as db, db.begin():
        db.add(RunRow(id=run_id, prompt="p", dataset_ids=["x"], status="done",
                      plan={"steps": [{"name": "refine", "goal": f"goal {run_id}"}]}))
        db.add(MetricRow(run_id=run_id, name="a_refined", value=a, unit="angstrom", uncertainty=3e-5,
                         source_key=f"runs/{run_id}/outputs/step_01/metrics.json"))


def test_compare_runs_tool(local_env):
    from app.agents.copilot import compare_runs, query_metrics

    _run_with_a("run-a", 5.430862)
    _run_with_a("run-b", 5.430900)
    out = json.loads(compare_runs.invoke({"run_a": "run-a", "run_b": "run-b"}))
    row = out["metrics"][0]
    assert row["name"] == "a_refined" and abs(row["difference_b_minus_a"] - 3.8e-5) < 1e-9
    assert len(out["plan_changes"]) == 1
    rows = json.loads(query_metrics.invoke({"run_ids": ["run-a"], "names": ["a_refined"]}))
    assert rows[0]["value"] == 5.430862


def test_start_run_only_proposes(seeded):
    from app.agents.copilot import start_run

    out = json.loads(start_run.invoke({"prompt": "rerun", "dataset_ids": ["nist-srm-640f"], "parent_run_id": "run-a"}))
    assert out["proposed_run"]["parent_run_id"] == "run-a"
    with get_sessionmaker()() as db:
        assert db.query(RunRow).count() == 0


def test_start_run_needs_measured_pattern(seeded):
    from app.agents.copilot import start_run

    out = json.loads(start_run.invoke({"prompt": "run", "dataset_ids": ["cod-9008565-si"]}))
    assert "proposed_run" not in out and "measured_pattern" in out["error"]
    out = json.loads(start_run.invoke({"prompt": "run", "dataset_ids": ["no-such-dataset"]}))
    assert "proposed_run" not in out


def test_read_artifact_rejects_traversal(local_env):
    from app.agents.copilot import read_artifact

    assert read_artifact.invoke({"run_id": "r", "path": "../secrets"}).startswith("error")
