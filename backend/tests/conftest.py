"""Every test runs in local mode against a fresh temp folder; LLM calls are mocked per test."""

import os
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
GOLD = BACKEND / "skills" / "examples" / "gold_analysis.py"
SEED = BACKEND.parent / "data"


def _clear_caches():
    from app.agents import copilot, llm, skills
    from app.config import get_settings
    from app.models import db
    from app.retrieval import index
    from app.storage import objects

    for f in (get_settings, db.get_engine, db.get_sessionmaker, objects.get_store, llm.get_client,
              index.get_qdrant, copilot.get_agent, skills.load):
        f.cache_clear()


@pytest.fixture(autouse=True)
def local_env(tmp_path, monkeypatch):
    from app.config import Settings

    # Empty env vars outrank backend/.env, so a filled-in .env never reaches the tests
    cloud = ("AWS_", "DAYTONA_", "QDRANT_", "DATABASE_URL", "S3_", "MP_")
    for key in set(os.environ) | set(Settings.model_fields):
        if key.startswith(cloud):
            monkeypatch.setenv(key, "")
    monkeypatch.setenv("COREFINE_MODE", "local")
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "local"))
    monkeypatch.setenv("TOOLS_DIR", str(tmp_path / "tools"))  # never see codes installed on the dev machine
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LLM_SERVER_FALLBACKS", "false")
    _clear_caches()
    from app.models.db import init_db

    init_db()
    yield tmp_path
    from app.retrieval import index

    if index.get_qdrant.cache_info().currsize:
        index.get_qdrant().close()
    _clear_caches()


@pytest.fixture
def seeded(local_env):
    """Seed datasets into the local bucket (needs data/*/raw from scripts/fetch_data.py)."""
    if not any((SEED / "nist-srm-640f" / "raw").glob("*.cif")):
        pytest.skip("seed data missing; run scripts/fetch_data.py")
    from app.storage import datasets
    from app.storage.objects import get_store

    store = get_store()
    for folder in ("nist-srm-640f", "cod-9008565-si"):
        src = SEED / folder
        m = datasets.parse_manifest((src / "dataset.yaml").read_text(), folder)
        # two scans are enough for tests and keep staging fast
        for f in sorted((src / "raw").glob("*"))[:2]:
            store.put(f"datasets/{folder}/raw/{f.name}", f.read_bytes())
        datasets.write_manifest(m, store)
    return store


@pytest.fixture
def gold_code() -> str:
    return GOLD.read_text()


@pytest.fixture
def no_index(monkeypatch):
    from app.retrieval import index

    monkeypatch.setattr(index, "index_run", lambda run_id: 0)
    monkeypatch.setattr(index, "index_dataset", lambda *a, **k: None)
