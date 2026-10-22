"""Raman (and IR) activity of Γ-point phonons from finite displacements, for any code that returns forces.

phonopy displaces the atoms of the unit cell (Γ frequencies need no supercell), each displaced cell is an
ordinary checked input set run locally, and phonopy builds the force constants. Activity comes from group
theory alone, using the characters phonopy gives for each mode under the point-group operations R:
  IR active     n = (1/|G|) Σ_R conj(χ_mode(R)) χ_V(R)                     > 0
  Raman active  n = (1/|G|) Σ_R conj(χ_mode(R)) [χ_V(R)^2 + χ_V(R^2)] / 2   > 0
with χ_V(R) = trace(R) (the vector representation). This gives which modes appear and where; Raman
intensities would need derivatives of the dielectric tensor and are not computed. Polar crystals: the
LO-TO splitting needs Born effective charges, also not computed, so the frequencies are TO-like.
"""

import json
import threading
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.io import write as ase_write
from phonopy import Phonopy
from phonopy.structure.atoms import PhonopyAtoms

from app.dft import execute, pipeline, sources, structure
from app.dft.codes import REGISTRY
from app.dft.request import CalcRequest

THZ_TO_CM1 = 33.35640951981521
DISPLACEMENT_A = 0.01
FORCE_CODES = ("espresso", "gpaw")
_lock = threading.Lock()


def activity(characters: np.ndarray, rotations: np.ndarray) -> tuple[bool, bool]:
    rots = np.array(rotations, dtype=float)
    chi_v = np.array([np.trace(r) for r in rots])
    chi_v2 = np.array([np.trace(r @ r) for r in rots])
    g = len(rots)
    ir = np.real(np.sum(np.conj(characters) * chi_v)) / g
    raman = np.real(np.sum(np.conj(characters) * (chi_v ** 2 + chi_v2) / 2)) / g
    return bool(raman > 0.5), bool(ir > 0.5)


def gamma_modes(ph: Phonopy) -> list[dict]:
    ir = ph.run_irreps([0, 0, 0])
    labels = getattr(ir, "_ir_labels", None)
    freqs = ir.frequencies
    out = []
    for i, bands in enumerate(ir.band_indices):
        f_thz = float(np.mean([freqs[b] for b in bands]))
        acoustic = 0 in bands
        raman, infrared = activity(ir.characters[i], ir.conventional_rotations)
        out.append({"frequency_cm1": f_thz * THZ_TO_CM1, "frequency_THz": f_thz, "degeneracy": len(bands),
                    "label": labels[i] if labels else None, "acoustic": acoustic,
                    "raman_active": raman and not acoustic, "ir_active": infrared and not acoustic})
    return out


def spectrum(modes: list[dict], fwhm_cm1: float = 5.0, lo: float = 0.0, hi: float | None = None, n: int = 2000) -> dict:
    """Lorentzian sticks of equal height for Raman-active modes (positions only; no intensities)."""
    active = [m for m in modes if m["raman_active"]]
    hi = hi or max([m["frequency_cm1"] for m in active] + [100]) * 1.3
    x = np.linspace(lo, hi, n)
    y = np.zeros_like(x)
    g = fwhm_cm1 / 2
    for m in active:
        y += m["degeneracy"] * g ** 2 / ((x - m["frequency_cm1"]) ** 2 + g ** 2)
    return {"x": x.tolist(), "y": y.tolist(), "fwhm_cm1": fwhm_cm1, "note": "positions only, equal intensity per degenerate mode"}


def _save(d: Path, **update) -> dict:
    with _lock:
        p = d / "study.json"
        st = json.loads(p.read_text()) if p.is_file() else {}
        st.update(update)
        p.write_text(json.dumps(st, indent=2, default=str))
        return st


def run(set_dir: Path, code: str, kmesh: tuple[int, int, int] | None = None) -> dict:
    if code not in FORCE_CODES:
        raise ValueError(f"Raman needs forces; supported for {FORCE_CODES}")
    prov = json.loads((set_dir / "provenance.json").read_text())
    base = CalcRequest.model_validate(prov["request"])
    conv = (json.loads((set_dir / "studies" / "convergence" / "study.json").read_text()).get("codes", {}).get(code, {})
            if (set_dir / "studies" / "convergence" / "study.json").is_file() else {})
    k = tuple(kmesh) if kmesh else tuple(conv.get("converged_kmesh") or base.kmesh)
    basis = conv.get("converged_basis_scale") or 1.0
    d = set_dir / "studies" / "raman" / code
    d.mkdir(parents=True, exist_ok=True)
    cell = structure.standard_primitive(sources.load(base.structure).atoms)
    unit = PhonopyAtoms(symbols=cell.symbols, cell=cell.lattice, scaled_positions=cell.frac)
    ph = Phonopy(unit, supercell_matrix=np.eye(3, dtype=int), primitive_matrix=None)
    ph.generate_displacements(distance=DISPLACEMENT_A)
    cells = ph.supercells_with_displacements
    _save(d, status="running", code=code, kmesh=list(k), basis_scale=basis, displacement_A=DISPLACEMENT_A,
          n_displacements=len(cells), message="")
    forces = []
    for i, sc in enumerate(cells):
        _save(d, message=f"displacement {i + 1} of {len(cells)}")
        pd = d / f"disp_{i:03d}"
        pd.mkdir(exist_ok=True)
        src = pd / "displaced.json"
        ase_write(src, Atoms(symbols=sc.symbols, cell=sc.cell, scaled_positions=sc.scaled_positions, pbc=True), format="json")
        req = base.model_copy(update={"structure": str(src), "codes": [code], "kmesh": k, "basis_scale": basis,
                                      "keep_cell": True, "forces": True, "volume_scale": 1.0})
        prep = pipeline.prepare(req, pd)
        if not prep["checks"]["passed"]:
            return _save(d, status="failed", message=f"displacement {i}: input checks failed")
        execute.start(pd, code, "local", wait=True)
        st = execute.read_state(pd, code) or {}
        f = REGISTRY[code].parse_forces(pd / code)
        if st.get("status") != "completed" or f is None:
            return _save(d, status="failed", message=f"displacement {i}: {st.get('message') or 'no forces'}")
        forces.append(np.asarray(f) - np.mean(f, axis=0))  # remove residual drift
    ph.forces = forces
    ph.produce_force_constants()
    ph.symmetrize_force_constants()
    modes = gamma_modes(ph)
    return _save(d, status="done", message="", modes=modes, spectrum=spectrum(modes),
                 point_group=getattr(ph.run_irreps([0, 0, 0]), "_pointgroup_symbol", None),
                 notes=["Raman/IR activity from group theory; intensities not computed",
                        "polar crystals: no LO-TO splitting (Born charges not computed)"])


def read(set_dir: Path) -> dict:
    out = {}
    for p in sorted((set_dir / "studies" / "raman").glob("*/study.json")):
        out[p.parent.name] = json.loads(p.read_text())
    return out


def start(set_dir: Path, code: str, kmesh: tuple | None = None, wait: bool = False) -> dict:
    d = set_dir / "studies" / "raman" / code
    d.mkdir(parents=True, exist_ok=True)
    if (d / "study.json").is_file() and json.loads((d / "study.json").read_text()).get("status") == "running":
        raise execute.ComputeConfigError(f"a Raman study for {code} is already running")
    _save(d, status="queued", code=code)

    def go():
        try:
            run(set_dir, code, kmesh)
        except Exception as e:  # noqa: BLE001
            _save(d, status="failed", message=str(e)[:1500])

    t = threading.Thread(target=go, daemon=True)
    t.start()
    if wait:
        t.join()
    return json.loads((d / "study.json").read_text())
