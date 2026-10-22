"""Dataset folders: manifest validation, file upload, tree listing and indexing into the database."""

import fnmatch
from dataclasses import dataclass

import yaml
from pydantic import ValidationError
from sqlalchemy import select

from app.models.contracts import Manifest
from app.models.db import DatasetRow, get_sessionmaker
from app.storage.objects import ObjectStore, get_store
from app.storage.sanitize import sanitize_pdcif

PREFIX = "datasets/"


class ManifestError(ValueError):
    pass


def parse_manifest(text: str | bytes, expected_id: str | None = None) -> Manifest:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ManifestError(f"dataset.yaml is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ManifestError("dataset.yaml must be a mapping")
    try:
        m = Manifest.model_validate(data)
    except ValidationError as e:
        reasons = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        raise ManifestError(f"dataset.yaml is invalid: {reasons}") from e
    if expected_id and m.id != expected_id:
        raise ManifestError(f"manifest id {m.id!r} does not match folder {expected_id!r}")
    return m


def manifest_key(dataset_id: str) -> str:
    return f"{PREFIX}{dataset_id}/dataset.yaml"


def write_manifest(m: Manifest, store: ObjectStore | None = None) -> None:
    store = store or get_store()
    text = yaml.safe_dump(m.model_dump(exclude_none=True), sort_keys=False)
    store.put(manifest_key(m.id), text.encode(), "application/yaml")
    index_manifest(m)


def load_manifest(dataset_id: str, store: ObjectStore | None = None) -> Manifest:
    store = store or get_store()
    key = manifest_key(dataset_id)
    if not store.exists(key):
        raise ManifestError(f"dataset {dataset_id!r} has no dataset.yaml and cannot be used in a run")
    return parse_manifest(store.get(key), dataset_id)


def index_manifest(m: Manifest) -> None:
    with get_sessionmaker()() as db, db.begin():
        row = db.get(DatasetRow, m.id) or DatasetRow(id=m.id)
        row.role, row.technique, row.material, row.format = m.role, m.technique, m.material, m.format
        row.prefix = f"{PREFIX}{m.id}/"
        row.manifest = m.model_dump(exclude_none=True)
        db.add(row)


def dataset_files(m: Manifest, store: ObjectStore | None = None) -> list[str]:
    """Keys of the files the manifest declares (glob patterns relative to the dataset folder)."""
    store = store or get_store()
    base = f"{PREFIX}{m.id}/"
    keys = [k for k in store.list(base) if not k.endswith(("dataset.yaml", "README.md"))]
    rel = [k[len(base):] for k in keys]
    return [base + r for r in rel if any(fnmatch.fnmatch(r, pat) for pat in m.files)]


@dataclass
class TreeNode:
    id: str
    role: str | None
    valid: bool
    problem: str | None
    files: list[str]
    material: str | None = None


def tree(store: ObjectStore | None = None) -> list[TreeNode]:
    store = store or get_store()
    folders: dict[str, list[str]] = {}
    for key in store.list(PREFIX):
        parts = key[len(PREFIX):].split("/", 1)
        if len(parts) == 2:
            folders.setdefault(parts[0], []).append(parts[1])
    nodes = []
    for ds_id, files in sorted(folders.items()):
        try:
            m = load_manifest(ds_id, store)
            nodes.append(TreeNode(ds_id, m.role, True, None, sorted(files), m.material))
        except ManifestError as e:
            nodes.append(TreeNode(ds_id, None, False, str(e), sorted(files)))
    return nodes


def rescan(store: ObjectStore | None = None) -> dict:
    """Re-index every valid manifest in the bucket. Returns indexed ids and rejected folders with reasons."""
    store = store or get_store()
    indexed, rejected = [], {}
    for node in tree(store):
        if node.valid:
            index_manifest(load_manifest(node.id, store))
            indexed.append(node.id)
        else:
            rejected[node.id] = node.problem
    return {"indexed": indexed, "rejected": rejected}


def list_indexed() -> list[DatasetRow]:
    with get_sessionmaker()() as db:
        return list(db.scalars(select(DatasetRow).order_by(DatasetRow.id)))


def staged_inputs(dataset_ids: list[str], store: ObjectStore | None = None) -> dict[str, bytes]:
    """Files to place under /work/inputs for a run: {relative path: bytes}.

    Each dataset gets <id>/dataset.yaml (without reference_values) and its declared files. Measured
    powder CIFs are sanitized so the certified answer and NIST's own fit never reach the sandbox.
    """
    store = store or get_store()
    out: dict[str, bytes] = {}
    for ds_id in dataset_ids:
        m = load_manifest(ds_id, store)
        out[f"{ds_id}/dataset.yaml"] = yaml.safe_dump(m.for_agents(), sort_keys=False).encode()
        keys = dataset_files(m, store)
        if not keys:
            raise ManifestError(f"dataset {ds_id!r}: no files match {m.files}")
        for key in keys:
            data = store.get(key)
            if m.format == "pdcif" and key.endswith(".cif"):
                data = sanitize_pdcif(data.decode("utf-8", errors="replace"))[0].encode()
            out[key[len(PREFIX):]] = data
    return out
