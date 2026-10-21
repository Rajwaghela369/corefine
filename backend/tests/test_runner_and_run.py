"""Sandbox runner and the full run graph, with the LLM mocked and everything else real."""

import json

import pytest

from app.agents import llm
from app.models.contracts import AnalystOutput, CoderOutput, Plan
from app.sandbox.local_runner import LocalRunner
from app.storage import datasets

GOLD_A = 5.430862  # scan cif_gen_20180612_073551, from skills/examples/gold_outputs/metrics.json


@pytest.fixture
def session(seeded):
    from app.config import get_settings

    s = LocalRunner(get_settings()).open("t-run")
    s.stage_inputs(datasets.staged_inputs(["nist-srm-640f", "cod-9008565-si"]))
    yield s
    s.close()


def test_staged_inputs_hide_the_answer(seeded):
    files = datasets.staged_inputs(["nist-srm-640f", "cod-9008565-si"])
    cifs = [v for k, v in files.items() if k.startswith("nist-srm-640f/raw/")]
    assert cifs and all(b"5.431144" not in c and b"_calc" not in c for c in cifs)
    assert b"reference_values" not in files["nist-srm-640f/dataset.yaml"]


def test_gold_through_runner_reproduces_gold_metrics(session, gold_code):
    r = session.run(gold_code, "gold.py", timeout_s=120)
    assert r.exit_code == 0, r.stderr
    metrics = {m["name"]: m for m in json.loads(r.files["metrics.json"])}
    assert metrics["a_refined"]["value"] == pytest.approx(GOLD_A, abs=1e-6)
    assert {"peaks.csv", "fit.png"} <= r.files.keys()


def test_runner_blocks_network(session):
    code = "import urllib.request\nurllib.request.urlopen('https://example.com', timeout=5)\n"
    r = session.run(code, "net.py", timeout_s=30)
    assert r.exit_code != 0 and "network access is disabled" in r.stderr


def test_runner_timeout(session):
    r = session.run("import time\ntime.sleep(10)\n", "slow.py", timeout_s=1)
    assert r.timed_out and "time limit" in r.stderr


def test_runner_output_limit(session, monkeypatch):
    from app.sandbox.base import OutputLimitError

    monkeypatch.setattr(session.settings, "MAX_OUTPUT_BYTES", 1000)
    code = ("import os\nfrom pathlib import Path\nw=Path(os.environ['COREFINE_WORK'])/'outputs'\n"
            "(w/'big.bin').write_bytes(b'0'*5000)\n")
    with pytest.raises(OutputLimitError):
        session.run(code, "big.py", timeout_s=30)


# --- Full run with mocked agents ----------------------------------------------

BROKEN = "import numpy as np\nraise ValueError('deliberately broken first attempt')\n"


def plan_one_step():
    return Plan.model_validate({"title": "Refine Si a", "summary": "One-step refinement", "steps": [{
        "idx": 1, "name": "refine", "goal": "fit peaks and refine a", "dataset_ids": ["nist-srm-640f", "cod-9008565-si"],
        "outputs": ["peaks.csv", "fit.png", "metrics.json"], "skill": "xrd_powder_refinement.md"}]})


@pytest.fixture
def mock_agents(monkeypatch, gold_code):
    calls = {"coder": 0, "analyst": 0}

    def fake_parse(*, agent, output, content, **kw):
        if agent == "planner":
            return plan_one_step()
        if agent == "coder":
            calls["coder"] += 1
            if calls["coder"] == 1:
                return CoderOutput(code=BROKEN, notes="first try")
            assert "deliberately broken" in content  # stderr tail fed back on retry
            return CoderOutput(code=gold_code, notes="fixed")
        if agent == "analyst":
            calls["analyst"] += 1
            text = content[-1]["text"]
            metrics = json.loads(text.split("Metrics (from metrics.json and orchestrator comparisons):\n")[1]
                                 .split("\n\nManifests")[0])
            a = next(m for m in metrics if m["name"] == "a_refined")
            invented = " It is probably 5.4321 Å." if calls["analyst"] == 1 else ""
            return AnalystOutput(classification="agreement", agrees_with_rule=True,
                                 report_markdown=f"# Result\n\n## Result\na = {a['value']:.6f} Å [a_refined].{invented}\n")
        if agent == "run_summary":
            return output(text="Run finished.")
        raise AssertionError(agent)

    monkeypatch.setattr(llm, "parse", fake_parse)
    return calls


def test_full_run_self_heals_and_traces(seeded, mock_agents, no_index):
    from app.models.contracts import RunRequest
    from app.models.db import MetricRow, RunRow, StepRow, get_sessionmaker
    from app.orchestration.events import bus
    from app.orchestration.graph import execute_run
    from app.storage.objects import get_store

    with get_sessionmaker()() as db, db.begin():
        db.add(RunRow(id="run-test-001", prompt="p", dataset_ids=["nist-srm-640f", "cod-9008565-si"], session_id="s1"))
    execute_run("run-test-001", RunRequest(prompt="Refine silicon's lattice parameter",
                                           dataset_ids=["nist-srm-640f", "cod-9008565-si"], session_id="s1"))
    store = get_store()
    with get_sessionmaker()() as db:
        run = db.get(RunRow, "run-test-001")
        step = db.get(StepRow, ("run-test-001", 1))
        metrics = {m.name: m for m in db.query(MetricRow).filter_by(run_id="run-test-001")}
    assert run.status == "done", run.error
    assert step.status == "done" and step.attempts == 2
    assert metrics["a_refined"].value == pytest.approx(GOLD_A, abs=1e-6)
    # metric rows equal the file exactly
    file_a = next(m for m in json.loads(store.get(metrics["a_refined"].source_key)) if m["name"] == "a_refined")
    assert metrics["a_refined"].value == file_a["value"]
    assert metrics["within_target"].value_text == "true"
    # first analyst report had an invented number; the second passed the claim checker
    assert mock_agents["analyst"] == 2 and run.claim_check["passed"]
    for f in ("plan.json", "plan.md", "report.md", "experiment_log.md", "code/step_01_refine.py",
              "code/step_01_refine.v2.py", "outputs/peaks.csv", "outputs/fit.png", "outputs/comparison.json"):
        assert store.exists(f"runs/run-test-001/{f}"), f
    log = store.get("runs/run-test-001/experiment_log.md").decode()
    assert "attempt 1 failed" in log and "claim_checker" in log
    types = [e["type"] for e in bus.since("run-test-001", 0)]
    assert types[-1] == "run_finished" and "chat_message" in types


def test_run_fails_cleanly_after_max_attempts(seeded, monkeypatch, no_index):
    from app.models.contracts import RunRequest
    from app.models.db import RunRow, StepRow, get_sessionmaker
    from app.orchestration.graph import execute_run

    def fake_parse(*, agent, output, **kw):
        if agent == "planner":
            return plan_one_step()
        if agent == "coder":
            return CoderOutput(code=BROKEN, notes="still broken")
        return output(text="x")

    monkeypatch.setattr(llm, "parse", fake_parse)
    with get_sessionmaker()() as db, db.begin():
        db.add(RunRow(id="run-test-002", prompt="p", dataset_ids=["nist-srm-640f", "cod-9008565-si"]))
    execute_run("run-test-002", RunRequest(prompt="refine", dataset_ids=["nist-srm-640f", "cod-9008565-si"]))
    with get_sessionmaker()() as db:
        run, step = db.get(RunRow, "run-test-002"), db.get(StepRow, ("run-test-002", 1))
    assert run.status == "failed" and "deliberately broken" in run.error
    assert step.status == "failed" and step.attempts == 3
