"""Convergence and equation-of-state studies across codes. Each point is an ordinary, fully checked input set.

convergence  for each code: k-mesh series (k-point spacings), then basis series at the converged mesh.
             A setting is converged when its total energy per atom is within TOL_MEV of the most accurate
             point of the series (CoRefine's criterion, stated in the result).
eos          7 volumes, 94 % ... 106 % of the reference volume (the Delta-test protocol), at the converged
             settings; Birch-Murnaghan fit per code -> V0, B0, B'; Delta gauge between every pair of codes:
             Delta = sqrt( integral (E1 - E2)^2 dV / (0.12 V0) ), each fit shifted so its minimum is zero,
             over 0.94..1.06 of the mean V0 (Lejaeghere et al., Science 351, aad3000 (2016)); computed with
             ase.utils.deltacodesdft. For elemental crystals in the Delta-test phase, WIEN2k is added as reference.
Points run one after another on the local target. All numbers come from the codes' parsed output files.
"""

import json
import threading
from pathlib import Path

from ase.eos import EquationOfState
from ase.units import GPa

from app.dft import execute, pipeline, planner, sources, structure
from app.dft.request import CalcRequest

TOL_MEV = 1.0
KSPACINGS = (0.5, 0.4, 0.3, 0.25, 0.2, 0.15)  # Å⁻¹
BASIS_SCALES = (0.8, 1.0, 1.25, 1.5, 2.0)
EOS_SCALES = (0.94, 0.96, 0.98, 1.00, 1.02, 1.04, 1.06)
_lock = threading.Lock()
BASIS_NOTES = {
    "espresso": "ecutwfc and ecutrho, x scale",
    "exciting": "rgkmax, x sqrt(scale)",
    "questaal": "gmax (interstitial density mesh), x sqrt(scale); does not test LMTO basis completeness",
    "vasp": "ENCUT, x scale of the POTCAR ENMAX",
    "gpaw": "PW ecut, x scale of 340 eV",
    "abinit": "ecut, x scale of the PseudoDojo normal hint",
}


def study_dir(set_dir: Path, kind: str) -> Path:
    d = set_dir / "studies" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state(d: Path) -> dict:
    p = d / "study.json"
    return json.loads(p.read_text()) if p.is_file() else {}


def _save(d: Path, **update) -> dict:
    with _lock:
        st = _state(d)
        st.update(update)
        (d / "study.json").write_text(json.dumps(st, indent=2, default=str))
        return st


def read(set_dir: Path) -> dict:
    out = {}
    for kind in ("convergence", "eos"):
        p = set_dir / "studies" / kind / "study.json"
        if p.is_file():
            out[kind] = json.loads(p.read_text())
    return out


def _base_request(set_dir: Path) -> CalcRequest:
    prov = json.loads((set_dir / "provenance.json").read_text())
    return CalcRequest.model_validate(prov["request"])


def _runnable(req: CalcRequest) -> list[str]:
    local = (execute.load_targets().get("local") or {}).get("codes") or {}
    return [c for c in req.codes if c in local]


def _point(point_dir: Path, req: CalcRequest, code: str) -> dict:
    """Prepare (with checks) and run one code at one setting; returns energy per atom or the failure."""
    r = req.model_copy(update={"codes": [code]})
    prep = pipeline.prepare(r, point_dir)
    if not prep["checks"]["passed"]:
        return {"ok": False, "error": "input checks failed"}
    execute.start(point_dir, code, "local", wait=True)
    st = execute.read_state(point_dir, code) or {}
    res = st.get("results") or {}
    natoms = prep["provenance"]["cell"]["natoms"]
    if st.get("status") != "completed" or not res.get("converged") or res.get("total_energy_eV") is None:
        return {"ok": False, "error": st.get("message") or "run failed", "status": st.get("status")}
    return {"ok": True, "e_per_atom_eV": res["total_energy_eV"] / natoms, "volume_per_atom_A3":
            prep["provenance"]["cell"]["volume_per_atom_A3"], "scf_iterations": res.get("scf_iterations"),
            "healed": (st.get("healed") or {}).get("change")}


def converged_index(energies: list[float | None], tol_mev: float = TOL_MEV) -> int | None:
    """First setting whose energy is within tol of the most accurate (last) point and stays within tol after it.
    The last point alone proves nothing, so it never counts: None means 'not converged within this series'."""
    if len(energies) < 2 or energies[-1] is None:
        return None
    ref = energies[-1]
    for i in range(len(energies) - 1):
        if all(e is not None and abs(e - ref) * 1000 <= tol_mev for e in energies[i:]):
            return i
    return None


# --- convergence -----------------------------------------------------------------

def convergence(set_dir: Path, codes: list[str] | None = None) -> dict:
    base = _base_request(set_dir)
    codes = codes or _runnable(base)
    d = study_dir(set_dir, "convergence")
    cell = structure.standard_primitive(sources.load(base.structure).atoms)
    meshes = list(dict.fromkeys(planner.kmesh_for(cell.lattice, sp) for sp in KSPACINGS))
    _save(d, status="running", tol_meV_per_atom=TOL_MEV, criterion=f"within {TOL_MEV} meV/atom of the most accurate point",
          kmeshes=[list(m) for m in meshes], basis_scales=list(BASIS_SCALES), codes={})
    for code in codes:
        kpts = []
        for m in meshes:
            _save(d, message=f"{code}: k-mesh {m}")
            pt = _point(d / code / f"k_{'x'.join(map(str, m))}", base.model_copy(update={"kmesh": m}), code)
            kpts.append({"kmesh": list(m), **pt})
        ik = converged_index([p.get("e_per_atom_eV") for p in kpts])
        k_conv = tuple(kpts[ik]["kmesh"]) if ik is not None else tuple(meshes[-1])  # densest if not demonstrated
        basis = []
        for bs in BASIS_SCALES:
            _save(d, message=f"{code}: basis x{bs}")
            pt = _point(d / code / f"b_{bs}", base.model_copy(update={"kmesh": k_conv, "basis_scale": bs}), code)
            basis.append({"basis_scale": bs, **pt})
        ib = converged_index([p.get("e_per_atom_eV") for p in basis])
        st = _state(d)
        st["codes"][code] = {"kpoints": kpts, "basis": basis, "converged_kmesh": list(k_conv) if ik is not None else None,
                             "converged_basis_scale": BASIS_SCALES[ib] if ib is not None else None,
                             "basis_parameter": BASIS_NOTES.get(code, "energy cutoff")}
        _save(d, codes=st["codes"])
    return _save(d, status="done", message="")


# --- equation of state --------------------------------------------------------------

def fit_bm(volumes: list[float], energies: list[float]) -> dict:
    eos = EquationOfState(volumes, energies, eos="birchmurnaghan")
    v0, e0, b = eos.fit()
    bp = float(eos.eos_parameters[2]) if hasattr(eos, "eos_parameters") else None
    # Birch-Murnaghan E(V) with the fitted parameters, for the Delta integral
    return {"V0_A3_per_atom": float(v0), "E0_eV_per_atom": float(e0), "B0_GPa": float(b / GPa), "B0_prime": bp}


def delta_gauge(f1: dict, f2: dict) -> float:
    """Delta (meV/atom) between two Birch-Murnaghan fits, via ASE's implementation of the Delta-test formula."""
    from ase.utils.deltacodesdft import delta

    return float(delta(f1["V0_A3_per_atom"], f1["B0_GPa"] * GPa, f1["B0_prime"],
                       f2["V0_A3_per_atom"], f2["B0_GPa"] * GPa, f2["B0_prime"]) * 1000)


def wien2k_reference(cell) -> dict | None:
    """All-electron WIEN2k EOS from the Delta project (ASE's dcdft collection), for elemental crystals in the same phase."""
    from ase.collections import dcdft

    symbols = set(cell.symbols)
    if len(symbols) != 1:
        return None
    el = symbols.pop()
    if el not in dcdft.data or "wien2k_volume" not in dcdft.data[el]:
        return None
    if structure.spacegroup_of(dcdft[el])[0] != cell.spacegroup_number:
        return None
    r = dcdft.data[el]
    return {"source": "WIEN2k, Delta project (Lejaeghere et al. 2016) via ase.collections.dcdft",
            "V0_A3_per_atom": r["wien2k_volume"], "B0_GPa": r["wien2k_B"], "B0_prime": r["wien2k_Bp"]}


def cubic_a0(cell, v0_per_atom: float) -> float | None:
    """Conventional cubic lattice constant at V0 (space groups 195-230), to compare with an XRD refinement."""
    import spglib

    if not 195 <= cell.spacegroup_number <= 230:
        return None
    conv = spglib.standardize_cell((cell.lattice, cell.frac, cell.atoms.numbers), to_primitive=False, symprec=1e-3)
    return float((v0_per_atom * len(conv[2])) ** (1 / 3))


def eos(set_dir: Path, codes: list[str] | None = None, use_converged: bool = True, kmesh: tuple | None = None) -> dict:
    base = _base_request(set_dir)
    codes = codes or _runnable(base)
    conv = read(set_dir).get("convergence", {}).get("codes", {}) if use_converged else {}
    d = study_dir(set_dir, "eos")
    _save(d, status="running", scales=list(EOS_SCALES), protocol="Delta-test volumes 94-106 %, Birch-Murnaghan fit",
          codes={}, delta_meV_per_atom={})
    for code in codes:
        c = conv.get(code) or {}
        k = tuple(kmesh) if kmesh else (tuple(c["converged_kmesh"]) if c.get("converged_kmesh") else None)
        req = base.model_copy(update={"sphere_ref_scale": min(EOS_SCALES),
                                      **({"kmesh": k} if k else {}),
                                      **({"basis_scale": c["converged_basis_scale"]} if c.get("converged_basis_scale") else {})})
        pts = []
        for sc in EOS_SCALES:
            _save(d, message=f"{code}: volume x{sc}")
            pts.append({"scale": sc, **_point(d / code / f"v_{sc:.2f}", req.model_copy(update={"volume_scale": sc}), code)})
        good = [p for p in pts if p["ok"]]
        entry = {"points": pts, "settings": {"kmesh": list(req.kmesh), "basis_scale": req.basis_scale,
                                             "from_convergence": bool(c), "kmesh_source": "yours" if kmesh else
                                             ("converged" if c.get("converged_kmesh") else "plan")}}
        if len(good) >= 5:
            fit = fit_bm([p["volume_per_atom_A3"] for p in good], [p["e_per_atom_eV"] for p in good])
            ref_v = json.loads((set_dir / "provenance.json").read_text())["cell"]["volume_per_atom_A3"]
            fit["V0_over_source"] = fit["V0_A3_per_atom"] / ref_v
            entry["fit"] = fit
        else:
            entry["error"] = f"only {len(good)} of {len(pts)} volumes converged; no fit"
        st = _state(d)
        st["codes"][code] = entry
        _save(d, codes=st["codes"])
    st = _state(d)
    cell = structure.standard_primitive(sources.load(base.structure).atoms)
    fits = {c: e["fit"] for c, e in st["codes"].items() if "fit" in e}
    for c, f in fits.items():
        f["a0_conventional_A"] = cubic_a0(cell, f["V0_A3_per_atom"])
        st["codes"][c]["fit"] = f
    ref = wien2k_reference(cell) if base.functional == "PBE" else None
    if ref:
        ref["a0_conventional_A"] = cubic_a0(cell, ref["V0_A3_per_atom"])
        fits_all = {**fits, "wien2k": ref}
    else:
        fits_all = fits
    names = sorted(fits_all)
    delta = {f"{a}|{b}": delta_gauge(fits_all[a], fits_all[b]) for i, a in enumerate(names) for b in names[i + 1:]}
    return _save(d, status="done", message="", codes=st["codes"], delta_meV_per_atom=delta, reference=ref)


def start(set_dir: Path, kind: str, wait: bool = False, kmesh: tuple | None = None) -> dict:
    fn = {"convergence": convergence, "eos": lambda d: eos(d, kmesh=kmesh)}[kind]
    d = study_dir(set_dir, kind)
    if _state(d).get("status") == "running":
        raise execute.ComputeConfigError(f"a {kind} study is already running for this set")
    _save(d, status="queued", message="")

    def go():
        try:
            fn(set_dir)
        except Exception as e:  # noqa: BLE001 — recorded for the UI
            _save(d, status="failed", message=str(e)[:1500])

    t = threading.Thread(target=go, daemon=True)
    t.start()
    if wait:
        t.join()
    return _state(d)
