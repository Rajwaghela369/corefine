"""The one module that builds Claude models, as LangChain `ChatAnthropic` chat models. Model names come from config;
agents get typed, schema-validated output through Claude's native structured outputs (`method="json_schema"`)."""

import base64
from collections.abc import Callable
from functools import lru_cache
from typing import Any, TypeVar

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
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


class _TextStream(BaseCallbackHandler):
    """Forwards the model's output text to a callback as it is generated (the JSON of the structured answer)."""

    def __init__(self, on_text: Callable[[str], None]):
        self.on_text = on_text

    def on_llm_new_token(self, token: str, *, chunk: Any = None, **kwargs: Any) -> None:
        content = getattr(getattr(chunk, "message", None), "content", None)
        if isinstance(content, list):
            token = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        if token:
            self.on_text(token)


def parse(*, agent: str, system: str, content: list[dict] | str, output: type[T],
          model: str | None = None, effort: str = "high", max_tokens: int = 16000,
          on_text: Callable[[str], None] | None = None) -> T:
    """One structured call. Raises LLMError on refusal, truncation or a missing parsed output.
    on_text, when given, receives the output text as it streams (for the live view)."""
    runnable = chat_model(model, max_tokens=max_tokens, effort=effort).with_structured_output(
        output, method="json_schema", include_raw=True)
    config: dict = {"run_name": agent, "tags": [agent]}
    if on_text:
        config["callbacks"] = [_TextStream(on_text)]
    try:
        res = runnable.invoke([SystemMessage(system), HumanMessage(content)], config=config)
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
