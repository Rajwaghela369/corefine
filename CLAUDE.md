# CoRefine — notes for Claude Code sessions

Read this file and `docs/SPEC.md`, then `docs/SPEC_CORRECTIONS.md` (verified deviations from the spec).

## Layout
- `backend/app/` — `api/` (FastAPI routers), `agents/` (llm client, planner, coder, analyst, copilot,
  code-only checks), `orchestration/` (LangGraph run graph, recorder, SSE event bus), `sandbox/`
  (local + Daytona runners), `storage/` (S3/local store, datasets, CIF sanitizer), `retrieval/` (Qdrant),
  `models/` (Pydantic contracts, SQLAlchemy tables).
- `backend/skills/` — skill files loaded by name; `examples/gold_analysis.py` is the human-checked
  reference and its outputs are in `examples/gold_outputs/`.
- `backend/tests/` — pytest; LLM calls mocked, everything else real (local mode).
- `frontend/src/` — React + Vite + TS: `panels/`, `tabs/`, `api/`.
- `data/` — seed dataset manifests and READMEs (raw files come from `backend/scripts/fetch_data.py`).

## Conventions
- Use the managed services through their official SDKs; never self-host or reimplement them. Local
  mode exists only for development, tests and the venue fallback.
- Secrets live only in `backend/.env`. The frontend and the sandbox never receive keys.
- All Claude calls go through `app/agents/llm.py` (Langfuse tracing, model names from config,
  structured outputs). The chat co-pilot uses `langchain-anthropic` inside Deep Agents.
- No number may appear in a report or chat answer unless it comes from `metrics.json`, a manifest
  or a database row. The claim checker (`app/agents/checks.py`) is code and cannot be overridden.
- The Coder never sees `reference_values` or the certified value. Measured CIFs are sanitized before
  staging.
- Pydantic models for every contract. Tests with pytest. Mock the LLM and sandbox in unit tests; mark
  tests that hit real services with `@pytest.mark.integration`.
- Backend Python 3.14 with uv (`backend/pyproject.toml`); sandbox Python 3.13 (Daytona's maximum).
- Verify physics claims against data or the certificate; never invent wavelengths, reference values
  or file tags.

## Commands
    cd backend && uv sync --extra embed && uv run pytest
    cd backend && uv run python scripts/fetch_data.py && uv run python scripts/setup.py
    cd backend && uv run uvicorn app.main:app --reload --port 8000
    cd frontend && npm install && npm run dev        # http://localhost:5173
