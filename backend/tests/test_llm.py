import functools

import anthropic
import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from app.agents import llm


class Out(BaseModel):
    text: str


def fake_model(result=None, error=None, seen=None):
    """Stand-in for ChatAnthropic: records what was sent and returns a LangChain include_raw result."""
    class Runnable:
        def invoke(self, messages, config):
            if seen is not None:
                seen.update(messages=messages, config=config)
            if error:
                raise error
            return result

    class Model:
        def with_structured_output(self, schema, method, include_raw):
            assert schema is Out and method == "json_schema" and include_raw
            return Runnable()

    return functools.cache(lambda *a, **k: Model())


def raw(stop="end_turn", **meta):
    return AIMessage("", response_metadata={"stop_reason": stop, **meta})


def test_chat_model_carries_effort_streaming_and_fallbacks(monkeypatch):
    monkeypatch.setenv("LLM_SERVER_FALLBACKS", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    m = llm.chat_model("claude-haiku-5-5", max_tokens=2000, effort="low")
    assert m.model == "claude-haiku-5-5" and m.max_tokens == 2000 and m.streaming
    assert m.thinking == {"type": "adaptive"} and m.output_config == {"effort": "low"}
    assert m.betas == [llm.FALLBACK_BETA] and m.model_kwargs == {"fallbacks": "default"}


def test_parse_returns_the_typed_output_and_names_the_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm, "chat_model", fake_model({"raw": raw(), "parsed": Out(text="ok"), "parsing_error": None}, seen=seen))
    out = llm.parse(agent="planner", system="sys", content="hello", output=Out)
    assert out == Out(text="ok")
    assert seen["config"]["run_name"] == "planner"
    assert seen["messages"][0].content == "sys" and seen["messages"][1].content == "hello"


@pytest.mark.parametrize("result, message", [
    ({"raw": raw("refusal", stop_details={"category": "cyber"}), "parsed": None, "parsing_error": None}, "declined the request (category: cyber)"),
    ({"raw": raw("max_tokens"), "parsed": None, "parsing_error": None}, "hit max_tokens=16000"),
    ({"raw": raw(), "parsed": None, "parsing_error": ValueError("bad json")}, "no structured output returned (bad json)"),
])
def test_parse_turns_bad_endings_into_llm_errors(monkeypatch, result, message):
    monkeypatch.setattr(llm, "chat_model", fake_model(result))
    with pytest.raises(llm.LLMError, match=message.replace("(", r"\(").replace(")", r"\)")):
        llm.parse(agent="coder", system="s", content="c", output=Out)


def test_parse_wraps_api_errors(monkeypatch):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIStatusError("overloaded", response=httpx.Response(529, request=req), body=None)
    monkeypatch.setattr(llm, "chat_model", fake_model(error=err))
    with pytest.raises(llm.LLMError, match="analyst: API error 529"):
        llm.parse(agent="analyst", system="s", content="c", output=Out)
