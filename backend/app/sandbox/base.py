"""One interface, two runners. A run opens one sandbox session; each step runs one script in it.

Layout inside the sandbox ($COREFINE_WORK, default /work):
  inputs/<dataset-id>/...       staged once per run (sanitized)
  inputs/previous/<file>        outputs of earlier steps the current step declared it reads
  outputs/                      emptied before each step; collected after it
  code/<script>                 the step's script
"""

from typing import Protocol

from app.models.contracts import StepResult


class SandboxSession(Protocol):
    def stage_inputs(self, files: dict[str, bytes]) -> None:
        """Write {relative path under inputs/: bytes}."""

    def run(self, script: str, script_name: str, timeout_s: int) -> StepResult:
        """Empty outputs/, run the script with python, return stdout/stderr/exit code and output files."""

    def close(self) -> None: ...


class SandboxRunner(Protocol):
    name: str

    def open(self, run_id: str) -> SandboxSession: ...

    def ping(self) -> None: ...


class OutputLimitError(RuntimeError):
    pass


def get_runner() -> SandboxRunner:
    from app.config import get_settings

    s = get_settings()
    if s.DAYTONA_API_KEY:
        from app.sandbox.daytona_runner import DaytonaRunner

        return DaytonaRunner(s)
    from app.sandbox.local_runner import LocalRunner

    return LocalRunner(s)
