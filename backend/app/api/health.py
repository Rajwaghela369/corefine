"""/health checks the five services. In local mode it says which local stand-in is in use."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings

router = APIRouter(tags=["health"])
CHECK_TIMEOUT_S = 15


def _neon():
    from app.models.db import get_engine

    with get_engine().connect() as c:
        c.execute(text("select 1"))
    return "postgres" if get_settings().DATABASE_URL else "local sqlite"


def _s3():
    from app.storage.objects import S3Store, get_store

    get_store().ping()
    return "s3" if isinstance(get_store(), S3Store) else "local folder"


def _qdrant():
    from app.retrieval.index import get_qdrant

    get_qdrant().get_collections()
    return "qdrant cloud" if get_settings().QDRANT_URL else "local qdrant"


def _daytona():
    from app.sandbox.base import get_runner

    r = get_runner()
    r.ping()
    return r.name


def _anthropic():
    from app.agents.llm import ping

    if not get_settings().ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    ping()
    return get_settings().MODEL_MAIN


CHECKS = {"neon": _neon, "s3": _s3, "qdrant": _qdrant, "daytona": _daytona, "anthropic": _anthropic}


@router.get("/ping")
def ping():
    return {"ok": True, "mode": get_settings().COREFINE_MODE}


@router.get("/health")
def health():
    out = {}
    with ThreadPoolExecutor(len(CHECKS)) as pool:
        futures = {name: pool.submit(fn) for name, fn in CHECKS.items()}
        for name, fut in futures.items():
            try:
                out[name] = {"ok": True, "detail": fut.result(timeout=CHECK_TIMEOUT_S)}
            except TimeoutError:
                out[name] = {"ok": False, "detail": f"no answer within {CHECK_TIMEOUT_S} s"}
            except Exception as e:
                out[name] = {"ok": False, "detail": str(e)[:300]}
    return {"mode": get_settings().COREFINE_MODE, "all_ok": all(v["ok"] for v in out.values()), "services": out}
