"""Datasets: list the NIST standards, read their manifests and upload your own scan."""

import gemmi
import yaml
from fastapi import APIRouter, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.retrieval import index
from app.storage import datasets
from app.storage.objects import get_store
from app.xrd import ingest

router = APIRouter(prefix="/datasets", tags=["datasets"])

MAX_UPLOAD_BYTES = 100 * 1024 * 1024


class CreateDataset(BaseModel):
    manifest: dict
    readme: str | None = None


def _bad(e: Exception, code: int = 400):
    raise HTTPException(code, detail=str(e)) from e


def _index_docs(m) -> None:
    store = get_store()
    key = f"datasets/{m.id}/README.md"
    readme = store.get(key).decode() if store.exists(key) else None
    try:
        index.index_dataset(m.model_dump(exclude_none=True), readme)
    except Exception:
        pass  # search is a convenience; never block an upload on it


@router.get("")
def list_datasets():
    return [n.__dict__ for n in datasets.tree()]


@router.post("/inspect")
async def inspect_file(file: UploadFile):
    """What an uploaded CIF says about itself (radiation, wavelength, formula ...), to pre-fill the Add-dataset form.
    Nothing is stored."""
    from app.storage import inspect

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail="file larger than 100 MB")
    if not (file.filename or "").lower().endswith(".cif"):
        return {"format": None, "role": None, "found": {}}
    try:
        return inspect.inspect_cif(data.decode(errors="replace"))
    except (ValueError, RuntimeError) as e:
        _bad(ValueError(f"{file.filename} is not readable CIF: {e}"))


@router.post("")
def create_dataset(body: CreateDataset):
    try:
        m = datasets.parse_manifest(yaml.safe_dump(body.manifest))
    except datasets.ManifestError as e:
        _bad(e)
    store = get_store()
    if body.readme:
        store.put(f"datasets/{m.id}/README.md", body.readme.encode(), "text/markdown")
    datasets.write_manifest(m, store)
    _index_docs(m)
    return {"id": m.id, "manifest": m.model_dump(exclude_none=True)}


@router.put("/{dataset_id}/manifest")
def update_manifest(dataset_id: str, manifest: dict):
    try:
        m = datasets.parse_manifest(yaml.safe_dump(manifest), expected_id=dataset_id)
    except datasets.ManifestError as e:
        _bad(e)
    datasets.write_manifest(m)
    _index_docs(m)
    return {"id": m.id, "manifest": m.model_dump(exclude_none=True)}


@router.get("/{dataset_id}/manifest")
def get_manifest(dataset_id: str):
    try:
        return datasets.load_manifest(dataset_id).model_dump(exclude_none=True)
    except datasets.ManifestError as e:
        _bad(e, 404)


def _validate_file(name: str, data: bytes, fmt: str) -> None:
    if fmt in ("pdcif", "cif") and name.lower().endswith(".cif"):
        try:
            doc = gemmi.cif.read_string(data.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, ValueError, RuntimeError) as e:
            raise HTTPException(400, detail=f"{name} is not a readable CIF: {e}") from e
        if fmt == "pdcif" and not any(b.find_values("_pd_proc_2theta_corrected") or b.find_values("_pd_meas_2theta_scan")
                                      for b in doc):
            raise HTTPException(400, detail=f"{name}: no 2θ loop (_pd_proc_2theta_corrected or _pd_meas_2theta_scan)"
                                            " found; this does not look like a powder pattern")


async def _read_scan(file: UploadFile) -> tuple[str, str, ingest.ParsedScan]:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail=f"{file.filename} exceeds {MAX_UPLOAD_BYTES} bytes")
    name = (file.filename or "scan.xy").rsplit("/", 1)[-1]
    text = data.decode("utf-8", errors="replace")
    try:
        return name, text, ingest.parse_scan(text)
    except ingest.ScanError as e:
        _bad(e)


@router.post("/scan/preview")
async def preview_scan(file: UploadFile):
    """Read a text scan (.xy, .xye, .csv, .dat) and say what was found, without saving anything."""
    name, _, scan = await _read_scan(file)
    existing = {n.id for n in datasets.tree()}
    base = ingest.slug(name)
    return {"filename": name, "suggested_id": base if base not in existing else f"{base}-2", **scan.summary()}


@router.post("/scan/import")
async def import_scan(file: UploadFile, material: str = Form(""), wavelength_A: float | None = Form(None),
                      radiation: str = Form(""), ka2_present: bool | None = Form(None), dataset_id: str = Form("")):
    """Turn an uploaded text scan into a measured-pattern dataset (powder CIF + manifest) ready for every analysis."""
    name, text, scan = await _read_scan(file)
    wl, source = wavelength_A, "entered by the person who uploaded the file"
    if wl is None:
        wl, source = scan.wavelength_A, f"header of {name}"
    if wl is None or not 0.2 < wl < 5:
        raise HTTPException(400, detail="a wavelength in ångström is needed (0.2 to 5); the file header has none. "
                                        "Ask whoever measured it, or read it from the instrument settings")
    ds_id = dataset_id.strip() or ingest.slug(name)
    if any(n.id == ds_id for n in datasets.tree()):
        raise HTTPException(409, detail=f"a dataset called {ds_id!r} already exists; choose another id")
    rad = radiation.strip() or (f"{scan.anode} Kα" if scan.anode else "X-ray")
    try:
        manifest = ingest.manifest_for(ds_id, scan, material.strip(), wl, source, rad, ka2_present, name)
        m = datasets.parse_manifest(yaml.safe_dump(manifest), expected_id=ds_id)
    except (datasets.ManifestError, ValueError) as e:
        _bad(e)
    store = get_store()
    cif_name = ingest.slug(name) + ".cif"
    store.put(f"datasets/{ds_id}/raw/{cif_name}", ingest.to_pdcif(scan, ds_id, wl, rad, name).encode(), "chemical/x-cif")
    store.put(f"datasets/{ds_id}/original/{name}", text.encode(), "text/plain")
    store.put(f"datasets/{ds_id}/README.md", (f"# {ds_id}\n\nUploaded scan `{name}` ({scan.x.size} points, "
              f"2θ {scan.x.min():g}–{scan.x.max():g}°). Wavelength {wl:g} Å from {source}. "
              "No certified reference value; 2θ zero correction unknown.\n").encode(), "text/markdown")
    datasets.write_manifest(m, store)
    _index_docs(m)
    return {"id": ds_id, "file": cif_name, "manifest": m.model_dump(exclude_none=True), "notes": scan.notes}


@router.post("/{dataset_id}/files")
async def upload_files(dataset_id: str, files: list[UploadFile]):
    """Upload into raw/. The folder must already have a valid manifest; files are validated by format."""
    try:
        m = datasets.load_manifest(dataset_id)
    except datasets.ManifestError as e:
        _bad(e)
    store, saved = get_store(), []
    for f in files:
        data = await f.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, detail=f"{f.filename} exceeds {MAX_UPLOAD_BYTES} bytes")
        name = (f.filename or "file").rsplit("/", 1)[-1]
        _validate_file(name, data, m.format)
        key = f"datasets/{dataset_id}/raw/{name}"
        store.put(key, data)
        saved.append(key)
    return {"saved": saved}


@router.get("/{dataset_id}/upload-url")
def presigned_upload(dataset_id: str, filename: str):
    """Presigned direct-to-bucket upload (S3 only). Returns null url in local mode; use POST /files."""
    try:
        datasets.load_manifest(dataset_id)
    except datasets.ManifestError as e:
        _bad(e)
    key = f"datasets/{dataset_id}/raw/{filename.rsplit('/', 1)[-1]}"
    return {"key": key, "url": get_store().presign_put(key)}


@router.post("/rescan")
def rescan():
    result = datasets.rescan()
    for ds_id in result["indexed"]:
        _index_docs(datasets.load_manifest(ds_id))
    return result
