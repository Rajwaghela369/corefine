"""The one module that calls Claude. Model names come from config; agents get typed,
schema-validated output via structured outputs."""

import base64
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

    try:
        # Streamed so large max_tokens (the Coder's 32k) passes the SDK's 10-minute non-streaming guard
        with get_client().messages.stream(**kwargs) as stream:
            resp = stream.get_final_message()
    except anthropic.APIStatusError as e:
        raise LLMError(f"{agent}: API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError(f"{agent}: could not reach the Anthropic API") from e
    if resp.stop_reason == "refusal":
        cat = resp.stop_details.category if resp.stop_details else None
        raise LLMError(f"{agent}: model declined the request (category: {cat})")
    if resp.stop_reason == "max_tokens":
        raise LLMError(f"{agent}: output hit max_tokens={max_tokens} before finishing")
    if resp.parsed_output is None:
        raise LLMError(f"{agent}: no structured output returned")
    return resp.parsed_output


def ping() -> None:
    get_client().models.retrieve(get_settings().MODEL_MAIN)
