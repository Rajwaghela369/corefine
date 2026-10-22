from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.sandbox.daytona_runner import DaytonaRunner


def runner_with(state: str, error_reason=None) -> DaytonaRunner:
    r = DaytonaRunner.__new__(DaytonaRunner)
    r.settings = get_settings()
    snap = SimpleNamespace(state=SimpleNamespace(value=state), error_reason=error_reason)
    r.client = SimpleNamespace(snapshot=SimpleNamespace(get=lambda name: snap))
    return r


def test_ping_accepts_active_snapshot():
    runner_with("active").ping()


@pytest.mark.parametrize("state", ["building", "pending", "error"])
def test_ping_rejects_snapshot_that_is_not_active(state):
    with pytest.raises(RuntimeError, match=f"is {state}, not ready"):
        runner_with(state, "build failed" if state == "error" else None).ping()
