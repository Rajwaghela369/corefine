"""Datasets: list the NIST standards, read their manifests and upload your own scan."""

import gemmi
import yaml
from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from app.retrieval import index
from app.storage import datasets
from app.storage.objects import get_store

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
