import functools
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(local_env, no_index):
    from app.main import app

    with TestClient(app) as c:
        yield c


MANIFEST = {"id": "my-scan", "role": "measured_pattern", "technique": "xrd_powder", "material": "Si",
            "format": "pdcif", "files": ["raw/*.cif"], "instrument": {"radiation": "CuKa1", "wavelength_A": 1.5405929}}


def test_ping(client):
    assert client.get("/ping").json()["ok"]


def test_invalid_manifest_rejected_with_reason(client):
    r = client.post("/datasets", json={"manifest": {**MANIFEST, "role": "banana"}})
    assert r.status_code == 400 and "role" in r.json()["detail"]


def test_upload_without_manifest_rejected(client):
    r = client.post("/datasets/no-manifest/files", files=[("files", ("a.cif", b"data_x\n", "text/plain"))])
    assert r.status_code == 400 and "no dataset.yaml" in r.json()["detail"]


def test_broken_cif_rejected(client):
    assert client.post("/datasets", json={"manifest": MANIFEST}).status_code == 200
    r = client.post("/datasets/my-scan/files", files=[("files", ("bad.cif", b"loop_\n_x\n'unterminated", "text/plain"))])
    assert r.status_code == 400 and "bad.cif" in r.json()["detail"]
    r = client.post("/datasets/my-scan/files", files=[("files", ("s.cif", b"data_s\n_cell_length_a 5.43\n", "text/plain"))])
    assert r.status_code == 400 and "powder pattern" in r.json()["detail"]


def test_tree_flags_folder_without_manifest(client):
    from app.storage.objects import get_store

    get_store().put("datasets/orphan/raw/x.cif", b"data_x\n")
    nodes = {n["id"]: n for n in client.get("/datasets").json()}
    assert nodes["orphan"]["valid"] is False and "no dataset.yaml" in nodes["orphan"]["problem"]
    r = client.post("/runs", json={"prompt": "refine", "dataset_ids": ["orphan"]})
    assert r.status_code == 400 and "no dataset.yaml" in r.json()["detail"]


def test_run_api_and_sse(seeded, client, monkeypatch, gold_code):
    from test_runner_and_run import plan_one_step

    from app.agents import llm
    from app.models.contracts import AnalystOutput, CoderOutput

    def fake_parse(*, agent, output, **kw):
        return {"planner": plan_one_step, "coder": lambda: CoderOutput(code=gold_code, notes="gold"),
                "analyst": lambda: AnalystOutput(classification="agreement", agrees_with_rule=True,
                                                 report_markdown="# Result\nAgreement.\n"),
                }.get(agent, lambda: output(text="done"))()

    monkeypatch.setattr(llm, "parse", fake_parse)
    rid = client.post("/runs", json={"prompt": "Refine silicon", "dataset_ids": ["nist-srm-640f", "cod-9008565-si"],
                                     "session_id": "sess-1"}).json()["id"]
    statuses, activities = [], []
    with client.stream("GET", f"/runs/{rid}/events") as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                ev = json.loads(line[5:])
                if ev["type"] == "step":
                    statuses.append(ev["step"]["status"])
                if ev["type"] == "activity":
                    activities.append(ev["agent"])
                if ev["type"] == "run_finished":
                    break
    assert statuses[0] == "running" and statuses[-1] == "done"
    assert activities == ["sandbox", "planner", "coder", "sandbox", "checker", "checker", "analyst", "claim_checker"]
    detail = client.get(f"/runs/{rid}").json()
    assert detail["status"] == "done" and detail["headline"]["a_refined"] == pytest.approx(5.430862, abs=1e-6)
    assert client.get(f"/runs/{rid}/artifacts/outputs/fit.png").headers["content-type"] == "image/png"
    listed = client.get("/runs").json()[0]
    assert listed["id"] == rid and listed["title"] == detail["plan"]["title"] and listed["archived"] is False
    assert client.patch(f"/runs/{rid}", json={"archived": True}).json()["archived"] is True
    assert client.get("/runs").json()[0]["archived"] is True
    assert client.patch("/runs/no-such-run", json={"archived": True}).status_code == 404
    msgs = client.get("/chat/sess-1").json()
    assert msgs and msgs[-1]["run_id"] == rid


def test_chat_passes_open_run_to_agent(local_env, monkeypatch):
    from langchain_core.messages import AIMessage

    from app.agents import copilot

    seen = {}

    class FakeAgent:
        def stream(self, inp, config, stream_mode):
            seen["user"] = inp["messages"][-1].content
            yield {"model": {"messages": [AIMessage("It agrees.")]}}

    monkeypatch.setattr(copilot, "get_agent", functools.cache(FakeAgent))  # teardown calls cache_clear
    events = list(copilot.chat("sess-ctx", "Explain this run", ["nist-srm-640f"], "run-2026-10-22-002"))
    assert events[-1]["content"] == "It agrees."
    assert "Run open on screen: run-2026-10-22-002" in seen["user"] and "nist-srm-640f" in seen["user"]
