"""exciting (FP-(L)APW+lo) ground-state input.xml, written with excitingtools.

Only what the request asks for goes into the XML (functional, k-mesh); everything else is left to
exciting's defaults, which are read from the schema of the exciting tree in use and recorded in
the provenance. Species files are copied next to input.xml so the folder runs anywhere (e.g. LISE),
with their SHA-256 recorded: they must match the exciting version that runs the job.
"""

import hashlib
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from ase.units import Bohr
from excitingtools.input import ExcitingGroundStateInput, ExcitingInputXML, ExcitingStructure

from app.dft.request import EXCITING_XC, CalcRequest
from app.dft.structure import Cell

# Ground-state attributes whose schema defaults are worth recording for a "normal inputs" run
DEFAULTS_OF_INTEREST = ("rgkmax", "gmaxvr", "lmaxapw", "lmaxvr", "nempty", "stype", "swidth", "epsengy",
                        "epspot", "maxscl", "mixer", "beta0")


class ExcitingSetupError(RuntimeError):
    pass


def schema_defaults(exciting_root: Path, names=DEFAULTS_OF_INTEREST) -> dict[str, str]:
    """Default values of groundstate attributes, read from xml/schema/groundstate.xsd."""
    xs = "{http://www.w3.org/2001/XMLSchema}"
    tree = ET.parse(exciting_root / "xml" / "schema" / "groundstate.xsd")
    gs = next((e for e in tree.iter(f"{xs}element") if e.get("name") == "groundstate"), None)
    if gs is None:
        return {}
    out = {}
    for attr in gs.iter(f"{xs}attribute"):
        if attr.get("name") in names and attr.get("default") is not None:
            out[attr.get("name")] = attr.get("default")
    return out


def write(cell: Cell, req: CalcRequest, outdir: Path, exciting_root: Path, title: str) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    species_dir = exciting_root / "species"
    species_files = {}
    for el in dict.fromkeys(cell.symbols):
        src = species_dir / f"{el}.xml"
        if not src.is_file():
            raise ExcitingSetupError(f"no exciting species file for {el} in {species_dir}")
        shutil.copy2(src, outdir / src.name)
        species_files[src.name] = hashlib.sha256(src.read_bytes()).hexdigest()

    atoms = [{"species": el, "position": [float(x) for x in pos]} for el, pos in zip(cell.symbols, cell.frac)]
    lattice_bohr = (cell.lattice / Bohr).tolist()
    structure = ExcitingStructure(atoms, lattice=lattice_bohr, species_path="./")
    gs = ExcitingGroundStateInput(xctype=EXCITING_XC[req.functional], ngridk=list(req.kmesh))
    inp = ExcitingInputXML(structure=structure, groundstate=gs, title=title)
    path = outdir / "input.xml"
    # excitingtools writes <atom ...> </atom>; the schema requires empty content, so self-close them
    path.write_text(re.sub(r"<(atom\b[^>]*)>\s*</atom>", r"<\1/>", inp.to_xml_str()))
    return {
        "files": ["input.xml", *species_files],
        "set_explicitly": {"xctype": EXCITING_XC[req.functional], "ngridk": " ".join(map(str, req.kmesh))},
        "defaults_from_schema": schema_defaults(exciting_root),
        "species_sha256": species_files,
        "units": "lattice vectors in bohr (Å / ase.units.Bohr), positions fractional",
    }


def validate(outdir: Path, exciting_root: Path) -> dict:
    """xmllint against the schema of the exciting tree in use."""
    xsd = exciting_root / "xml" / "schema" / "input.xsd"
    if not shutil.which("xmllint"):
        return {"ok": None, "detail": "xmllint not installed; schema validation skipped"}
    p = subprocess.run(["xmllint", "--noout", "--schema", str(xsd), str(outdir / "input.xml")],
                       capture_output=True, text=True, timeout=60)
    return {"ok": p.returncode == 0, "detail": (p.stderr or p.stdout).strip()[-1500:]}


def read_back(outdir: Path) -> dict:
    """Parse input.xml as exciting would see it: lattice (bohr × scale), species, fractional coords."""
    root = ET.parse(outdir / "input.xml").getroot()
    crystal = root.find("structure/crystal")
    scale = float(crystal.get("scale", "1"))
    lattice = [[float(x) * scale for x in v.text.split()] for v in crystal.findall("basevect")]
    symbols, frac = [], []
    for sp in root.findall("structure/species"):
        el = sp.get("speciesfile").removesuffix(".xml")
        for at in sp.findall("atom"):
            symbols.append(el)
            frac.append([float(x) for x in at.get("coord").split()])
    gs = root.find("groundstate")
    return {"lattice_bohr": lattice, "symbols": symbols, "frac": frac,
            "cartesian": root.find("structure").get("cartesian", "false") == "true",
            "xctype": gs.get("xctype"), "ngridk": gs.get("ngridk")}
