"""In-process event log per run, read by the SSE endpoint. Thread-safe: runs execute in worker threads."""

import threading
import time
from collections import defaultdict


class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._events: dict[str, list[dict]] = defaultdict(list)

    def publish(self, run_id: str, type_: str, **data) -> None:
        with self._lock:
            self._events[run_id].append({"type": type_, "ts": time.time(), "run_id": run_id, **data})

    def since(self, run_id: str, index: int) -> list[dict]:
        with self._lock:
            return list(self._events.get(run_id, [])[index:])

    def finished(self, run_id: str) -> bool:
        with self._lock:
            evs = self._events.get(run_id, [])
            return bool(evs) and evs[-1]["type"] == "run_finished"


bus = EventBus()
