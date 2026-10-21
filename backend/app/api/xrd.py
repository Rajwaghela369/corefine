"""XRD inspection: measured scans and simulated patterns, for experimentalists and theorists alike."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dft import materials, sources
from app.storage import datasets
from app.storage.imports import import_materials_project
from app.xrd import analysis, patterns

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


def _structure_meta(structure: str) -> dict:
    """Bulk modulus etc. recorded with a computed structure in Storage (e.g. a DFT equation of state)."""
    if structure.startswith("dataset:"):
        m = datasets.load_manifest(structure.removeprefix("dataset:"))
        return (m.model_extra or {}).get("computed") or {}
    return {}


class CompareBody(BaseModel):
    dataset: str                       # measured pattern in Storage
    file: str | None = None
    structure: str                     # model: dataset:<id>, mp:<id>, cod:<id>
    volume_scale: float = 1.0
    bulk_modulus_GPa: float | None = None
    tol_deg: float = analysis.DEFAULT_TOL_DEG


@router.post("/compare")
def compare(body: CompareBody):
    """Measured peaks vs a model structure: matched reflections, best lattice scale, strain, equivalent pressure."""
    import numpy as np

    try:
        x, y, wl, file, _ = patterns.measured_full(body.dataset, body.file)
        atoms = sources.load(body.structure).atoms
    except (patterns.PatternError, datasets.ManifestError, sources.SourceError) as e:
        raise HTTPException(400, detail=str(e)) from e
    if body.volume_scale != 1.0:
        atoms = atoms.copy()
        atoms.set_cell(atoms.cell[:] * body.volume_scale ** (1 / 3), scale_atoms=True)
    meta = _structure_meta(body.structure)
    b0 = body.bulk_modulus_GPa or meta.get("B0_GPa")
    peaks = analysis.find_measured_peaks(x, y)
    refl = patterns.simulate(atoms, wl, (float(x.min()), float(x.max())), body.structure)["peaks"]
    result = analysis.compare(peaks, refl, wl, body.tol_deg, b0)
    lengths = atoms.cell.lengths()
    result.update(file=file, wavelength_A=wl, measured_peaks=peaks, model=body.structure, model_meta=meta,
                  bulk_modulus_source=("given" if body.bulk_modulus_GPa else "computed structure (EOS)") if b0 else None,
                  model_lattice_A=[float(v) for v in lengths],
                  implied_lattice_A=[float(v * result.get("lattice_scale", 1)) for v in lengths])
    fwhm = float(np.median([p["fwhm"] for p in peaks])) if peaks else 0.1
    grid = np.linspace(float(x.min()), float(x.max()), 3000)
    scaled = [{**r, "two_theta": float(t)} for r, t in zip(refl, [
        float(analysis._two_theta(np.array([r["d_A"] * result.get("lattice_scale", 1)]), wl)[0]) + result.get("zero_shift_deg", 0)
        for r in refl])]
    result["profile"] = {"x": grid.tolist(), "y": analysis.profile(scaled, grid, fwhm).tolist(), "fwhm_deg": fwhm,
                         "note": "fitted model broadened with the median measured FWHM; for visual comparison only"}
    result["model_reflections"] = refl
    return result


class IdentifyBody(BaseModel):
    dataset: str
    file: str | None = None
    formula: str | None = None         # default: the material in the dataset manifest
    max_candidates: int = 12


@router.post("/identify")
def identify(body: IdentifyBody):
    """Which Materials Project polymorph explains the measured peaks best."""
    try:
        x, y, wl, file, m = patterns.measured_full(body.dataset, body.file)
        cands = materials.search(body.formula or m.material, limit=body.max_candidates)
    except (patterns.PatternError, datasets.ManifestError, materials.SearchError) as e:
        raise HTTPException(400, detail=str(e)) from e
    peaks = analysis.find_measured_peaks(x, y)
    refls, info = {}, {}
    for c in cands:
        if c["nsites"] > 60:
            continue
        refls[c["id"]] = patterns.simulate(sources.load(f"mp:{c['id']}").atoms, wl, (float(x.min()), float(x.max())))["peaks"]
        info[c["id"]] = c
    ranked = analysis.identify(peaks, refls, wl)
    for r in ranked:
        r["material"] = info[r["candidate"]]
    return {"file": file, "formula": body.formula or m.material, "n_peaks": len(peaks), "ranked": ranked}
