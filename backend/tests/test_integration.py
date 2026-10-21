"""Real services, real Claude. Skipped by default; run with:

    uv run pytest -m integration -s

They read backend/.env as it is (not the local test env), so they need real keys there.
"""

import os
import subprocess
import sys

import pytest
from conftest import BACKEND

pytestmark = pytest.mark.integration

GATE2 = """
import json, os
from app.config import get_settings
from app.models.contracts import RunRequest
from app.models.db import RunRow, MetricRow, get_sessionmaker, init_db
from app.api.runs import _new_run_id
from app.orchestration.graph import execute_run

init_db()
req = RunRequest(prompt="Refine silicon's lattice parameter from the 640f scan and compare it with the certified value.",
                 dataset_ids=["nist-srm-640f", "cod-9008565-si"], session_id="integration")
rid = _new_run_id()
with get_sessionmaker()() as db, db.begin():
    db.add(RunRow(id=rid, prompt=req.prompt, dataset_ids=req.dataset_ids, session_id="integration"))
execute_run(rid, req)
with get_sessionmaker()() as db:
    r = db.get(RunRow, rid)
    ms = {m.name: m.value for m in db.query(MetricRow).filter_by(run_id=rid) if m.value is not None}
print(json.dumps({"id": rid, "status": r.status, "error": r.error, "claim": r.claim_check,
                  "classification": r.classification, "a": ms.get("a_refined"),
                  "diff": ms.get("difference_from_certified")}))
"""


def _env():
    env = {k: v for k, v in os.environ.items() if k not in ("COREFINE_MODE", "LOCAL_DATA_DIR", "ANTHROPIC_API_KEY",
                                                            "LLM_SERVER_FALLBACKS")}
    return env


def test_health_all_ok():
    out = subprocess.run([sys.executable, "-c", "import json; from fastapi.testclient import TestClient;"
                          "from app.main import app;\nwith TestClient(app) as c: print(json.dumps(c.get('/health').json()))"],
                         cwd=BACKEND, env=_env(), capture_output=True, text=True, timeout=120)
    print(out.stdout, out.stderr[-2000:])
    assert '"all_ok": true' in out.stdout


def test_gate2_one_prompt_to_traced_report():
    """Gate 2: one prompt yields a report with refined a within target and all numbers traced."""
    import json

    out = subprocess.run([sys.executable, "-c", GATE2], cwd=BACKEND, env=_env(), capture_output=True, text=True,
                         timeout=900)
    print(out.stderr[-3000:])
    res = json.loads(out.stdout.strip().splitlines()[-1])
    print(res)
    assert res["status"] == "done", res["error"]
    assert res["claim"]["passed"], res["claim"]
    assert abs(res["diff"]) <= 0.0005
