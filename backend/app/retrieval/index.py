"""Qdrant: filtered search over run reports, dataset docs and reference notes.

Text goes in as `models.Document`; qdrant-client embeds it either on the Qdrant Cloud cluster
(EMBED_PROVIDER=qdrant_cloud, cloud inference) or locally with FastEmbed. Numbers are never read
from here — the chat reads numbers from the metrics table.
"""

import re
import uuid
from functools import lru_cache

from qdrant_client import QdrantClient, models
from sqlalchemy import select

from app.config import get_settings
from app.models.db import RunRow, get_sessionmaker
from app.storage.objects import get_store

COLLECTIONS = {
    "run_reports": ["run_id", "parent_run_id", "dataset_ids", "technique", "material", "status"],
    "dataset_docs": ["dataset_id", "role", "technique", "material"],
    "reference_notes": ["source", "technique", "material"],
}


@lru_cache
def get_qdrant() -> QdrantClient:
    s = get_settings()
    if s.QDRANT_URL:
        return QdrantClient(url=s.QDRANT_URL, api_key=s.QDRANT_API_KEY or None,
                            cloud_inference=s.EMBED_PROVIDER == "qdrant_cloud")
    return QdrantClient(path=str(s.LOCAL_DATA_DIR / "qdrant"))


def ensure_collections() -> None:
    """Idempotent: creates missing collections and payload indexes."""
    s, q = get_settings(), get_qdrant()
    for name, fields in COLLECTIONS.items():
        if not q.collection_exists(name):
            q.create_collection(name, vectors_config=models.VectorParams(size=s.EMBED_DIM, distance=models.Distance.COSINE))
        for f in fields if s.QDRANT_URL else ():  # local Qdrant ignores payload indexes
            try:
                q.create_payload_index(name, f, field_schema=models.PayloadSchemaType.KEYWORD)
            except Exception:
                pass  # already exists, or local mode (no payload indexes needed)


def _doc(text: str) -> models.Document:
    return models.Document(text=text, model=get_settings().EMBED_MODEL)


def _pid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "/".join(parts)))


def split_sections(markdown: str) -> list[tuple[str, str]]:
    chunks = re.split(r"(?m)^(?=#{1,2} )", markdown)
    out = []
    for c in chunks:
        c = c.strip()
        if c:
            out.append((c.splitlines()[0].lstrip("# ").strip(), c))
    return out


def index_run(run_id: str) -> int:
    ensure_collections()
    store = get_store()
    with get_sessionmaker()() as db:
        run = db.get(RunRow, run_id)
    payload_base = {
        "run_id": run.id, "parent_run_id": run.parent_run_id or "", "dataset_ids": run.dataset_ids,
        "technique": "xrd_powder", "material": "Si", "status": run.status,
        "created_at": run.started_at.isoformat() if run.started_at else "",
    }
    texts = []
    if run.plan:
        texts.append(("plan", f"Plan: {run.plan.get('title')}\n{run.plan.get('summary')}"))
    if store.exists(f"runs/{run_id}/report.md"):
        texts += split_sections(store.get(f"runs/{run_id}/report.md").decode())
    if run.error:
        texts.append(("error", f"Run failed: {run.error[:2000]}"))
    points = [models.PointStruct(id=_pid(run_id, str(i)), vector=_doc(t),
                                 payload={**payload_base, "section": title, "text": t})
              for i, (title, t) in enumerate(texts)]
    if points:
        get_qdrant().upsert("run_reports", points=points)
    return len(points)


def index_dataset(manifest: dict, readme: str | None) -> None:
    ensure_collections()
    text = f"Dataset {manifest['id']} ({manifest['role']}, {manifest['technique']}, {manifest['material']})\n"
    text += (readme or "") + "\n" + str({k: v for k, v in manifest.items() if k != "reference_values"})
    get_qdrant().upsert("dataset_docs", points=[models.PointStruct(
        id=_pid("dataset", manifest["id"]), vector=_doc(text),
        payload={"dataset_id": manifest["id"], "role": manifest["role"], "technique": manifest["technique"],
                 "material": manifest["material"], "text": text})])


def index_note(source: str, technique: str, material: str, text: str) -> None:
    ensure_collections()
    get_qdrant().upsert("reference_notes", points=[models.PointStruct(
        id=_pid("note", source), vector=_doc(text),
        payload={"source": source, "technique": technique, "material": material, "text": text})])


def search(collection: str, query: str, filters: dict | None = None, limit: int = 5) -> list[dict]:
    if collection not in COLLECTIONS:
        raise ValueError(f"unknown collection {collection!r}")
    must = [models.FieldCondition(key=k, match=models.MatchValue(value=v)) for k, v in (filters or {}).items()]
    res = get_qdrant().query_points(collection, query=_doc(query),
                                    query_filter=models.Filter(must=must) if must else None, limit=limit)
    return [{"score": p.score, **(p.payload or {})} for p in res.points]


def reindex_all_runs() -> int:
    with get_sessionmaker()() as db:
        ids = list(db.scalars(select(RunRow.id)))
    return sum(index_run(i) for i in ids)
