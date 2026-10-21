"""The one module that calls Claude. Every call is traced in Langfuse (when keys are set) and uses
model names from config. Agents get typed, schema-validated output via structured outputs."""

import base64
from contextlib import nullcontext
from functools import lru_cache
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


@lru_cache
def get_client() -> anthropic.Anthropic:
    s = get_settings()
    return anthropic.Anthropic(api_key=s.ANTHROPIC_API_KEY or None, max_retries=3)


@lru_cache
def get_langfuse():
    s = get_settings()
    if not s.langfuse_enabled:
        return None
    from langfuse import Langfuse

    return Langfuse(public_key=s.LANGFUSE_PUBLIC_KEY, secret_key=s.LANGFUSE_SECRET_KEY, host=s.LANGFUSE_HOST or None)


def trace_span(name: str, **kwargs):
    """A Langfuse span (or a no-op) to group a run's LLM calls into one trace."""
    lf = get_langfuse()
    return lf.start_as_current_observation(name=name, as_type="span", **kwargs) if lf else nullcontext()


def image_block(png: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.standard_b64encode(png).decode()}}


def parse(*, agent: str, system: str, content: list[dict] | str, output: type[T],
          model: str | None = None, effort: str = "high", max_tokens: int = 16000) -> T:
    """One structured call. Raises LLMError on refusal, truncation or a missing parsed output."""
    s = get_settings()
    model = model or s.MODEL_MAIN
    kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        output_format=output,
    )
    if s.LLM_SERVER_FALLBACKS:
        kwargs["extra_headers"] = {"anthropic-beta": FALLBACK_BETA}
        kwargs["extra_body"] = {"fallbacks": "default"}

    lf = get_langfuse()
    gen = (lf.start_as_current_observation(name=agent, as_type="generation", model=model,
                                           input={"system": system, "content": _loggable(content)})
           if lf else nullcontext())
    with gen as g:
        try:
            resp = get_client().messages.parse(**kwargs)
        except anthropic.APIStatusError as e:
            if g:
                g.update(level="ERROR", status_message=str(e))
            raise LLMError(f"{agent}: API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"{agent}: could not reach the Anthropic API") from e
        if g:
            g.update(output=resp.parsed_output.model_dump() if resp.parsed_output else None,
                     usage_details={"input": resp.usage.input_tokens, "output": resp.usage.output_tokens},
                     metadata={"stop_reason": resp.stop_reason, "request_id": resp._request_id})
    if resp.stop_reason == "refusal":
        cat = resp.stop_details.category if resp.stop_details else None
        raise LLMError(f"{agent}: model declined the request (category: {cat})")
    if resp.stop_reason == "max_tokens":
        raise LLMError(f"{agent}: output hit max_tokens={max_tokens} before finishing")
    if resp.parsed_output is None:
        raise LLMError(f"{agent}: no structured output returned")
    return resp.parsed_output


def _loggable(content):
    if isinstance(content, str):
        return content
    return [b if b.get("type") != "image" else {"type": "image", "omitted": True} for b in content]


def ping() -> None:
    get_client().models.retrieve(get_settings().MODEL_MAIN)
