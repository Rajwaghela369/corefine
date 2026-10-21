"""Sanity checks, the same for every code.

The reference is the standardized primitive cell from the source. Each adapter reads its own input
back the way its code will (not what we meant to write), converted to Å; spglib then analyses it.
A units slip (Å vs bohr), a wrong origin or a dropped atom shows up as a failed check. Adapters add
code-specific checks (schema validation, the code's own symmetry and overlap analysis).
"""

import numpy as np
from ase import Atoms

from app.dft.codes import ReadBack
from app.dft.request import CalcRequest
from app.dft.structure import Cell, spacegroup_of

REL_TOL = 1e-6


def metrics(atoms: Atoms) -> dict:
    number, symbol = spacegroup_of(atoms)
    d = atoms.get_all_distances(mic=True)
    return {"natoms": len(atoms), "formula": atoms.get_chemical_formula(mode="metal"),
            "spacegroup_number": number, "spacegroup": symbol,
            "volume_per_atom_A3": float(atoms.get_volume() / len(atoms)),
            "nearest_neighbour_A": float(np.min(d[d > 1e-6])) if len(atoms) > 1 else None}


def _check(name: str, ok: bool | None, detail: str, code: str | None = None) -> dict:
    """ok None = not done (e.g. licensed files absent); it is shown but does not fail the set."""
    return {"check": name, "ok": None if ok is None else bool(ok), "detail": detail, "code": code}


def _structure_checks(label: str, got: dict, ref: dict) -> list[dict]:
    out = [
        _check(f"{label}: atom count and formula", got["natoms"] == ref["natoms"] and got["formula"] == ref["formula"],
               f"{got['formula']} ({got['natoms']} atoms) vs reference {ref['formula']} ({ref['natoms']})", label),
        _check(f"{label}: space group", got["spacegroup_number"] == ref["spacegroup_number"],
               f"{got['spacegroup']} ({got['spacegroup_number']}) vs reference {ref['spacegroup']} ({ref['spacegroup_number']})", label),
        _check(f"{label}: volume per atom", abs(got["volume_per_atom_A3"] / ref["volume_per_atom_A3"] - 1) < REL_TOL,
               f"{got['volume_per_atom_A3']:.6f} Å³ vs reference {ref['volume_per_atom_A3']:.6f} Å³", label),
    ]
    if ref["nearest_neighbour_A"]:
        out.append(_check(f"{label}: nearest-neighbour distance",
                          abs(got["nearest_neighbour_A"] / ref["nearest_neighbour_A"] - 1) < REL_TOL,
                          f"{got['nearest_neighbour_A']:.6f} Å vs reference {ref['nearest_neighbour_A']:.6f} Å", label))
    return out


def run_checks(cell: Cell, req: CalcRequest, declared_spacegroup: str | None, read_backs: dict[str, ReadBack]) -> dict:
    ref = metrics(cell.atoms)
    results = []
    if declared_spacegroup:
        results.append(_check("source: declared space group reproduced by spglib",
                              str(ref["spacegroup_number"]) == str(declared_spacegroup),
                              f"source says {declared_spacegroup}, spglib finds {ref['spacegroup_number']}", "source"))
    codes = {}
    for name, rb in read_backs.items():
        m = metrics(rb.atoms)
        codes[name] = m
        results += _structure_checks(name, m, ref)
        results.append(_check(f"{name}: k-mesh", rb.kmesh == list(req.kmesh), f"{rb.kmesh} vs requested {list(req.kmesh)}", name))
        results.append(_check(f"{name}: functional {req.functional}", rb.functional_ok, rb.functional_detail, name))
        results += [_check(f"{name}: {c['check']}", c["ok"], c["detail"], name) for c in rb.extra_checks]
    names = list(codes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ma, mb = codes[a], codes[b]
            same = (ma["spacegroup_number"] == mb["spacegroup_number"] and ma["natoms"] == mb["natoms"]
                    and abs(ma["volume_per_atom_A3"] / mb["volume_per_atom_A3"] - 1) < REL_TOL)
            results.append(_check(f"{a} vs {b}: same crystal", same,
                                  f"V/atom {ma['volume_per_atom_A3']:.6f} vs {mb['volume_per_atom_A3']:.6f} Å³", "cross-code"))
    return {"passed": all(r["ok"] is not False for r in results), "reference": ref, "codes": codes, "results": results}
