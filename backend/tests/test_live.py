from types import SimpleNamespace

from app.agents.llm import _TextStream
from app.orchestration import live as live_mod
from app.orchestration.events import bus


def test_draft_batches_deltas_and_marks_the_end(monkeypatch):
    clock = iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
    monkeypatch.setattr(live_mod.time, "monotonic", lambda: next(clock))
    lv = live_mod.Live("run-live-1")
    with lv.draft("coder", step=2, attempt=1) as on_text:
        for piece in ['{"co', 'de": "import', ' numpy', '\\n"}']:
            on_text(piece)
    evs = [e for e in bus.since("run-live-1", 0)]
    drafts = [e for e in evs if e["type"] == "draft"]
    assert "".join(d["delta"] for d in drafts) == '{"code": "import numpy\\n"}'
    assert 1 <= len(drafts) < 4                                  # batched, not one event per token
    assert evs[-1]["type"] == "draft_done" and evs[-1]["step"] == 2 and evs[-1]["agent"] == "coder"


def test_activity_event_carries_step_and_text():
    live_mod.Live("run-live-2").activity("sandbox", "Running step 1 in the sandbox", step=1, attempt=1)
    ev = bus.since("run-live-2", 0)[0]
    assert ev["type"] == "activity" and ev["text"].startswith("Running step 1") and ev["ts"] > 0


def test_text_stream_forwards_only_text_blocks():
    got = []
    h = _TextStream(got.append)
    chunk = SimpleNamespace(message=SimpleNamespace(content=[{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": '{"a"'}]))
    h.on_llm_new_token("", chunk=chunk)
    h.on_llm_new_token(": 1}", chunk=None)
    assert got == ['{"a"', ": 1}"]
