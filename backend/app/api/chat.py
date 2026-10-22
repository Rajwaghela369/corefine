from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.concurrency import iterate_in_threadpool

from app.agents import copilot
from app.models.db import MessageRow, get_sessionmaker

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=4, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    dataset_ids: list[str] = Field(default_factory=list)
    run_id: str | None = Field(default=None, max_length=64)


@router.post("", response_class=EventSourceResponse)
async def chat(req: ChatRequest):
    try:
        async for ev in iterate_in_threadpool(copilot.chat(req.session_id, req.message, req.dataset_ids, req.run_id)):
            yield ServerSentEvent(data=ev, event=ev["type"])
    except Exception as e:  # surface agent/API errors to the chat instead of a dropped stream
        yield ServerSentEvent(data={"type": "error", "message": str(e)}, event="error")


@router.get("/{session_id}")
def history(session_id: str):
    with get_sessionmaker()() as db:
        rows = db.scalars(select(MessageRow).where(MessageRow.session_id == session_id).order_by(MessageRow.id))
        return [{"role": r.role, "content": r.content, "run_id": r.run_id, "created_at": r.created_at} for r in rows]
