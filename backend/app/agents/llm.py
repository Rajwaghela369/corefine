"""The one module that builds Claude models, as LangChain `ChatAnthropic` chat models. Model names come from config;
agents get typed, schema-validated output through Claude's native structured outputs (`method="json_schema"`)."""

import base64
from functools import lru_cache
from typing import TypeVar

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


@lru_cache
def chat_model(model: str | None = None, *, max_tokens: int = 16000, effort: str | None = "high") -> ChatAnthropic:
    """A configured Claude chat model, shared by the run agents and the co-pilot.

    Streaming keeps long generations (the Coder's 32k tokens) under the SDK's 10-minute non-streaming guard;
    server-side fallbacks retry declined requests on Anthropic's recommended model.
    """
    s = get_settings()
    kw: dict = dict(model=model or s.MODEL_MAIN, max_tokens=max_tokens, api_key=s.ANTHROPIC_API_KEY or None,
                    max_retries=3, streaming=True, thinking={"type": "adaptive"})
    if effort:
        kw["output_config"] = {"effort": effort}
    if s.LLM_SERVER_FALLBACKS:
        kw["betas"] = [FALLBACK_BETA]
        kw["model_kwargs"] = {"fallbacks": "default"}
    return ChatAnthropic(**kw)


def image_block(png: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.standard_b64encode(png).decode()}}


def parse(*, agent: str, system: str, content: list[dict] | str, output: type[T],
          model: str | None = None, effort: str = "high", max_tokens: int = 16000) -> T:
    """One structured call. Raises LLMError on refusal, truncation or a missing parsed output."""
    runnable = chat_model(model, max_tokens=max_tokens, effort=effort).with_structured_output(
        output, method="json_schema", include_raw=True)
    try:
        res = runnable.invoke([SystemMessage(system), HumanMessage(content)], config={"run_name": agent, "tags": [agent]})
    except anthropic.APIStatusError as e:
        raise LLMError(f"{agent}: API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError(f"{agent}: could not reach the Anthropic API") from e
    meta = res["raw"].response_metadata
    stop = meta.get("stop_reason")
    if stop == "refusal":
        cat = (meta.get("stop_details") or {}).get("category")
        raise LLMError(f"{agent}: model declined the request (category: {cat})")
    if stop == "max_tokens":
        raise LLMError(f"{agent}: output hit max_tokens={max_tokens} before finishing")
    if res["parsed"] is None:
        raise LLMError(f"{agent}: no structured output returned" + (f" ({res['parsing_error']})" if res["parsing_error"] else ""))
    return res["parsed"]


def ping() -> None:
    """Health check without spending tokens: the model is known to the API. LangChain has no model-lookup call."""
    s = get_settings()
    anthropic.Anthropic(api_key=s.ANTHROPIC_API_KEY or None, max_retries=1).models.retrieve(s.MODEL_MAIN)
