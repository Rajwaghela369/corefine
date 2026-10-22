"""Find materials in the Materials Project so a person can pick one instead of knowing an id.

Without a key: MP's public OPTIMADE endpoint (structure + `_mp_stability`, i.e. energy above the
convex hull and formation energy, GGA/GGA+U). Space groups are computed here with spglib, because
the endpoint does not fill them. With MP_API_KEY: the official summary API adds band gap, metal flag
and magnetic ordering, which the planner uses (e.g. smearing for metals).

Queries: a formula ("GaAs", "Fe2O3"; any element order) or elements ("Ga,As" or "Ga-As": every
material made of exactly those elements).
"""

import re

import httpx
import numpy as np
from ase import Atoms
from pymatgen.core import Composition

from app.config import get_settings
from app.dft.structure import spacegroup_of

OPTIMADE = "https://optimade.materialsproject.org/v1/structures"
MP_SUMMARY = "https://api.materialsproject.org/materials/summary/"
TIMEOUT = 30


class SearchError(ValueError):
    pass


def same_material(formula_a: str, formula_b: str) -> bool:
    """True when two formulas reduce to the same composition (Si2 and Si, ZnO and Zn2O2)."""
    try:
        return optimade_formula(formula_a) == optimade_formula(formula_b)
    except Exception:
        return False


def optimade_formula(formula: str) -> str:
    """OPTIMADE reduced formula: elements in alphabetical order, counts reduced, 1s omitted (GaAs -> AsGa)."""
    try:
        comp = Composition(formula).reduced_composition
    except Exception as e:  # pymatgen raises several types for bad formulas
        raise SearchError(f"not a chemical formula: {formula!r}") from e
    return "".join(f"{el.symbol}{'' if n == 1 else int(n)}" for el, n in sorted(comp.items(), key=lambda kv: kv[0].symbol))


def _filter(query: str) -> str:
    q = query.strip()
    if re.fullmatch(r"[A-Z][a-z]?(\s*[,\- ]\s*[A-Z][a-z]?)+", q):
        els = sorted(set(re.split(r"\s*[,\- ]\s*", q)))
        return f'elements HAS ALL {", ".join(f"{e!r}".replace("'", chr(34)) for e in els)} AND nelements={len(els)}'
    return f'chemical_formula_reduced="{optimade_formula(q)}"'


def _hull(stab: dict | None) -> float | None:
    stab = stab or {}
    for key in ("gga_gga+u", "gga_gga+u_r2scan", "r2scan"):
        if key in stab and stab[key].get("energy_above_hull") is not None:
            return float(stab[key]["energy_above_hull"])
    return None


def search(query: str, limit: int = 25, max_sites: int = 40) -> list[dict]:
    params = {"filter": _filter(query), "page_limit": 100,
              "response_fields": "chemical_formula_reduced,nsites,_mp_stability,lattice_vectors,cartesian_site_positions,"
                                 "species_at_sites"}
    r = httpx.get(OPTIMADE, params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        raise SearchError(f"Materials Project OPTIMADE: HTTP {r.status_code}")
    out = []
    for item in r.json().get("data", []):
        a = item["attributes"]
        entry = {"id": item["id"], "formula": a["chemical_formula_reduced"], "nsites": a["nsites"],
                 "e_above_hull_eV": _hull(a.get("_mp_stability")), "spacegroup": None, "band_gap_eV": None,
                 "is_metal": None, "ordering": None}
        if a.get("lattice_vectors") and a["nsites"] <= 400:
            try:
                atoms = Atoms(symbols=a["species_at_sites"], positions=np.array(a["cartesian_site_positions"]),
                              cell=np.array(a["lattice_vectors"]), pbc=True)
                n, sym = spacegroup_of(atoms)
                entry["spacegroup"] = f"{sym} ({n})"
            except Exception:
                pass
        out.append(entry)
    _add_summary(out)
    out.sort(key=lambda e: (e["e_above_hull_eV"] if e["e_above_hull_eV"] is not None else 99, e["nsites"]))
    for e in out:
        e["stable"] = e["e_above_hull_eV"] is not None and e["e_above_hull_eV"] <= 1e-6
        e["fits_laptop"] = e["nsites"] <= max_sites
    return out[:limit]


def mp_number(material_id: str) -> int | None:
    """Both Materials Project id forms as one integer: legacy 'mp-149' and the current API's 'mp-aaaaaaft'
    (the same number written in base 26 with a=0 ... z=25; checked: aaaaaaft=149, aaaaadtm=2534, aaaaaaan=13)."""
    body = material_id.removeprefix("mp-")
    if body.isdigit():
        return int(body)
    if body.isalpha() and body.islower():
        n = 0
        for ch in body:
            n = n * 26 + (ord(ch) - ord("a"))
        return n
    return None


def _add_summary(entries: list[dict]) -> None:
    """Band gap, metal flag and magnetism from the official API, only when MP_API_KEY is set."""
    key = get_settings().MP_API_KEY
    if not key or not entries:
        return
    ids = ",".join(e["id"] for e in entries)
    r = httpx.get(MP_SUMMARY, params={"material_ids": ids, "_fields": "material_id,band_gap,is_metal,ordering,is_magnetic",
                                      "_limit": len(entries)},
                  headers={"X-API-KEY": key}, timeout=TIMEOUT)
    if r.status_code != 200:
        return
    by_number = {mp_number(d["material_id"]): d for d in r.json().get("data", [])}
    for e in entries:
        d = by_number.get(mp_number(e["id"]))
        if d:
            e.update(band_gap_eV=d.get("band_gap"), is_metal=d.get("is_metal"), ordering=d.get("ordering"),
                     is_magnetic=d.get("is_magnetic"))


def get(mp_id: str) -> dict:
    """One material's search entry (stability, space group, and summary fields when a key is set)."""
    r = httpx.get(OPTIMADE, params={"filter": f'id="{mp_id}"', "response_fields":
                                    "chemical_formula_reduced,nsites,_mp_stability,lattice_vectors,cartesian_site_positions,"
                                    "species_at_sites"}, timeout=TIMEOUT)
    data = r.json().get("data") if r.status_code == 200 else None
    if not data:
        raise SearchError(f"Materials Project has no {mp_id}")
    a = data[0]["attributes"]
    atoms = Atoms(symbols=a["species_at_sites"], positions=np.array(a["cartesian_site_positions"]),
                  cell=np.array(a["lattice_vectors"]), pbc=True)
    n, sym = spacegroup_of(atoms)
    entry = {"id": mp_id, "formula": a["chemical_formula_reduced"], "nsites": a["nsites"], "spacegroup": f"{sym} ({n})",
             "e_above_hull_eV": _hull(a.get("_mp_stability")), "band_gap_eV": None, "is_metal": None, "ordering": None}
    _add_summary([entry])
    return entry
