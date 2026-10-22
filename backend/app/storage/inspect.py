"""What an uploaded file says about itself, for pre-filling the Add-dataset form. Only values that are literally in
the file are returned, each with the CIF tag it came from; nothing is looked up or defaulted. Refined results that a
measured CIF may carry (cell, R factors) are not read, so they can never leak into a manifest from here."""

import gemmi

# manifest field -> CIF tags that carry it, in order of preference (coreCIF and pdCIF names)
TAGS = {
    "radiation": ["_diffrn_radiation_type"],
    "radiation_source": ["_diffrn_source", "_diffrn_radiation_source"],
    "probe": ["_diffrn_radiation_probe"],
    "wavelength_A": ["_diffrn_radiation_wavelength", "_pd_instr_diffrn_radiation_wavelength"],
    "material": ["_chemical_formula_sum"],
}
POWDER = ("_pd_proc_2theta_corrected", "_pd_meas_2theta_scan", "_pd_meas_counts_total", "_pd_proc_intensity_total")
PROBES = {"x-ray", "neutron", "electron", "gamma"}


def _first(doc: gemmi.cif.Document, tag: str) -> str | None:
    for block in doc:
        for v in block.find_values(tag):
            v = gemmi.cif.as_string(v).strip()
            if v and v not in ("?", "."):
                return v
    return None


def inspect_cif(text: str) -> dict:
    """{'format': 'pdcif'|'cif', 'role': ..., 'found': {field: {'value', 'tag'}}} from one CIF's own tags."""
    doc = gemmi.cif.read_string(text)
    powder = any(block.find_values(t) for block in doc for t in POWDER)
    found: dict[str, dict] = {}
    for field, tags in TAGS.items():
        for tag in tags:
            if (v := _first(doc, tag)) is None:
                continue
            if field == "wavelength_A":
                try:
                    v = float(v.split("(")[0])
                except ValueError:
                    continue
            if field == "probe" and v.lower() not in PROBES:
                continue
            if field == "material":  # CIF writes the sum in Hill order ('O Zn'); people write the reduced formula (ZnO)
                from pymatgen.core import Composition

                try:
                    v = Composition(v).reduced_formula
                except ValueError:
                    pass
            found[field] = {"value": v.lower() if field == "probe" else v, "tag": tag}
            break
    # NIST's 11-BM files put the source in the radiation type
    if str(found.get("radiation", {}).get("value", "")).lower() == "synchrotron" and "radiation_source" not in found:
        found["radiation_source"] = found.pop("radiation")
    return {"format": "pdcif" if powder else "cif", "role": "measured_pattern" if powder else "reference_structure",
            "found": found}
