"""Live view of a run: what is happening now ("activity") and the text a model is writing ("draft"), as SSE events.

Nothing here is recorded as a result; the experiment log and files stay the record. Drafts are sent as small
deltas a few times a second so a page that opens mid-run replays the text so far from the event log.
"""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from app.orchestration.events import bus

FLUSH_S = 0.25


class Live:
    def __init__(self, run_id: str):
        self.run_id = run_id

    def activity(self, agent: str, text: str, step: int | None = None, attempt: int | None = None) -> None:
        bus.publish(self.run_id, "activity", agent=agent, text=text, step=step, attempt=attempt)

    @contextmanager
    def draft(self, agent: str, step: int | None = None, attempt: int | None = None) -> Iterator[Callable[[str], None]]:
        """Yields a callback that collects streamed text and publishes it in batches; flushes on exit."""
        lock, buf, last = threading.Lock(), [], [time.monotonic()]

        def flush() -> None:
            with lock:
                if not buf:
                    return
                delta = "".join(buf)
                buf.clear()
                last[0] = time.monotonic()
            bus.publish(self.run_id, "draft", agent=agent, step=step, attempt=attempt, delta=delta)

        def on_text(t: str) -> None:
            with lock:
                buf.append(t)
                due = time.monotonic() - last[0] >= FLUSH_S
            if due:
                flush()

        try:
            yield on_text
        finally:
            flush()
            bus.publish(self.run_id, "draft_done", agent=agent, step=step, attempt=attempt)
