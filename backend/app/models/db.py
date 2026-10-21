"""Neon Postgres tables (SQLite in local mode). JSONB on Postgres, JSON elsewhere."""

from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings

Json = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class DatasetRow(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(32))
    technique: Mapped[str] = mapped_column(String(64))
    material: Mapped[str] = mapped_column(String(64))
    format: Mapped[str] = mapped_column(String(16))
    prefix: Mapped[str] = mapped_column(String(256))
    manifest: Mapped[dict] = mapped_column(Json)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prompt: Mapped[str] = mapped_column(Text)
    dataset_ids: Mapped[list] = mapped_column(Json)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    plan: Mapped[dict | None] = mapped_column(Json, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification: Mapped[str | None] = mapped_column(String(48), nullable=True)
    claim_check: Mapped[dict | None] = mapped_column(Json, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)


class StepRow(Base):
    __tablename__ = "steps"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    code_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    stdout_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    step_idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))  # plot, csv, json, report, code, log, text
    key: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64))


class MetricRow(Base):
    __tablename__ = "metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # non-numeric metric values
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uncertainty: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_key: Mapped[str] = mapped_column(String(512))


class MessageRow(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


@lru_cache
def get_engine():
    url = get_settings().database_url
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


@lru_cache
def get_sessionmaker() -> sessionmaker:
    return sessionmaker(get_engine(), expire_on_commit=False)


def init_db() -> None:
    """Create all tables if absent. Idempotent: safe to run on every start."""
    Base.metadata.create_all(get_engine())
