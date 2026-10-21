"""Install open-source DFT codes and their data for people who have nothing installed.

Everything goes into TOOLS_DIR (no root, no system changes) and is verified before use:
  micromamba   single static binary from the official mamba-org GitHub release, SHA-256 checked
  qe           Quantum ESPRESSO from conda-forge, in its own environment (GPL-2.0)
  sssp-*       SSSP pseudopotential libraries from the Materials Cloud Archive (CC-BY 4.0), MD5 checked
               against the archive's own file listing; their JSON carries the recommended cutoffs

Commercial codes (VASP) cannot be installed here; their inputs are still generated.
Install state is kept in TOOLS_DIR/tools.json; each install runs in the background with a log.
"""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.config import get_settings

MICROMAMBA_URL = "https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-{plat}"
SSSP_RECORD_FIRST = "e67tc-6b197"   # first version of the SSSP record; the API redirects to the latest version
MC_API = "https://archive.materialscloud.org/api/records"
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tools")
_lock = threading.Lock()


class ToolError(RuntimeError):
    pass


RECIPES: dict[str, dict] = {
    # conda-forge qe 7.6 (build mpi_openmpi_*_102) links libelpa.so.19 without declaring ELPA as a dependency,
    # so ELPA is requested explicitly with the same MPI variant; the ldd check below catches any other gap.
    "qe": {"label": "Quantum ESPRESSO", "kind": "conda", "package": "qe", "channel": "conda-forge",
           "specs": ["qe=*=mpi_openmpi*", "elpa=*=mpi_openmpi*"],
           "provides": {"espresso": "bin/pw.x"}, "license": "GPL-2.0", "size": "about 300 MB",
           "source": "conda-forge (https://anaconda.org/conda-forge/qe)"},
    "sssp-pbe": {"label": "SSSP 1.3 PBE efficiency pseudopotentials", "kind": "sssp", "file": "SSSP_1.3.0_PBE_efficiency",
                 "functional": "PBE", "license": "CC-BY 4.0", "size": "60 MB",
                 "source": "Materials Cloud Archive, SSSP record"},
    "sssp-pbesol": {"label": "SSSP 1.3 PBEsol efficiency pseudopotentials", "kind": "sssp", "file": "SSSP_1.3.0_PBEsol_efficiency",
                    "functional": "PBEsol", "license": "CC-BY 4.0", "size": "60 MB",
                    "source": "Materials Cloud Archive, SSSP record"},
    "gpaw": {"label": "GPAW", "kind": "conda", "package": "gpaw", "channel": "conda-forge", "specs": ["gpaw", "gpaw-data"],
             "provides": {"gpaw": "bin/gpaw"}, "license": "GPL-3.0", "size": "about 400 MB",
             "source": "conda-forge (gpaw + gpaw-data PAW setups)"},
    "abinit": {"label": "ABINIT", "kind": "conda", "package": "abinit", "channel": "conda-forge",
               "provides": {"abinit": "bin/abinit"}, "license": "GPL-3.0", "size": "about 400 MB",
               "source": "conda-forge (https://anaconda.org/conda-forge/abinit)"},
    "pseudodojo-pbe": {"label": "PseudoDojo NC PBE v0.4 (standard)", "kind": "pseudodojo", "repo": "ONCVPSP-PBE-PDv0.4",
                       "branch": "master", "functional": "PBE", "license": "CC-BY 4.0", "size": "about 10 MB",
                       "source": "github.com/PseudoDojo/ONCVPSP-PBE-PDv0.4 (standard.djson: files, MD5, cutoff hints)"},
}
NOT_INSTALLABLE = {"vasp": "VASP is commercial software; CoRefine cannot install it. Inputs are still generated.",
                   "exciting": "exciting is open source but not packaged on conda-forge; build it from "
                               "https://git.physik.hu-berlin.de/sol/exciting and set EXCITING_BIN.",
                   "questaal": "Questaal is open source but not packaged on conda-forge; build it from source and set QUESTAAL_BIN."}


def tools_dir() -> Path:
    d = get_settings().TOOLS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _state() -> dict:
    p = tools_dir() / "tools.json"
    return json.loads(p.read_text()) if p.is_file() else {}


def _set(name: str, **update) -> dict:
    with _lock:
        st = _state()
        st.setdefault(name, {}).update(update, updated=now())
        (tools_dir() / "tools.json").write_text(json.dumps(st, indent=2))
        return st[name]


def status() -> list[dict]:
    st = _state()
    out = [{"name": n, **{k: r[k] for k in ("label", "license", "size", "source")}, "installable": True,
            "status": st.get(n, {}).get("status", "not installed"), "message": st.get(n, {}).get("message", ""),
            "version": st.get(n, {}).get("version")} for n, r in RECIPES.items()]
    return out


def installed(name: str) -> bool:
    return _state().get(name, {}).get("status") == "installed"


# --- paths the adapters and runner use -------------------------------------------

def managed_executable(code: str) -> Path | None:
    for name, r in RECIPES.items():
        rel = r.get("provides", {}).get(code)
        if rel and installed(name):
            p = tools_dir() / "envs" / name / rel
            if p.is_file():
                return p
    return None


def managed_pseudo_dir(functional: str, kind: str = "sssp") -> Path | None:
    """Installed pseudopotential library for a functional: kind 'sssp' (QE) or 'pseudodojo' (ABINIT, norm-conserving)."""
    for name, r in RECIPES.items():
        if r["kind"] == kind and r["functional"] == functional and installed(name):
            d = tools_dir() / "pseudos" / (r.get("file") or r["repo"])
            if d.is_dir():
                return d
    return None


# --- installing -------------------------------------------------------------------

def install(name: str, wait: bool = False) -> dict:
    if name not in RECIPES:
        raise ToolError(NOT_INSTALLABLE.get(name, f"no install recipe for {name!r}"))
    if _state().get(name, {}).get("status") == "installing":
        raise ToolError(f"{name} is already being installed")
    _set(name, status="installing", message="starting", started=now())
    if wait:
        _install(name)
    else:
        _pool.submit(_install, name)
    return _state()[name]


def _install(name: str) -> None:
    r = RECIPES[name]
    log = tools_dir() / "logs" / f"{name}.log"
    log.parent.mkdir(exist_ok=True)
    try:
        if r["kind"] == "conda":
            version = _install_conda(name, r, log)
        elif r["kind"] == "pseudodojo":
            version = _install_pseudodojo(name, r, log)
        else:
            version = _install_sssp(name, r, log)
        _set(name, status="installed", message="ready", version=version, finished=now())
    except Exception as e:  # noqa: BLE001 — recorded for the UI
        _set(name, status="failed", message=str(e)[:1500], finished=now())


def _platform() -> str:
    system, machine = platform.system(), platform.machine().lower()
    if system == "Linux":
        return {"x86_64": "linux-64", "aarch64": "linux-aarch64", "arm64": "linux-aarch64"}.get(machine, "")
    if system == "Darwin":
        return {"x86_64": "osx-64", "arm64": "osx-arm64"}.get(machine, "")
    return ""


def _download(url: str, dest: Path, log: Path) -> Path:
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as resp, open(dest, "wb") as fh, open(log, "a") as lg:
        if resp.status_code != 200:
            raise ToolError(f"download failed: HTTP {resp.status_code} for {url}")
        lg.write(f"downloading {url}\n")
        for chunk in resp.iter_bytes(1 << 20):
            fh.write(chunk)
    return dest


def micromamba(log: Path) -> Path:
    """The micromamba binary, downloaded once and checked against the release's published SHA-256."""
    exe = tools_dir() / "bin" / "micromamba"
    if exe.is_file():
        return exe
    plat = _platform()
    if not plat:
        raise ToolError(f"no micromamba build for {platform.system()} {platform.machine()}")
    exe.parent.mkdir(parents=True, exist_ok=True)
    tmp = _download(MICROMAMBA_URL.format(plat=plat), exe.with_suffix(".part"), log)
    want = httpx.get(MICROMAMBA_URL.format(plat=plat) + ".sha256", follow_redirects=True, timeout=60).text.split()[0]
    got = hashlib.sha256(tmp.read_bytes()).hexdigest()
    if got != want:
        tmp.unlink(missing_ok=True)
        raise ToolError(f"micromamba checksum mismatch ({got} != {want})")
    tmp.rename(exe)
    exe.chmod(0o755)
    return exe


def _conda_version(prefix: Path, package: str) -> str | None:
    """Installed version from the environment's own package metadata (conda-meta/<pkg>-<ver>-<build>.json)."""
    for meta in sorted((prefix / "conda-meta").glob(f"{package}-*.json")):
        data = json.loads(meta.read_text())
        if data.get("name") == package:
            return data.get("version")
    return None


def _install_conda(name: str, r: dict, log: Path) -> str:
    prefix = tools_dir() / "envs" / name
    complete = all((prefix / rel).is_file() for rel in r["provides"].values()) and _conda_version(prefix, r["package"])
    if not complete:
        _set(name, message="getting micromamba")
        mm = micromamba(log)
        env = {**os.environ, "MAMBA_ROOT_PREFIX": str(tools_dir() / "mamba-root")}
        _set(name, message=f"installing {r['package']} from {r['channel']} (this downloads a few hundred MB)")
        with open(log, "a") as lg:
            p = subprocess.run([str(mm), "create", "-y", "-p", str(prefix), "-c", r["channel"], "--override-channels",
                                *r.get("specs", [r["package"]])], stdout=lg, stderr=subprocess.STDOUT, env=env, timeout=3600)
        if p.returncode != 0:
            raise ToolError(f"micromamba exited {p.returncode}; see {log}")
    for rel in r["provides"].values():
        if not (prefix / rel).is_file():
            raise ToolError(f"{r['package']} installed but {rel} is missing")
        missing = missing_libraries(prefix / rel)
        if missing:
            raise ToolError(f"{rel} cannot load {', '.join(missing)} (a packaging problem); see {log}")
    return _conda_version(prefix, r["package"]) or "unknown"


def missing_libraries(exe: Path) -> list[str]:
    """Shared libraries the executable cannot resolve (Linux, via ldd); empty elsewhere or if ldd is absent."""
    if platform.system() != "Linux" or not shutil.which("ldd"):
        return []
    out = subprocess.run(["ldd", str(exe)], capture_output=True, text=True, timeout=60).stdout
    return [ln.split("=>")[0].strip() for ln in out.splitlines() if "not found" in ln]


def _install_sssp(name: str, r: dict, log: Path) -> str:
    _set(name, message="finding the latest SSSP record")
    latest = httpx.get(f"{MC_API}/{SSSP_RECORD_FIRST}/versions/latest", follow_redirects=True, timeout=60).json()["id"]
    listing = {e["key"]: e for e in httpx.get(f"{MC_API}/{latest}/files", timeout=60).json()["entries"]}
    dest = tools_dir() / "pseudos" / r["file"]
    tmp = tools_dir() / "downloads"
    tmp.mkdir(exist_ok=True)
    for ext in ("tar.gz", "json"):
        key = f"{r['file']}.{ext}"
        if key not in listing:
            raise ToolError(f"{key} is not in the SSSP record {latest}")
        _set(name, message=f"downloading {key}")
        f = _download(f"{MC_API}/{latest}/files/{key}/content", tmp / key, log)
        want = listing[key]["checksum"].removeprefix("md5:")
        got = hashlib.md5(f.read_bytes()).hexdigest()
        if got != want:
            raise ToolError(f"{key}: MD5 mismatch ({got} != {want})")
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    with tarfile.open(tmp / f"{r['file']}.tar.gz") as tar:
        tar.extractall(dest, filter="data")
    # tarballs may hold a top-level folder; flatten so the UPF files sit next to the JSON
    for upf in list(dest.rglob("*")):
        if upf.is_file() and upf.parent != dest:
            upf.rename(dest / upf.name)
    shutil.copy2(tmp / f"{r['file']}.json", dest / f"{r['file']}.json")
    n = len(list(dest.glob("*.[uU][pP][fF]")))
    if n < 50:
        raise ToolError(f"only {n} pseudopotential files after unpacking")
    return f"{r['file']} ({n} elements, record {latest})"


GITHUB_RAW = "https://raw.githubusercontent.com/PseudoDojo/{repo}/{branch}/{path}"


def _install_pseudodojo(name: str, r: dict, log: Path) -> str:
    """standard.djson lists the recommended pseudopotential per element with its MD5 and cutoff hints."""
    url = GITHUB_RAW.format(repo=r["repo"], branch=r["branch"], path="standard.djson")
    _set(name, message="downloading the PseudoDojo index (standard.djson)")
    resp = httpx.get(url, follow_redirects=True, timeout=60)
    if resp.status_code != 200:
        raise ToolError(f"PseudoDojo index: HTTP {resp.status_code}")
    meta = resp.json()["pseudos_metadata"]
    dest = tools_dir() / "pseudos" / r["repo"]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "standard.djson").write_bytes(resp.content)
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for i, (el, m) in enumerate(sorted(meta.items()), 1):
            target = dest / m["basename"]
            if target.is_file() and hashlib.md5(target.read_bytes()).hexdigest() == m["md5"]:
                continue
            _set(name, message=f"downloading {m['basename']} ({i}/{len(meta)})")
            data = client.get(GITHUB_RAW.format(repo=r["repo"], branch=r["branch"], path=f"{el}/{m['basename']}")).content
            if hashlib.md5(data).hexdigest() != m["md5"]:
                raise ToolError(f"{m['basename']}: MD5 mismatch with standard.djson")
            target.write_bytes(data)
    return f"{r['repo']} standard ({len(meta)} elements)"
