"""Run generated inputs and collect parsed results. Where things run is per-user configuration, not code.

compute.yaml (see compute.example.yaml) lists *targets*. Each target says which codes it can run and how:

  kind: local   run the program in the set's code folder on this server, with a timeout and core limit
  kind: slurm   copy the folder to a cluster over SSH (your ~/.ssh config and keys; no passwords stored),
                render your own job-script template, sbatch it, poll sacct, copy results back

The run state of each code lives in <set>/runs/<code>.json, so the set folder is the record. Results
come only from the code's own output files, parsed by the code adapter.
"""

import json
import os
import shlex
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app.config import get_settings
from app.dft.codes import REGISTRY, CodeAdapter

TERMINAL = {"completed", "failed", "cancelled"}
SLURM_DONE = {"COMPLETED"}
SLURM_FAILED = {"FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED", "BOOT_FAIL", "DEADLINE"}
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dftrun")
_lock = threading.Lock()


class ComputeConfigError(ValueError):
    pass


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --- configuration -----------------------------------------------------------

def load_targets() -> dict[str, dict]:
    path = get_settings().COMPUTE_CONFIG
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    targets = data.get("targets") or {}
    for name, t in targets.items():
        if t.get("kind") not in ("local", "slurm"):
            raise ComputeConfigError(f"target {name}: kind must be local or slurm")
        if t["kind"] == "slurm" and not t.get("host"):
            raise ComputeConfigError(f"target {name}: slurm targets need host (an ssh host or alias)")
    return targets


def describe_targets() -> list[dict]:
    out = []
    for name, t in load_targets().items():
        out.append({"name": name, "kind": t["kind"], "host": t.get("host"), "codes": sorted((t.get("codes") or {}).keys()),
                    "confirm": t["kind"] != "local"})
    return out


def _expand(value: str) -> str:
    s = get_settings()
    return value.format(QUESTAAL_BIN=s.QUESTAAL_BIN or "", EXCITING_ROOT=s.EXCITING_ROOT or "")


# --- run state ---------------------------------------------------------------

def state_path(set_dir: Path, code: str) -> Path:
    # kept outside <set>/<code>/ so copying a run folder to or from a cluster never overwrites it
    d = set_dir / "runs"
    d.mkdir(exist_ok=True)
    return d / f"{code}.json"


def read_state(set_dir: Path, code: str) -> dict | None:
    p = state_path(set_dir, code)
    return json.loads(p.read_text()) if p.is_file() else None


def write_state(set_dir: Path, code: str, **update) -> dict:
    with _lock:
        st = read_state(set_dir, code) or {}
        st.update(update, code=code, updated=now())
        state_path(set_dir, code).write_text(json.dumps(st, indent=2, default=str))
        return st


def all_states(set_dir: Path) -> dict[str, dict]:
    return {c: st for c in REGISTRY if (st := read_state(set_dir, c))}


def attach_results(set_dir: Path, code: str, adapter: CodeAdapter) -> dict | None:
    res = adapter.parse_results(set_dir / code)
    if res is None:
        return None
    write_state(set_dir, code, results=asdict(res))
    return asdict(res)


# --- starting runs -------------------------------------------------------------

def start(set_dir: Path, code: str, target_name: str, wait: bool = False) -> dict:
    adapter = REGISTRY.get(code)
    if adapter is None:
        raise ComputeConfigError(f"unknown code {code!r}")
    if not (set_dir / code).is_dir():
        raise ComputeConfigError(f"this input set has no {code} inputs")
    targets = load_targets()
    target = targets.get(target_name)
    if target is None:
        raise ComputeConfigError(f"unknown compute target {target_name!r}; configured: {sorted(targets)}")
    code_cfg = (target.get("codes") or {}).get(code)
    if code_cfg is None:
        raise ComputeConfigError(f"target {target_name} has no entry for {code}")
    st = read_state(set_dir, code)
    if st and st.get("status") not in TERMINAL | {None}:
        raise ComputeConfigError(f"{code} is already {st['status']} on {st.get('target')}")
    write_state(set_dir, code, target=target_name, kind=target["kind"], status="queued", started=now(),
                finished=None, message="", results=None, attempts=0, remote_job_id=None)
    runner = _run_local if target["kind"] == "local" else _run_slurm
    if wait:
        runner(set_dir, code, adapter, target, code_cfg)
    else:
        _pool.submit(runner, set_dir, code, adapter, target, code_cfg)
    return read_state(set_dir, code)


def _finish(set_dir: Path, code: str, adapter: CodeAdapter, ok_exit: bool, message: str) -> None:
    res = adapter.parse_results(set_dir / code)
    status = "completed" if ok_exit and res is not None else "failed"
    if res is not None and res.converged is False and status == "completed":
        message = (message + "; " if message else "") + "finished but SCF not converged"
    write_state(set_dir, code, status=status, finished=now(), message=message, results=asdict(res) if res else None)


# --- local ---------------------------------------------------------------------

def _run_local(set_dir: Path, code: str, adapter: CodeAdapter, target: dict, code_cfg: dict) -> None:
    rundir = set_dir / code
    try:
        spec = adapter.run_args(rundir)
        exe = _expand(code_cfg.get("executable") or spec["program"])
        launcher = shlex.split(_expand(code_cfg.get("launcher", "")))
        threads = str(code_cfg.get("threads", target.get("threads", 1)))
        env = {**os.environ, "OMP_NUM_THREADS": threads, **adapter.local_env(get_settings()),
               **{k: _expand(str(v)) for k, v in (code_cfg.get("env") or {}).items()}}
        timeout = int(code_cfg.get("timeout_s", target.get("timeout_s", 3600)))
        restarts = int(code_cfg.get("max_restarts", 3)) if adapter.restartable else 0
        for attempt in range(1, restarts + 2):
            note = f" (restart {attempt - 1} from saved density)" if attempt > 1 else ""
            write_state(set_dir, code, status="running", attempts=attempt, message=f"running {Path(exe).name} locally{note}")
            with open(rundir / spec["stdout"], "w") as out:
                p = subprocess.run([*launcher, exe, *spec["args"]], cwd=rundir, env=env, stdout=out, stderr=subprocess.STDOUT,
                                   timeout=timeout)
            res = adapter.parse_results(rundir)
            if p.returncode != 0 or res is None or res.converged is not False:
                break
        _finish(set_dir, code, adapter, p.returncode == 0, f"exit code {p.returncode}" if p.returncode else "")
    except subprocess.TimeoutExpired:
        write_state(set_dir, code, status="failed", finished=now(), message="timed out")
    except Exception as e:  # noqa: BLE001 — a run must end in a recorded state
        write_state(set_dir, code, status="failed", finished=now(), message=str(e)[:2000])


# --- slurm over ssh --------------------------------------------------------------

def _ssh(target: dict, command: str, timeout: int = 120) -> subprocess.CompletedProcess:
    base = shlex.split(target.get("ssh_command", "ssh -o BatchMode=yes -o ConnectTimeout=20"))
    return subprocess.run([*base, target["host"], command], capture_output=True, text=True, timeout=timeout)


def _copy(target: dict, src: str, dst: str, timeout: int = 600) -> subprocess.CompletedProcess:
    base = shlex.split(target.get("copy_command", "rsync -az"))
    return subprocess.run([*base, src, dst], capture_output=True, text=True, timeout=timeout)


def render_script(code_cfg: dict, job_name: str, spec: dict) -> str:
    template = code_cfg.get("script")
    if not template:
        raise ComputeConfigError("slurm code entries need a script template")
    command = " ".join([shlex.quote(_expand(code_cfg.get("executable") or spec["program"])), *map(shlex.quote, spec["args"])])
    return template.format(job_name=job_name, command=command, stdout=spec["stdout"],
                           executable=_expand(code_cfg.get("executable") or spec["program"]))


def _run_slurm(set_dir: Path, code: str, adapter: CodeAdapter, target: dict, code_cfg: dict) -> None:
    rundir = set_dir / code
    remote = f"{target.get('remote_dir', '~/corefine-runs').rstrip('/')}/{set_dir.name}/{code}"
    host = target["host"]
    try:
        spec = adapter.run_args(rundir)
        (rundir / "job.sh").write_text(render_script(code_cfg, f"cf-{set_dir.name[-9:]}-{code}", spec))
        write_state(set_dir, code, status="staging", message=f"copying inputs to {host}:{remote}", remote_dir=remote)
        _check(_ssh(target, f"mkdir -p {remote}"), "creating the remote folder")
        _check(_copy(target, f"{rundir}/", f"{host}:{remote}/"), "copying inputs")
        sub = _check(_ssh(target, f"cd {remote} && sbatch --parsable job.sh"), "sbatch")
        job_id = sub.stdout.strip().split(";")[0]
        write_state(set_dir, code, status="submitted", remote_job_id=job_id, message=f"Slurm job {job_id} on {host}")
        poll = int(target.get("poll_seconds", 30))
        while True:
            q = _ssh(target, f"sacct -j {job_id} -n -P -X --format=State")
            state = (q.stdout.strip().splitlines() or [""])[0].split()[0] if q.returncode == 0 else ""
            if state in SLURM_DONE | SLURM_FAILED:
                break
            write_state(set_dir, code, status="running" if state == "RUNNING" else "submitted",
                        message=f"Slurm job {job_id} on {host}: {state or 'waiting for sacct'}")
            time.sleep(poll)
        excludes = [a for pattern in target.get("fetch_exclude", []) for a in ("--exclude", pattern)]
        back = subprocess.run([*shlex.split(target.get("copy_command", "rsync -az")), *excludes, f"{host}:{remote}/", f"{rundir}/"],
                              capture_output=True, text=True, timeout=1800)
        _check(back, "copying results back")
        _finish(set_dir, code, adapter, state in SLURM_DONE, f"Slurm job {job_id}: {state}")
    except Exception as e:  # noqa: BLE001
        write_state(set_dir, code, status="failed", finished=now(), message=str(e)[:2000])


def _check(p: subprocess.CompletedProcess, what: str) -> subprocess.CompletedProcess:
    if p.returncode != 0:
        raise RuntimeError(f"{what} failed: {(p.stderr or p.stdout).strip()[-800:]}")
    return p
