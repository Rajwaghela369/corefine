import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, datasets, health, runs
from app.config import get_settings
from app.models.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # fails fast, naming any missing key, in cloud mode
    init_db()
    yield
    from app.agents.llm import get_langfuse

    if lf := get_langfuse():
        lf.flush()


app = FastAPI(title="CoRefine", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[get_settings().FRONTEND_ORIGIN], allow_methods=["*"],
                   allow_headers=["*"])
for r in (health.router, datasets.router, runs.router, chat.router):
    app.include_router(r)
