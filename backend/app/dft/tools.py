"""Install open-source DFT codes and their data for people who have nothing installed.

Everything goes into TOOLS_DIR (no root, no system changes) and is verified before use:
  micromamba   single static binary from the official mamba-org GitHub release, SHA-256 checked
  qe           Quantum ESPRESSO from conda-forge, in its own environment (GPL-2.0)
  sssp-*       SSSP pseudopotential libraries from the Materials Cloud Archive (CC-BY 4.0), MD5 checked
               against the archive's own file listing; their JSON carries the recommended cutoffs
  pseudodojo-* PseudoDojo norm-conserving tables (ABINIT), MD5 checked against standard.djson
  jth-lda      JTH v1.1 LDA PAW datasets as UPF (QE has no SSSP for LDA); cutoff hints from the JTH table's
               standard.djson, written into an SSSP-style JSON so the QE adapter reads them the same way

Commercial codes (VASP) cannot be installed here; their inputs are still generated.
Install state is kept in TOOLS_DIR/tools.json; each install runs in its own detached process with a log, so a
backend restart (or --reload) does not kill it. On startup, installs whose process is gone are settled from disk.
"""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.config import get_settings

MICROMAMBA_URL = "https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-{plat}"
SSSP_RECORD_FIRST = "e67tc-6b197"   # first version of the SSSP record; the API redirects to the latest version
MC_API = "https://archive.materialscloud.org/api/records"


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
    # conda-forge builds ABINIT for Intel Macs only; Apple Silicon runs that build under Rosetta 2
    "abinit": {"label": "ABINIT", "kind": "conda", "package": "abinit", "channel": "conda-forge",
               "platform_fallback": {"osx-arm64": "osx-64"},
               "provides": {"abinit": "bin/abinit"}, "license": "GPL-3.0", "size": "about 400 MB",
               "source": "conda-forge (https://anaconda.org/conda-forge/abinit)"},
    "pseudodojo-pbe": {"label": "PseudoDojo NC PBE v0.4 (standard)", "kind": "pseudodojo", "repo": "ONCVPSP-PBE-PDv0.4",
                       "branch": "master", "functional": "PBE", "license": "CC-BY 4.0", "size": "about 10 MB",
                       "source": "github.com/PseudoDojo/ONCVPSP-PBE-PDv0.4 (standard.djson: files, MD5, cutoff hints)"},
    "pseudodojo-lda": {"label": "PseudoDojo NC LDA v0.4 (standard)", "kind": "pseudodojo", "repo": "ONCVPSP-LDA-PDv0.4",
                       "branch": "main", "functional": "LDA", "license": "CC-BY 4.0", "size": "about 10 MB",
                       "source": "github.com/PseudoDojo/ONCVPSP-LDA-PDv0.4 (standard.djson: files, MD5, cutoff hints)"},
    # XRD refinement engines
    "gsas2": {"label": "GSAS-II (Rietveld refinement)", "kind": "gsas2", "repo": "https://github.com/AdvancedPhotonSource/GSAS-II.git",
              "commit": "a39f978abcd66cc234a170f11837578e87d3bf11",
              "specs": ["python=3.13", "numpy", "scipy", "pycifrw", "meson-python", "ninja", "cython", "pkg-config",
                        "c-compiler", "fortran-compiler", "git", "pip"],
              "provides": {"gsas2": "bin/python"}, "license": "GSAS-II licence (free, open source)", "size": "about 1 GB",
              "source": "github.com/AdvancedPhotonSource/GSAS-II, built from a pinned commit (not on PyPI or conda-forge)"},
    "maud": {"label": "MAUD (Rietveld and microstructure)", "kind": "release", "repo": "luttero/Maud", "tag": "v3.08",
             "assets": {"linux-64": "Maud_linux_x64.tar.gz", "linux-aarch64": "Maud_linux_aarch64.tar.gz",
                        "osx-arm64": "Maud_macos_aarch64.dmg.gz", "osx-64": "Maud_macos_x64.dmg.gz"},
             "provides": {"maud": "Maud/jdk/bin/java"},
             # the macOS build is an app bundle: jars in Contents/Java, its own Java runtime under Contents/PlugIns/Home
             "provides_macos": {"maud": "Maud.app/Contents/PlugIns/Home/bin/java"},
             "license": "BSD-3-Clause", "size": "about 300 MB download",
             "source": "github.com/luttero/Maud release v3.08 (bundled Java), SHA-256 from GitHub's release record"},
    # PseudoDojo's LDA v0.4 table has psp8 files but almost no UPF, so QE gets the JTH PAW table instead
    "jth-lda": {"label": "JTH v1.1 LDA PAW datasets (UPF, for Quantum ESPRESSO)", "kind": "jth", "repo": "ATOMPAW-LDA-JTHv1.1",
                "branch": "main", "functional": "LDA", "license": "GPL-3.0", "size": "about 60 MB",
                "index": "https://raw.githubusercontent.com/abinit/paw_jth_datasets/main/pseudos/JTH-LDA-v1.1/standard.djson",
                "source": "UPF files from github.com/PseudoDojo/ATOMPAW-LDA-JTHv1.1; cutoff hints from "
                          "github.com/abinit/paw_jth_datasets (JTH-LDA-v1.1/standard.djson)"},
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


@contextmanager
def _locked():
    """tools.json is written by the backend and by install processes; an advisory file lock keeps writes whole."""
    with open(tools_dir() / "tools.lock", "w") as fh:
        try:
            import fcntl
        except ImportError:  # Windows: single writer is the common case; accept the small race
            yield
            return
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _set(name: str, **update) -> dict:
    with _locked():
        st = _state()
        st.setdefault(name, {}).update(update, updated=now())
        (tools_dir() / "tools.json").write_text(json.dumps(st, indent=2))
        return st[name]


def status() -> list[dict]:
    recover_interrupted()  # an install process that died (killed, out of disk) must not stay "installing" forever
    st = _state()
    out = [{"name": n, **{k: r[k] for k in ("label", "license", "size", "source")}, "installable": True,
            "status": st.get(n, {}).get("status", "not installed"), "message": st.get(n, {}).get("message", ""),
            "version": st.get(n, {}).get("version"), "finished": st.get(n, {}).get("finished")}
           for n, r in RECIPES.items()]
    return out


def installed(name: str) -> bool:
    return _state().get(name, {}).get("status") == "installed"


# --- paths the adapters and runner use -------------------------------------------

def provides(r: dict) -> dict[str, str]:
    """What an install puts on disk for this platform (the macOS build of a release can be laid out differently)."""
    return r.get("provides_macos", r.get("provides", {})) if platform.system() == "Darwin" else r.get("provides", {})


def managed_executable(code: str) -> Path | None:
    for name, r in RECIPES.items():
        rel = provides(r).get(code)
        if rel and installed(name):
            p = tools_dir() / ("apps" if r["kind"] == "release" else "envs") / name / rel
            if p.is_file():
                return p
    return None


def managed_pseudo_dir(functional: str, kind: str | tuple[str, ...] = ("sssp", "jth")) -> Path | None:
    """Installed pseudopotential library for a functional: kinds 'sssp'/'jth' (QE, UPF) or 'pseudodojo' (ABINIT, psp8)."""
    kinds = (kind,) if isinstance(kind, str) else kind
    for name, r in RECIPES.items():
        if r["kind"] in kinds and r["functional"] == functional and installed(name):
            d = tools_dir() / "pseudos" / (r.get("file") or r["repo"])
            if d.is_dir():
                return d
    return None


# --- installing -------------------------------------------------------------------

def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def install(name: str, wait: bool = False) -> dict:
    if name not in RECIPES:
        raise ToolError(NOT_INSTALLABLE.get(name, f"no install recipe for {name!r}"))
    cur = _state().get(name, {})
    if cur.get("status") == "installing" and _alive(cur.get("pid")):
        raise ToolError(f"{name} is already being installed")
    _set(name, status="installing", message="starting", started=now(), pid=os.getpid() if wait else None, finished=None)
    if wait:
        _install(name)
    else:
        log = tools_dir() / "logs" / f"{name}.log"
        log.parent.mkdir(exist_ok=True)
        with open(log, "a") as lg:
            p = subprocess.Popen([sys.executable, "-m", "app.dft.tools", name], cwd=Path(__file__).resolve().parents[2],
                                 stdout=lg, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        _set(name, pid=p.pid)
    return _state()[name]


def _complete(name: str) -> str | None:
    """The installed version if the files of an install are all on disk, else None (used after an interruption)."""
    r = RECIPES[name]
    if r["kind"] == "conda":
        prefix = tools_dir() / "envs" / name
        ok = all((prefix / rel).is_file() for rel in provides(r).values())
        return _conda_version(prefix, r["package"]) if ok else None
    if r["kind"] == "release":
        dest = tools_dir() / "apps" / name
        return f"{r['repo'].split('/')[-1]} {r['tag']}" if all((dest / p).is_file() for p in provides(r).values()) else None
    return None  # pseudopotential tables and GSAS-II are cheap to re-check by running the install again


def recover_interrupted() -> list[str]:
    """Settle installs left 'installing' by a process that no longer runs: complete on disk -> installed, else failed."""
    settled = []
    for name, st in _state().items():
        if name not in RECIPES or st.get("status") != "installing" or _alive(st.get("pid")):
            continue
        if version := _complete(name):
            _set(name, status="installed", message="ready", version=version, finished=now(), pid=None)
        else:
            _set(name, status="failed", message="interrupted before it finished (the backend stopped); click Retry",
                 finished=now(), pid=None)
        settled.append(name)
    return settled


def log_tail(name: str, lines: int = 60) -> str:
    log = tools_dir() / "logs" / f"{name}.log"
    return "\n".join(log.read_text(errors="replace").splitlines()[-lines:]) if log.is_file() else ""


def _install(name: str) -> None:
    r = RECIPES[name]
    log = tools_dir() / "logs" / f"{name}.log"
    log.parent.mkdir(exist_ok=True)
    try:
        if r["kind"] == "conda":
            version = _install_conda(name, r, log)
        elif r["kind"] == "pseudodojo":
            version = _install_pseudodojo(name, r, log)
        elif r["kind"] == "jth":
            version = _install_jth(name, r, log)
        elif r["kind"] == "gsas2":
            version = _install_gsas2(name, r, log)
        elif r["kind"] == "release":
            version = _install_release(name, r, log)
        else:
            version = _install_sssp(name, r, log)
        _set(name, status="installed", message="ready", version=version, finished=now(), pid=None)
    except Exception as e:  # noqa: BLE001 — recorded for the UI
        _set(name, status="failed", message=str(e)[:1500], finished=now(), pid=None)


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
    complete = all((prefix / rel).is_file() for rel in provides(r).values()) and _conda_version(prefix, r["package"])
    if not complete:
        _set(name, message="getting micromamba")
        mm = micromamba(log)
        env = {**os.environ, "MAMBA_ROOT_PREFIX": str(tools_dir() / "mamba-root")}
        _set(name, message=f"installing {r['package']} from {r['channel']} (this downloads a few hundred MB)")
        with open(log, "a") as lg:
            plat = r.get("platform_fallback", {}).get(_platform())
            p = subprocess.run([str(mm), "create", "-y", "-p", str(prefix), "-c", r["channel"], "--override-channels",
                                *(["--platform", plat] if plat else []), *r.get("specs", [r["package"]])],
                               stdout=lg, stderr=subprocess.STDOUT, env=env, timeout=3600)
        if p.returncode != 0:
            raise ToolError(f"micromamba exited {p.returncode}; see {log}")
    for rel in provides(r).values():
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


HA_TO_RY = 2.0


def _install_jth(name: str, r: dict, log: Path) -> str:
    """UPF per element from the PseudoDojo mirror of the JTH table, plus a cutoff table from the JTH standard.djson.

    The djson hints are ABINIT plane-wave cutoffs in Ha; pw.x takes Ry, so ecutwfc = 2 x hint. ecutrho is left
    out, so the QE adapter uses pw.x's own default (4 x ecutwfc). Elements without a hint get no entry, and the
    adapter then refuses them instead of guessing. The djson MD5s are for the XML files, not the UPFs, so no
    MD5 is claimed; the SHA-256 of each downloaded UPF is recorded instead.
    """
    _set(name, message="downloading the JTH index (standard.djson)")
    resp = httpx.get(r["index"], follow_redirects=True, timeout=60)
    if resp.status_code != 200:
        raise ToolError(f"JTH index: HTTP {resp.status_code}")
    meta = resp.json()["pseudo_metadata"]
    dest = tools_dir() / "pseudos" / r["repo"]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "jth_standard.djson").write_bytes(resp.content)
    table = {}
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for i, (el, m) in enumerate(sorted(meta.items()), 1):
            fname = f"{el}.LDA-PW-paw.UPF"
            target = dest / fname
            if not target.is_file():
                _set(name, message=f"downloading {fname} ({i}/{len(meta)})")
                resp = client.get(GITHUB_RAW.format(repo=r["repo"], branch=r["branch"], path=f"{el}/{fname}"))
                if resp.status_code != 200:
                    continue  # not in the UPF mirror; the element stays unavailable for QE
                if b"<PP_HEADER" not in resp.content[:20000]:
                    raise ToolError(f"{fname} is not a UPF v2 file")
                target.write_bytes(resp.content)
            hint = (m.get("hints") or {}).get("normal", {}).get("ecut")
            if hint:
                table[el] = {"filename": fname, "cutoff_wfc": HA_TO_RY * float(hint), "cutoff_rho": None, "md5": None,
                             "sha256_downloaded": hashlib.sha256(target.read_bytes()).hexdigest(),
                             "cutoff_source": f"JTH-LDA-v1.1 standard.djson hint {hint} Ha (normal) x 2 Ry/Ha"}
    (dest / "JTH_LDA_v1.1_cutoffs.json").write_text(json.dumps(table, indent=1))
    n = len(list(dest.glob("*.UPF")))
    if n < 50:
        raise ToolError(f"only {n} UPF files downloaded")
    return f"{r['repo']} ({n} elements, {len(table)} with cutoff hints)"


def _install_gsas2(name: str, r: dict, log: Path) -> str:
    """GSAS-II is not packaged; its own build (meson + gfortran) runs in a conda-forge environment from a pinned commit."""
    prefix = tools_dir() / "envs" / name
    mm = micromamba(log)
    env = {**os.environ, "MAMBA_ROOT_PREFIX": str(tools_dir() / "mamba-root")}
    with open(log, "a") as lg:
        if not (prefix / "bin" / "python").is_file():
            _set(name, message="creating the build environment (compilers, numpy, scipy)")
            p = subprocess.run([str(mm), "create", "-y", "-p", str(prefix), "-c", "conda-forge", "--override-channels", *r["specs"]],
                               stdout=lg, stderr=subprocess.STDOUT, env=env, timeout=3600)
            if p.returncode != 0:
                raise ToolError(f"micromamba exited {p.returncode}; see {log}")
        src = tools_dir() / "src" / "GSAS-II"
        if not (src / ".git").is_dir():
            _set(name, message="downloading the GSAS-II source")
            subprocess.run(["git", "clone", "-q", r["repo"], str(src)], stdout=lg, stderr=subprocess.STDOUT, check=True, timeout=1800)
        subprocess.run(["git", "-C", str(src), "fetch", "-q", "origin", r["commit"]], stdout=lg, stderr=subprocess.STDOUT, timeout=600)
        subprocess.run(["git", "-C", str(src), "checkout", "-q", r["commit"]], stdout=lg, stderr=subprocess.STDOUT, check=True)
        _set(name, message="compiling GSAS-II (a few minutes)")
        p = subprocess.run([str(mm), "run", "-p", str(prefix), "pip", "install", "--no-build-isolation", str(src)],
                           stdout=lg, stderr=subprocess.STDOUT, env=env, timeout=3600)
        if p.returncode != 0:
            raise ToolError(f"GSAS-II build failed; see {log}")
        p = subprocess.run([str(prefix / "bin" / "python"), "-c", "from GSASII import GSASIIscriptable"],
                           stdout=lg, stderr=subprocess.STDOUT, timeout=300)
        if p.returncode != 0:
            raise ToolError(f"GSAS-II built but GSASIIscriptable does not import; see {log}")
    return f"GSAS-II {r['commit'][:10]}"


def _unpack_dmg(gz: Path, dest: Path, log: Path) -> None:
    """macOS disk image (gzipped): mount it read-only and out of sight, copy the app bundle out, unmount."""
    import gzip
    import tempfile

    dmg = gz.with_suffix("")  # x.dmg.gz -> x.dmg
    with gzip.open(gz) as src, open(dmg, "wb") as out:
        shutil.copyfileobj(src, out, 1 << 20)
    mnt = Path(tempfile.mkdtemp(prefix="corefine-dmg-"))
    with open(log, "a") as lg:
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", str(mnt), str(dmg)],
                       stdout=lg, stderr=subprocess.STDOUT, check=True, timeout=600)
        try:
            for app in mnt.glob("*.app"):  # ditto keeps the bundle's permissions, symlinks and code signature
                subprocess.run(["ditto", str(app), str(dest / app.name)], stdout=lg, stderr=subprocess.STDOUT, check=True, timeout=1800)
        finally:
            subprocess.run(["hdiutil", "detach", str(mnt)], stdout=lg, stderr=subprocess.STDOUT, timeout=120)
            dmg.unlink(missing_ok=True)


def _install_release(name: str, r: dict, log: Path) -> str:
    """A GitHub release asset, checked against the SHA-256 GitHub records for it, unpacked under TOOLS_DIR/apps."""
    asset = r["assets"].get(_platform())
    if not asset:
        raise ToolError(f"{r['label']}: no release build for {platform.system()} {platform.machine()} that runs headless")
    rel = httpx.get(f"https://api.github.com/repos/{r['repo']}/releases/tags/{r['tag']}", timeout=60).json()
    meta = next((a for a in rel.get("assets", []) if a["name"] == asset), None)
    if not meta or not str(meta.get("digest", "")).startswith("sha256:"):
        raise ToolError(f"{asset}: no SHA-256 in the GitHub release record; not installed")
    tmp = tools_dir() / "downloads"
    tmp.mkdir(exist_ok=True)
    f = tmp / asset
    if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != meta["digest"].removeprefix("sha256:"):
        _set(name, message=f"downloading {asset}")
        _download(meta["browser_download_url"], f, log)
    got = hashlib.sha256(f.read_bytes()).hexdigest()
    if got != meta["digest"].removeprefix("sha256:"):
        raise ToolError(f"{asset}: SHA-256 mismatch ({got})")
    dest = tools_dir() / "apps" / name
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    _set(name, message="unpacking")
    if asset.endswith(".dmg.gz"):
        _unpack_dmg(f, dest, log)
    else:
        with tarfile.open(f) as tar:
            tar.extractall(dest, filter="data", members=[m for m in tar.getmembers() if "/._" not in "/" + m.name])
    for rel_path in provides(r).values():
        if not (dest / rel_path).is_file():
            raise ToolError(f"{rel_path} missing after unpacking")
    return f"{r['repo'].split('/')[-1]} {r['tag']}"


if __name__ == "__main__":  # the detached install process started by install()
    _install(sys.argv[1])
