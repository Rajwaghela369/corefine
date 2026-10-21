"""Sanity checks: read every generated input back the way each code will, and compare.

The reference is the standardized primitive cell from the source. Each code's input is re-parsed
(not taken from what we meant to write), converted to Å and analysed with spglib, so a units slip
(Å vs bohr), a wrong origin or a dropped atom shows up as a failed check.
"""

import numpy as np
from ase import Atoms
from ase.units import Bohr

from app.dft.request import EXCITING_XC, QUESTAAL_LIBXC_IDS, CalcRequest
from app.dft.structure import Cell, spacegroup_of

REL_TOL = 1e-6


def _metrics(atoms: Atoms) -> dict:
    number, symbol = spacegroup_of(atoms)
    d = atoms.get_all_distances(mic=True)
    return {"natoms": len(atoms), "formula": atoms.get_chemical_formula(mode="metal"),
            "spacegroup_number": number, "spacegroup": symbol,
            "volume_per_atom_A3": float(atoms.get_volume() / len(atoms)),
            "nearest_neighbour_A": float(np.min(d[d > 1e-6])) if len(atoms) > 1 else None}


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"check": name, "ok": bool(ok), "detail": detail}


def _compare(code: str, got: dict, ref: dict) -> list[dict]:
    out = [
        _check(f"{code}: atom count and formula", got["natoms"] == ref["natoms"] and got["formula"] == ref["formula"],
               f"{got['formula']} ({got['natoms']} atoms) vs reference {ref['formula']} ({ref['natoms']})"),
        _check(f"{code}: space group", got["spacegroup_number"] == ref["spacegroup_number"],
               f"{got['spacegroup']} ({got['spacegroup_number']}) vs reference {ref['spacegroup']} ({ref['spacegroup_number']})"),
        _check(f"{code}: volume per atom", abs(got["volume_per_atom_A3"] / ref["volume_per_atom_A3"] - 1) < REL_TOL,
               f"{got['volume_per_atom_A3']:.6f} Å³ vs reference {ref['volume_per_atom_A3']:.6f} Å³"),
    ]
    if ref["nearest_neighbour_A"]:
        out.append(_check(f"{code}: nearest-neighbour distance",
                          abs(got["nearest_neighbour_A"] / ref["nearest_neighbour_A"] - 1) < REL_TOL,
                          f"{got['nearest_neighbour_A']:.6f} Å vs reference {ref['nearest_neighbour_A']:.6f} Å"))
    return out


def run_checks(cell: Cell, req: CalcRequest, declared_spacegroup: str | None,
               exciting_back: dict | None, exciting_schema: dict | None, questaal_back: dict | None) -> dict:
    ref = _metrics(cell.atoms)
    results = []
    if declared_spacegroup:
        results.append(_check("source: declared space group reproduced by spglib",
                              str(ref["spacegroup_number"]) == str(declared_spacegroup),
                              f"source says {declared_spacegroup}, spglib finds {ref['spacegroup_number']}"))
    codes = {}

    if exciting_back is not None:
        lat = np.array(exciting_back["lattice_bohr"]) * Bohr
        frac = np.array(exciting_back["frac"])
        atoms = Atoms(symbols=exciting_back["symbols"], cell=lat, pbc=True,
                      **({"positions": frac * Bohr} if exciting_back["cartesian"] else {"scaled_positions": frac}))
        m = _metrics(atoms)
        codes["exciting"] = m
        results += _compare("exciting", m, ref)
        results.append(_check("exciting: functional", exciting_back["xctype"] == EXCITING_XC[req.functional],
                              f"xctype={exciting_back['xctype']}"))
        results.append(_check("exciting: k-mesh", exciting_back["ngridk"] == " ".join(map(str, req.kmesh)),
                              f"ngridk={exciting_back['ngridk']}"))
        if exciting_schema is not None and exciting_schema.get("ok") is not None:
            results.append(_check("exciting: input.xml valid against exciting's schema", exciting_schema["ok"],
                                  exciting_schema["detail"] or "valid"))

    if questaal_back is not None:
        alat = questaal_back["alat_bohr"] * Bohr
        lat = np.array(questaal_back["plat"]) * alat
        pos = np.array(questaal_back["positions"])
        atoms = Atoms(symbols=questaal_back["symbols"], cell=lat, pbc=True,
                      **({"scaled_positions": pos} if questaal_back["positions_are_fractional"] else {"positions": pos * alat}))
        m = _metrics(atoms)
        codes["questaal"] = m
        results += _compare("questaal", m, ref)
        lc = questaal_back["lmchk"]
        if lc["cell_volume_bohr3"]:
            v = lc["cell_volume_bohr3"] * Bohr**3 / len(atoms)
            results.append(_check("questaal: lmchk cell volume", abs(v / ref["volume_per_atom_A3"] - 1) < 1e-5,
                                  f"lmchk {lc['cell_volume_bohr3']} bohr³ = {v:.6f} Å³/atom"))
        if lc["space_group_operations"] is not None:
            from spglib import get_symmetry_dataset

            ds = get_symmetry_dataset((cell.lattice, cell.frac, cell.atoms.numbers), symprec=1e-3)
            results.append(_check("questaal: lmchk symmetry operations", lc["space_group_operations"] == len(ds.rotations),
                                  f"lmchk {lc['space_group_operations']}, spglib {len(ds.rotations)}"))
        if lc["max_sphere_overlap_percent"] is not None:
            results.append(_check("questaal: muffin-tin spheres do not overlap", lc["max_sphere_overlap_percent"] <= 0,
                                  f"max overlap {lc['max_sphere_overlap_percent']}%"))
        results.append(_check("questaal: k-mesh", questaal_back["nkabc"] == list(req.kmesh), f"nkabc={questaal_back['nkabc']}"))
        want = QUESTAAL_LIBXC_IDS.get(req.functional)
        got = questaal_back["xcfun"]
        results.append(_check("questaal: functional (libxc ids)", bool(want and got and tuple(got[1:3]) == want),
                              f"xcfun={got}, expected libxc {want}"))
        results.append(_check("questaal: gmax set", questaal_back["gmax"] not in (None, "NULL"), f"gmax={questaal_back['gmax']}"))

    if "exciting" in codes and "questaal" in codes:
        e, q = codes["exciting"], codes["questaal"]
        results.append(_check("exciting vs questaal: same crystal",
                              e["spacegroup_number"] == q["spacegroup_number"] and e["natoms"] == q["natoms"]
                              and abs(e["volume_per_atom_A3"] / q["volume_per_atom_A3"] - 1) < REL_TOL,
                              f"V/atom {e['volume_per_atom_A3']:.6f} vs {q['volume_per_atom_A3']:.6f} Å³"))
    return {"passed": all(r["ok"] for r in results), "reference": ref, "codes": codes, "results": results}
