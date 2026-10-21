"""Local fallback runner: a subprocess per step with the same limits and file layout as Daytona.

This machine has no Docker and unprivileged user namespaces are blocked, so this runner cannot give
real network isolation. It installs a sitecustomize hook that refuses outbound socket connections,
which stops accidental network use by generated code but is not a security boundary. Use it for
development and as the venue-Wi-Fi fallback, not for untrusted code.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

from app.config import Settings
from app.models.contracts import StepResult
from app.sandbox.base import OutputLimitError

NO_NETWORK_HOOK = '''
import socket
def _blocked(*args, **kwargs):
    raise PermissionError("network access is disabled in the CoRefine sandbox")
socket.socket.connect = _blocked
socket.create_connection = _blocked
'''


class LocalSession:
    def __init__(self, root: Path, settings: Settings):
        self.root, self.settings = root, settings
        for d in ("inputs", "outputs", "code", "logs", "_hook"):
            (root / d).mkdir(parents=True, exist_ok=True)
        (root / "_hook" / "sitecustomize.py").write_text(NO_NETWORK_HOOK)

    def stage_inputs(self, files: dict[str, bytes]) -> None:
        for rel, data in files.items():
            p = (self.root / "inputs" / rel).resolve()
            if not p.is_relative_to((self.root / "inputs").resolve()):
                raise ValueError(f"input path escapes inputs/: {rel}")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def run(self, script: str, script_name: str, timeout_s: int) -> StepResult:
        out = self.root / "outputs"
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir()
        code = self.root / "code" / script_name
        code.write_text(script)
        env = {
            "COREFINE_WORK": str(self.root),
            "PYTHONPATH": str(self.root / "_hook"),
            "MPLBACKEND": "Agg",
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.root),
        }
        t0 = time.monotonic()
        try:
            p = subprocess.run(
                [sys.executable, "-u", str(code)],
                cwd=self.root, env=env, capture_output=True, text=True, timeout=timeout_s,
            )
            exit_code, stdout, stderr, timed_out = p.returncode, p.stdout, p.stderr, False
        except subprocess.TimeoutExpired as e:
            exit_code, timed_out = None, True
            stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = (e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")) + (
                f"\nstep exceeded the {timeout_s} s time limit"
            )
        files, total = {}, 0
        for f in sorted(out.rglob("*")):
            if f.is_file():
                data = f.read_bytes()
                total += len(data)
                if total > self.settings.MAX_OUTPUT_BYTES:
                    raise OutputLimitError(f"outputs exceed the {self.settings.MAX_OUTPUT_BYTES} byte limit")
                files[str(f.relative_to(out))] = data
        return StepResult(exit_code=exit_code, stdout=stdout, stderr=stderr, timed_out=timed_out,
                          files=files, duration_s=time.monotonic() - t0)

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class LocalRunner:
    name = "local"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base = settings.LOCAL_DATA_DIR / "sandboxes"

    def open(self, run_id: str) -> LocalSession:
        root = self.base / run_id
        shutil.rmtree(root, ignore_errors=True)
        return LocalSession(root, self.settings)

    def ping(self) -> None:
        subprocess.run([sys.executable, "-c", "import numpy, scipy, lmfit, gemmi, pymatgen"], check=True,
                       capture_output=True, timeout=60)
