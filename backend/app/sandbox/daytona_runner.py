"""Daytona runner: one sandbox per run, files staged in and out by the backend.

The sandbox never receives cloud credentials, and is created with network_block_all so generated
code cannot reach the internet (Daytona's free tier restricts egress anyway).
"""

import shlex
import time

from daytona import (
    CreateSandboxFromSnapshotParams,
    Daytona,
    DaytonaConfig,
    FileDownloadRequest,
    FileUpload,
)

from app.config import Settings
from app.models.contracts import StepResult
from app.sandbox.base import OutputLimitError

TIMEOUT_EXIT = 124  # coreutils `timeout`


class DaytonaSession:
    def __init__(self, client: Daytona, sandbox, settings: Settings):
        self.client, self.sb, self.settings = client, sandbox, settings
        self.work = f"{sandbox.get_user_home_dir()}/work"
        self._exec(f"mkdir -p {self.work}/inputs {self.work}/outputs {self.work}/code {self.work}/logs")

    def _exec(self, cmd: str, timeout: int = 60):
        return self.sb.process.exec(cmd, timeout=timeout)

    def stage_inputs(self, files: dict[str, bytes]) -> None:
        dirs = {f"{self.work}/inputs/{rel.rsplit('/', 1)[0]}" for rel in files if "/" in rel}
        if dirs:
            self._exec("mkdir -p " + " ".join(shlex.quote(d) for d in sorted(dirs)))
        self.sb.fs.upload_files(
            [FileUpload(source=data, destination=f"{self.work}/inputs/{rel}") for rel, data in files.items()]
        )

    def run(self, script: str, script_name: str, timeout_s: int) -> StepResult:
        w = self.work
        self._exec(f"rm -rf {w}/outputs && mkdir -p {w}/outputs")
        self.sb.fs.upload_file(script.encode(), f"{w}/code/{script_name}")
        cmd = (
            f"cd {w} && COREFINE_WORK={w} MPLBACKEND=Agg timeout {timeout_s} python -u code/{script_name} "
            f"> logs/stdout.txt 2> logs/stderr.txt; echo $?"
        )
        t0 = time.monotonic()
        resp = self._exec(f"bash -lc {shlex.quote(cmd)}", timeout=timeout_s + 30)
        exit_code = int((resp.result or "").strip().splitlines()[-1])
        logs = self.sb.fs.download_files([
            FileDownloadRequest(source=f"{w}/logs/stdout.txt"), FileDownloadRequest(source=f"{w}/logs/stderr.txt"),
        ])
        stdout, stderr = (self._text(r) for r in logs)
        timed_out = exit_code == TIMEOUT_EXIT
        if timed_out:
            stderr += f"\nstep exceeded the {timeout_s} s time limit"

        names = [f.name for f in self.sb.fs.list_files(f"{w}/outputs") if not f.is_dir]
        files, total = {}, 0
        if names:
            for name, r in zip(names, self.sb.fs.download_files(
                [FileDownloadRequest(source=f"{w}/outputs/{n}") for n in names]
            )):
                data = r.result if isinstance(r.result, bytes) else (r.result or "").encode()
                total += len(data)
                if total > self.settings.MAX_OUTPUT_BYTES:
                    raise OutputLimitError(f"outputs exceed the {self.settings.MAX_OUTPUT_BYTES} byte limit")
                files[name] = data
        return StepResult(exit_code=None if timed_out else exit_code, stdout=stdout, stderr=stderr,
                          timed_out=timed_out, files=files, duration_s=time.monotonic() - t0)

    @staticmethod
    def _text(r) -> str:
        if r.error:
            return ""
        return r.result.decode(errors="replace") if isinstance(r.result, bytes) else (r.result or "")

    def close(self) -> None:
        try:
            self.client.delete(self.sb)
        except Exception:
            pass  # auto-stop and ephemeral deletion clean up a sandbox we failed to delete


class DaytonaRunner:
    name = "daytona"

    def __init__(self, settings: Settings):
        self.settings = settings
        cfg = {"api_key": settings.DAYTONA_API_KEY}
        if settings.DAYTONA_API_URL:
            cfg["api_url"] = settings.DAYTONA_API_URL
        self.client = Daytona(DaytonaConfig(**cfg))

    def open(self, run_id: str) -> DaytonaSession:
        sb = self.client.create(CreateSandboxFromSnapshotParams(
            snapshot=self.settings.DAYTONA_SNAPSHOT,
            language="python",
            labels={"app": "corefine", "run": run_id},
            network_block_all=True,
            auto_stop_interval=15,
            ephemeral=True,
        ), timeout=120)
        return DaytonaSession(self.client, sb, self.settings)

    def ping(self) -> None:
        self.client.snapshot.get(self.settings.DAYTONA_SNAPSHOT)
