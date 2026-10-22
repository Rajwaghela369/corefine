"""All-electron DFT input jobs: generate exciting + Questaal inputs, check them, serve the files."""

import io
import re
import secrets
import zipfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.agents.llm import LLMError
from app.config import get_settings
from app.dft import execute, materials, raman, sets, sources, structure, studies, tools, workflow
from app.dft.codes import REGISTRY
from app.dft.codes.exciting import ExcitingSetupError
from app.dft.codes.questaal import QuestaalSetupError
from app.dft.pipeline import RequestError, prepare
from app.dft.request import CalcRequest, from_prompt

router = APIRouter(prefix="/dft", tags=["dft"])
JOB_ID = re.compile(r"^dft-\d{8}-\d{6}-[0-9a-f]{4}$")
MAX_CIF_BYTES = 5 * 1024 * 1024


def jobs_dir() -> Path:
    """Local working folders; the record of each set is in the cloud services (app/dft/sets.py)."""
    return sets.local_root()


@contextmanager
def job_dir(job_id: str):
    """The set's working folder, downloaded first if only the cloud copy exists."""
    if not JOB_ID.match(job_id):
        raise HTTPException(400, detail="bad job id")
    try:
        with sets.working(job_id) as d:
            yield d
    except FileNotFoundError as e:
        raise HTTPException(404, detail=f"no job {job_id}") from e


class JobRequest(BaseModel):
    prompt: str | None = None
    structure: str | None = None
    codes: list[str] | None = None
    functional: str | None = None
    kmesh: tuple[int, int, int] | None = None


SETUP_ERRORS = (RequestError, sources.SourceError, structure.SymmetryError, ExcitingSetupError, QuestaalSetupError, LLMError)


@router.get("/config")
def config():
    """Registered code adapters, whether each is usable on this server, and whether prompts can be parsed."""
    s = get_settings()
    return {"codes": [a.describe(s) for a in REGISTRY.values()], "prompt": bool(s.ANTHROPIC_API_KEY)}


@router.post("/jobs")
def create_job(body: JobRequest):
    """Runs synchronously (a few seconds: structure fetch, blm, lmfa, lmchk)."""
    try:
        req = from_prompt(body.prompt) if body.prompt else CalcRequest()
        overrides = {k: v for k, v in body.model_dump(exclude={"prompt"}).items() if v}
        req = CalcRequest.model_validate({**req.model_dump(), **overrides})
        job_id = f"dft-{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        result = prepare(req, jobs_dir() / job_id)
        sets.settle_soon(jobs_dir() / job_id)
    except SETUP_ERRORS as e:
        raise HTTPException(400, detail=str(e)) from e
    except ValueError as e:  # pydantic validation of the merged request
        raise HTTPException(400, detail=str(e)) from e
    return {"id": job_id, "passed": result["checks"]["passed"]}


@router.get("/jobs")
def list_jobs():
    return sets.all_listings()


def _known(job_id: str) -> None:
    if not JOB_ID.match(job_id):
        raise HTTPException(400, detail="bad job id")


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    _known(job_id)
    if (d := sets.detail(job_id)) is None:
        raise HTTPException(404, detail=f"no job {job_id}")
    return d


@router.get("/jobs/{job_id}/files/{path:path}")
def get_file(job_id: str, path: str):
    _known(job_id)
    if (data := sets.read_file(job_id, path)) is None:
        raise HTTPException(404, detail=f"{path} not found")
    return Response(data, media_type="text/plain; charset=utf-8")


@router.get("/jobs/{job_id}/archive")
def archive(job_id: str):
    _known(job_id)
    files = sets.all_files(job_id)
    if not files:
        raise HTTPException(404, detail=f"no job {job_id}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, data in files:
            z.writestr(f"{job_id}/{rel}", data)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{job_id}.zip"'})


@router.post("/upload")
async def upload_cif(file: UploadFile):
    data = await file.read()
    if len(data) > MAX_CIF_BYTES:
        raise HTTPException(413, detail="CIF larger than 5 MB")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", (file.filename or "structure.cif").rsplit("/", 1)[-1])
    if not name.lower().endswith(".cif"):
        raise HTTPException(400, detail="upload a .cif file")
    up = jobs_dir() / "uploads"
    up.mkdir(exist_ok=True)
    path = up / f"{secrets.token_hex(3)}-{name}"
    path.write_bytes(data)
    try:
        src = sources.load(str(path))
        cell = structure.standard_primitive(src.atoms)
    except (sources.SourceError, structure.SymmetryError) as e:
        path.unlink(missing_ok=True)
        raise HTTPException(400, detail=str(e)) from e
    return {"structure": str(path), "name": name, "cell": cell.summary()}


# --- running ---------------------------------------------------------------------

class RunBody(BaseModel):
    code: str
    target: str


@router.get("/targets")
def targets():
    """Compute targets from compute.yaml (per user/site). Hosts are shown; nothing secret is stored there."""
    try:
        return execute.describe_targets()
    except execute.ComputeConfigError as e:
        raise HTTPException(400, detail=str(e)) from e


@router.post("/jobs/{job_id}/runs")
def start_run(job_id: str, body: RunBody):
    with job_dir(job_id) as d:
        try:
            return execute.start(d, body.code, body.target)
        except execute.ComputeConfigError as e:
            raise HTTPException(400, detail=str(e)) from e


@router.post("/jobs/{job_id}/runs/{code}/import")
async def import_results(job_id: str, code: str, files: list[UploadFile]):
    """Attach output files of a run done elsewhere (e.g. submitted by hand); they are parsed like any run."""
    from dataclasses import asdict

    uploads = [(re.sub(r"[^A-Za-z0-9._-]", "_", (f.filename or "file").rsplit("/", 1)[-1]), await f.read()) for f in files]
    with job_dir(job_id) as d:
        adapter = REGISTRY.get(code)
        if adapter is None or not (d / code).is_dir():
            raise HTTPException(404, detail=f"this set has no {code} inputs")
        for name, data in uploads:
            (d / code / name).write_bytes(data)
        res = adapter.parse_results(d / code)
        if res is None:
            raise HTTPException(400, detail=f"no {adapter.label} output recognised among the uploaded files")
        return execute.write_state(d, code, target="imported", kind="import", status="completed",
                                   finished=execute.now(), message=f"imported {len(files)} file(s)", results=asdict(res))


# --- installing codes ---------------------------------------------------------------

# what one click installs to make a code usable locally
CODE_TOOLS = {"espresso": ["qe", "sssp-pbe"], "gpaw": ["gpaw"], "abinit": ["abinit", "pseudodojo-pbe"]}
# pseudopotential libraries for the other functionals, offered once the code itself is usable
FUNCTIONAL_TOOLS = {"espresso": {"PBEsol": ["sssp-pbesol"], "LDA": ["jth-lda"]}, "abinit": {"LDA": ["pseudodojo-lda"]}}


@router.get("/tools")
def list_tools():
    return {"tools": tools.status(), "not_installable": tools.NOT_INSTALLABLE, "code_tools": CODE_TOOLS,
            "functional_tools": FUNCTIONAL_TOOLS,
            "local": execute.local_executables()}


@router.post("/tools/{name}/install")
def install_tool(name: str):
    try:
        return tools.install(name)
    except tools.ToolError as e:
        raise HTTPException(400, detail=str(e)) from e


@router.get("/tools/{name}/log")
def tool_log(name: str):
    if name not in tools.RECIPES:
        raise HTTPException(404, detail=f"no tool {name!r}")
    return {"name": name, "log": tools.log_tail(name)}


# --- materials and the end-to-end workflow -------------------------------------------

@router.get("/materials")
def search_materials(q: str, limit: int = 20):
    """Materials Project search by formula ("GaAs") or elements ("Ga,As"); stable phases first."""
    try:
        return materials.search(q, limit=limit)
    except materials.SearchError as e:
        raise HTTPException(400, detail=str(e)) from e


class WorkflowBody(BaseModel):
    material: str                     # Materials Project id, e.g. mp-2534
    goal: str | None = None           # plain-language goal for the planning agent (needs an Anthropic key)
    functional: str = "PBE"
    kmesh: tuple[int, int, int] | None = None
    codes: list[str] | None = None
    run: bool = True


@router.post("/workflow")
def start_workflow(body: WorkflowBody):
    job_id = f"dft-{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    try:
        out = workflow.start(jobs_dir() / job_id, body.material.removeprefix("mp:"), body.goal, body.functional,
                             body.kmesh, body.codes, body.run)
    except (*SETUP_ERRORS, materials.SearchError) as e:
        raise HTTPException(400, detail=str(e)) from e
    return {"id": job_id, "plan": out["plan"].model_dump(), "runs": out["runs"], "checks_passed": out["checks_passed"]}


# --- convergence and equation-of-state studies ------------------------------------------

class StudyBody(BaseModel):
    kmesh: tuple[int, int, int] | None = None   # EOS only: your k-mesh for every code (default: converged, else plan)


@router.post("/jobs/{job_id}/studies/{kind}")
def start_study(job_id: str, kind: str, body: StudyBody | None = None):
    if kind not in ("convergence", "eos"):
        raise HTTPException(404, detail="studies: convergence or eos")
    if body and body.kmesh and not all(1 <= k <= 24 for k in body.kmesh):
        raise HTTPException(400, detail="k-mesh entries must be 1..24")
    with job_dir(job_id) as d:
        try:
            return studies.start(d, kind, kmesh=body.kmesh if body else None)
        except execute.ComputeConfigError as e:
            raise HTTPException(400, detail=str(e)) from e


@router.post("/jobs/{job_id}/studies/eos/{code}/save")
def save_eos_structure(job_id: str, code: str):
    """Store this code's equilibrium structure as a reference_structure dataset (usable by the XRD pipeline)."""
    from app.storage.imports import save_computed_structure

    with job_dir(job_id) as d:
        try:
            m = save_computed_structure(d, code)
        except (ValueError, FileNotFoundError) as e:
            raise HTTPException(400, detail=str(e)) from e
    sets.settle_soon(d)  # downloaded only to read the fit: nothing runs, so the working copy goes again
    return {"dataset": m.id, "manifest": m.model_dump(exclude_none=True)}


class RamanBody(BaseModel):
    code: str = "espresso"
    kmesh: tuple[int, int, int] | None = None   # default: converged k-mesh of that code, else the set's


@router.post("/jobs/{job_id}/studies/raman")
def start_raman(job_id: str, body: RamanBody):
    """Γ-point phonons by finite displacements -> Raman/IR-active modes (group theory) and a stick spectrum."""
    if body.code not in raman.FORCE_CODES:
        raise HTTPException(400, detail=f"Raman needs a code that returns forces: {', '.join(raman.FORCE_CODES)}")
    with job_dir(job_id) as d:
        try:
            return raman.start(d, body.code, body.kmesh)
        except execute.ComputeConfigError as e:
            raise HTTPException(400, detail=str(e)) from e


@router.get("/plan-preview")
def plan_preview(material: str, functional: str = "PBE"):
    """The plan the workflow would use for this material, before anything is written (shows the planned k-mesh)."""
    try:
        plan, entry = workflow.plan_for(material.removeprefix("mp:"), None, functional)
    except (materials.SearchError, sources.SourceError) as e:
        raise HTTPException(400, detail=str(e)) from e
    return {"plan": plan.model_dump(), "material": entry}
