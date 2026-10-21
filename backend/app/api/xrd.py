"""XRD inspection: measured scans and simulated patterns, for experimentalists and theorists alike."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dft import sources
from app.storage import datasets
from app.storage.imports import import_materials_project
from app.xrd import patterns

router = APIRouter(prefix="/xrd", tags=["xrd"])


@router.get("/measured/{dataset_id}")
def measured(dataset_id: str, file: str | None = None, lo: float | None = None, hi: float | None = None):
    try:
        return patterns.measured(dataset_id, file, lo, hi)
    except (patterns.PatternError, datasets.ManifestError) as e:
        raise HTTPException(400, detail=str(e)) from e


class SimulateBody(BaseModel):
    structure: str                    # dataset:<id>, mp:<id>, cod:<id> or a .cif path
    wavelength_A: float
    two_theta_min: float = 10
    two_theta_max: float = 150
    volume_scale: float = 1.0         # e.g. a DFT V0 / source volume, to see where a computed lattice puts the peaks


@router.post("/simulate")
def simulate(body: SimulateBody):
    if not (0.1 < body.wavelength_A < 5):
        raise HTTPException(400, detail="wavelength must be in Å (e.g. 1.5405929 for Cu Kα1)")
    try:
        atoms = sources.load(body.structure).atoms
    except sources.SourceError as e:
        raise HTTPException(400, detail=str(e)) from e
    if body.volume_scale != 1.0:
        atoms = atoms.copy()
        atoms.set_cell(atoms.cell[:] * body.volume_scale ** (1 / 3), scale_atoms=True)
    return patterns.simulate(atoms, body.wavelength_A, (body.two_theta_min, body.two_theta_max), body.structure)


class ImportBody(BaseModel):
    mp_id: str


@router.post("/import/materials-project")
def import_mp(body: ImportBody):
    """Materials Project structure -> Storage reference_structure dataset."""
    try:
        m = import_materials_project(body.mp_id.removeprefix("mp:"))
    except (sources.SourceError, ValueError) as e:
        raise HTTPException(400, detail=str(e)) from e
    return {"dataset": m.id, "manifest": m.model_dump(exclude_none=True)}
