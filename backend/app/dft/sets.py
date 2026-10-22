"""Where simulation sets live. The codes run on this computer, so a set is worked on in a local folder; the record is
in the cloud services: its files in object storage under dft/<id>/ and one database row (what the list and the set's
page show). When nothing is running, the folder is uploaded and removed; starting new work downloads it again.

Restart scratch (wavefunctions, densities: hundreds of MB, rewritten by every run) is never uploaded. Results come
from the codes' text outputs, which are kept. In local mode (development, tests) the folder is the record and
nothing is uploaded or removed.
"""

import hashlib
import json
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings

SET_ID = re.compile(r"^dft-\d{8}-\d{6}-[0-9a-f]{4}$")
PREFIX = "dft/"
SYNCED = ".synced.json"  # rel path -> sha256 of what is in storage; local bookkeeping, never uploaded
MAX_FILE_BYTES = 25 * 1024 * 1024
SCRATCH_DIRS = {"tmp"}  # Quantum ESPRESSO outdir (wavefunctions, charge density)
SCRATCH_FILE = re.compile(r"(_WFK|_DEN|_POT)(\.nc)?$|\.gpw$|^(STATE|EVECFV|EVECSV)\.OUT$|^(rst|mixm)\.")
LIVE = {"waiting", "queued", "staging", "submitted", "running"}

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dftsync")
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def cloud() -> bool:
    return get_settings().is_cloud


def local_root() -> Path:
    d = get_settings().LOCAL_DATA_DIR / "dft"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lock(set_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(set_id, threading.Lock())


def set_root(path: Path) -> Path | None:
    """The set folder containing path (runs and studies write in sub-folders of their set)."""
    for p in (path, *path.parents):
        if SET_ID.match(p.name):
            return p
    return None


# --- what the list and the page show -------------------------------------------------

def listing(d: Path) -> dict:
    prov = json.loads((d / "provenance.json").read_text())
    chk = json.loads((d / "checks.json").read_text())
    return {"id": d.name, "created": prov["created"], "structure": prov["request"]["structure"],
            "formula": prov["cell"]["formula"], "functional": prov["request"]["functional"],
            "kmesh": prov["request"]["kmesh"], "codes": prov["request"]["codes"], "passed": chk["passed"],
            "n_checks": len(chk["results"]), "n_failed": sum(r["ok"] is False for r in chk["results"]),
            "n_passed": sum(r["ok"] is True for r in chk["results"])}


def describe(d: Path) -> dict:
    from app.dft import execute, raman, studies

    files = sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and p.name != SYNCED)
    plan = json.loads((d / "plan.json").read_text()) if (d / "plan.json").is_file() else None
    summary = json.loads((d / "summary.json").read_text()) if (d / "summary.json").is_file() else None
    return {"id": d.name, "provenance": json.loads((d / "provenance.json").read_text()),
            "checks": json.loads((d / "checks.json").read_text()), "files": files, "runs": execute.all_states(d),
            "plan": plan, "summary": summary, "studies": {**studies.read(d), "raman": raman.read(d)}}


def busy(d: Path) -> bool:
    """Something is queued or running in this set (a code run, or a study and its runs)."""
    states = [json.loads(p.read_text()).get("status") for p in (d / "runs").glob("*.json")] if (d / "runs").is_dir() else []
    states += [json.loads(p.read_text()).get("status") for p in (d / "studies").rglob("study.json")]
    return any(s in LIVE for s in states)


def all_listings() -> list[dict]:
    """Every set: the database rows, plus folders being worked on here that have no row yet."""
    out = {}
    if cloud():
        from app.models.db import DftSetRow, get_sessionmaker

        with get_sessionmaker()() as db:
            out = {r.id: r.listing for r in db.query(DftSetRow).all()}
    for d in local_root().glob("dft-*"):
        if SET_ID.match(d.name):
            try:
                out[d.name] = listing(d)
            except (OSError, json.JSONDecodeError, KeyError):
                continue
    return sorted(out.values(), key=lambda x: x["id"], reverse=True)


def detail(set_id: str) -> dict | None:
    d = local_root() / set_id
    if d.is_dir():
        return describe(d)
    if cloud():
        from app.models.db import DftSetRow, get_sessionmaker

        with get_sessionmaker()() as db:
            row = db.get(DftSetRow, set_id)
            return row.detail if row else None
    return None


def read_file(set_id: str, rel: str) -> bytes | None:
    d = local_root() / set_id
    if d.is_dir():
        f = (d / rel).resolve()
        return f.read_bytes() if f.is_relative_to(d.resolve()) and f.is_file() and f.name != SYNCED else None
    if cloud() and ".." not in Path(rel).parts:
        from app.storage.objects import get_store

        try:
            return get_store().get(f"{PREFIX}{set_id}/{rel}")
        except Exception:  # noqa: BLE001 — missing key
            return None
    return None


def all_files(set_id: str) -> list[tuple[str, bytes]]:
    d = local_root() / set_id
    if d.is_dir():
        return [(str(p.relative_to(d)), p.read_bytes()) for p in sorted(d.rglob("*")) if p.is_file() and p.name != SYNCED]
    if not cloud():
        return []
    from app.storage.objects import get_store

    store, base = get_store(), f"{PREFIX}{set_id}/"
    return [(k[len(base):], store.get(k)) for k in store.list(base)]


def exists(set_id: str) -> bool:
    return (local_root() / set_id).is_dir() or detail(set_id) is not None


# --- moving a set between this computer and the cloud --------------------------------------

def _kept(d: Path) -> dict[str, Path]:
    out = {}
    for p in d.rglob("*"):
        rel = p.relative_to(d)
        if not p.is_file() or p.name == SYNCED or SCRATCH_DIRS & set(rel.parts[:-1]) or SCRATCH_FILE.search(p.name):
            continue
        if p.stat().st_size > MAX_FILE_BYTES:
            continue
        out[str(rel)] = p
    return out


def push(d: Path) -> dict:
    """Upload what changed, drop what was removed, and write the database row. Returns {uploaded, removed}."""
    from app.models.db import DftSetRow, get_sessionmaker
    from app.storage.objects import get_store

    store, base = get_store(), f"{PREFIX}{d.name}/"
    side = d / SYNCED
    synced = json.loads(side.read_text()) if side.is_file() else {}
    kept = _kept(d)
    up = 0
    for rel, p in kept.items():
        data = p.read_bytes()
        h = hashlib.sha256(data).hexdigest()
        if synced.get(rel) != h:
            store.put(base + rel, data)
            synced[rel] = h
            up += 1
    gone = [k for k in store.list(base) if k[len(base):] not in kept]
    for k in gone:
        store.delete(k)
        synced.pop(k[len(base):], None)
    side.write_text(json.dumps(synced))
    with get_sessionmaker()() as db:
        row = db.get(DftSetRow, d.name) or DftSetRow(id=d.name)
        row.listing, row.detail, row.updated_at = listing(d), describe(d), datetime.now(UTC)
        db.merge(row)
        db.commit()
    return {"uploaded": up, "removed": len(gone)}


def pull(set_id: str) -> Path:
    """Download a set into its local working folder (the files in storage, without restart scratch)."""
    from app.storage.objects import get_store

    store, base = get_store(), f"{PREFIX}{set_id}/"
    keys = store.list(base)
    if not keys:
        raise FileNotFoundError(set_id)
    d = local_root() / set_id
    tmp = d.with_name(d.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    synced = {}
    for k in keys:
        data = store.get(k)
        f = tmp / k[len(base):]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        synced[k[len(base):]] = hashlib.sha256(data).hexdigest()
    (tmp / SYNCED).write_text(json.dumps(synced))
    tmp.rename(d)
    return d


def settle(path: Path) -> str:
    """Upload the set and, if nothing in it is queued or running, remove the local folder. Cloud mode only."""
    d = set_root(path)
    if d is None or not cloud():
        return "skipped"
    with _lock(d.name):
        if not d.is_dir():
            return "gone"
        push(d)
        if busy(d):
            return "uploaded"
        shutil.rmtree(d)
        return "uploaded and removed locally"


def fail_interrupted() -> list[str]:
    """At startup: runs and studies that ran in this backend's threads died with it. Mark them failed (a Slurm job
    keeps running on its cluster and is left alone), then upload each local set. Returns the sets touched."""
    note = "interrupted: the backend restarted while this was in progress"
    touched = []
    for d in local_root().glob("dft-*"):
        if not SET_ID.match(d.name):
            continue
        changed = False
        for p in d.rglob("runs/*.json"):
            st = json.loads(p.read_text())
            if st.get("status") in LIVE and st.get("kind") != "slurm":
                st.update(status="failed", message=note, finished=datetime.now(UTC).isoformat(timespec="seconds"))
                p.write_text(json.dumps(st, indent=2))
                changed = True
        for p in (d / "studies").rglob("study.json"):
            st = json.loads(p.read_text())
            if st.get("status") in LIVE:
                st.update(status="failed", message=note)
                p.write_text(json.dumps(st, indent=2))
                changed = True
        if changed:
            touched.append(d.name)
        settle_soon(d)
    return touched


def settle_soon(path: Path) -> None:
    if cloud() and set_root(path) is not None:
        _pool.submit(_settle_logged, path)


def _settle_logged(path: Path) -> None:
    import logging

    try:
        logging.getLogger("corefine").info("simulation set %s: %s", path, settle(path))
    except Exception:  # noqa: BLE001 — the local folder stays; the next settle retries
        logging.getLogger("corefine").exception("could not upload simulation set %s", path)


@contextmanager
def working(set_id: str):
    """The local folder of a set, downloaded first if needed. Hold it while starting work, so the set cannot be
    removed between the download and the first 'queued' state."""
    with _lock(set_id):
        d = local_root() / set_id
        if not d.is_dir():
            if not cloud():
                raise FileNotFoundError(set_id)
            pull(set_id)
        yield d
