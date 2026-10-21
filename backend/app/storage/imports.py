"""Bring theory into Storage, so the XRD side (Raj's pipeline) and the DFT side share the same datasets.

  import_materials_project   an MP structure as a reference_structure dataset (symmetrized CIF + manifest)
  save_computed_structure    a DFT equation-of-state equilibrium structure as a reference_structure dataset,
                             with how it was computed in the manifest (code, functional, settings, V0, B0)

Both are plain datasets: they show in the Storage tree, can be used as the reference structure of an XRD
refinement, and are searchable like any other dataset.
"""

import json
import re
from pathlib import Path

from ase import Atoms
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.io.cif import CifWriter

from app.dft import materials, sources, structure
from app.models.contracts import Manifest
from app.storage import datasets
from app.storage.objects import get_store


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")[:60]


def _write(dataset_id: str, atoms: Atoms, manifest_extra: dict, readme: str, formula: str) -> Manifest:
    store = get_store()
    cif = str(CifWriter(AseAtomsAdaptor.get_structure(atoms), symprec=1e-3))
    store.put(f"datasets/{dataset_id}/raw/{dataset_id}.cif", cif.encode(), "chemical/x-cif")
    store.put(f"datasets/{dataset_id}/README.md", readme.encode(), "text/markdown")
    m = Manifest.model_validate({"id": dataset_id, "role": "reference_structure", "technique": "structure",
                                 "material": formula, "format": "cif", "files": ["raw/*.cif"], **manifest_extra})
    datasets.write_manifest(m, store)
    return m


def import_materials_project(mp_id: str) -> Manifest:
    entry = materials.get(mp_id)
    atoms = sources.load(f"mp:{mp_id}").atoms
    cell = structure.standard_primitive(atoms)
    dataset_id = _slug(f"mp-{entry['formula']}-{mp_id.removeprefix('mp-')}")
    readme = (f"# {entry['formula']} — Materials Project {mp_id}\n\nStructure from the Materials Project ({entry['spacegroup']}), "
              f"relaxed with GGA(+U). Energy above hull: {entry['e_above_hull_eV']} eV/atom.\n\n"
              f"https://next-gen.materialsproject.org/materials/{mp_id}\n")
    return _write(dataset_id, cell.atoms, {"source": f"https://next-gen.materialsproject.org/materials/{mp_id}",
                                           "computed": {"by": "Materials Project", "id": mp_id,
                                                        "e_above_hull_eV": entry["e_above_hull_eV"]}},
                  readme, cell.atoms.get_chemical_formula(mode="metal", empirical=True))


def save_computed_structure(set_dir: Path, code: str) -> Manifest:
    """The equilibrium structure of a code's EOS fit: the set's cell scaled to the fitted V0."""
    eos = json.loads((set_dir / "studies" / "eos" / "study.json").read_text())
    entry = eos["codes"].get(code) or {}
    fit = entry.get("fit")
    if not fit:
        raise ValueError(f"no equation-of-state fit for {code} in this set")
    prov = json.loads((set_dir / "provenance.json").read_text())
    cell = structure.standard_primitive(sources.load(prov["request"]["structure"]).atoms)
    eq = structure.scaled(cell, fit["V0_over_source"]).atoms
    formula = eq.get_chemical_formula(mode="metal", empirical=True)
    functional = prov["request"]["functional"]
    dataset_id = _slug(f"dft-{formula}-{code}-{functional}-eos")
    computed = {"by": code, "functional": functional, "set": set_dir.name, "kmesh": entry["settings"]["kmesh"],
                "basis_scale": entry["settings"]["basis_scale"], "V0_A3_per_atom": fit["V0_A3_per_atom"],
                "B0_GPa": fit["B0_GPa"], "B0_prime": fit["B0_prime"], "source_structure": prov["request"]["structure"]}
    readme = (f"# {formula} — {functional} equilibrium structure from {code}\n\nCell of `{prov['request']['structure']}` scaled "
              f"isotropically to the Birch-Murnaghan V0 of a 7-volume equation of state (CoRefine set {set_dir.name}).\n")
    return _write(dataset_id, eq, {"source": f"corefine:{set_dir.name}", "computed": computed}, readme, formula)
