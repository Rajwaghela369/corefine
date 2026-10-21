"""exciting (all-electron FP-(L)APW+lo): ground-state input.xml, written with excitingtools.

Only what the request asks for goes into the XML (functional, k-mesh); everything else is left to
exciting's defaults, read from the schema of the exciting tree in use and recorded in provenance.
Species files are copied next to input.xml so the folder is self-contained, with their SHA-256
recorded: they must match the exciting version that runs the job.
"""

import hashlib
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.units import Bohr
from excitingtools.input import ExcitingGroundStateInput, ExcitingInputXML, ExcitingStructure

from app.config import Settings
from app.dft.codes.base import CodeAdapter, ReadBack, Results
from app.dft.request import CalcRequest
from app.dft.structure import Cell

EV_PER_HA = 27.211386245988
# xctype values checked against xml/schema/groundstate.xsd
XC = {"PBE": "GGA_PBE", "PBEsol": "GGA_PBE_SOL", "LDA": "LDA_PW"}
# Ground-state attributes whose schema defaults are recorded for a "normal inputs" run
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
    return {a.get("name"): a.get("default") for a in gs.iter(f"{xs}attribute")
            if a.get("name") in names and a.get("default") is not None}


def validate(outdir: Path, exciting_root: Path) -> dict:
    """xmllint against the schema of the exciting tree in use."""
    xsd = exciting_root / "xml" / "schema" / "input.xsd"
    if not shutil.which("xmllint"):
        return {"ok": None, "detail": "xmllint not installed; schema validation skipped"}
    p = subprocess.run(["xmllint", "--noout", "--schema", str(xsd), str(outdir / "input.xml")],
                       capture_output=True, text=True, timeout=60)
    return {"ok": p.returncode == 0, "detail": (p.stderr or p.stdout).strip()[-1500:]}


class ExcitingAdapter(CodeAdapter):
    name, label, method, main_file = "exciting", "exciting", "all-electron FP-(L)APW+lo", "input.xml"
    program = "exciting_smp"  # or exciting_mpismp; the compute target decides which binary and launcher

    def availability(self, s: Settings) -> tuple[bool, str]:
        root = s.EXCITING_ROOT
        if not root:
            return False, "EXCITING_ROOT not set (needs the exciting tree for species files and schema)"
        if not (root / "species").is_dir() or not (root / "xml" / "schema").is_dir():
            return False, f"{root} has no species/ or xml/schema/"
        return True, f"species and schema from {root}"

    def functionals(self) -> dict[str, str]:
        return XC

    def write(self, cell: Cell, req: CalcRequest, outdir: Path, s: Settings, title: str) -> dict:
        root = s.EXCITING_ROOT
        outdir.mkdir(parents=True, exist_ok=True)
        species = {}
        for el in dict.fromkeys(cell.symbols):
            src = root / "species" / f"{el}.xml"
            if not src.is_file():
                raise ExcitingSetupError(f"no exciting species file for {el} in {root / 'species'}")
            shutil.copy2(src, outdir / src.name)
            species[src.name] = hashlib.sha256(src.read_bytes()).hexdigest()
        atoms = [{"species": el, "position": [float(x) for x in pos]} for el, pos in zip(cell.symbols, cell.frac)]
        structure = ExcitingStructure(atoms, lattice=(cell.lattice / Bohr).tolist(), species_path="./")
        extra = {}
        if req.basis_scale != 1.0:  # basis size ~ (rgkmax)^2, so an energy-like scale maps to sqrt on rgkmax
            default = float(schema_defaults(root).get("rgkmax", "7.0d0").replace("d", "e"))
            extra["rgkmax"] = round(default * req.basis_scale ** 0.5, 4)
        gs = ExcitingGroundStateInput(xctype=XC[req.functional], ngridk=list(req.kmesh), **extra)
        inp = ExcitingInputXML(structure=structure, groundstate=gs, title=title)
        # excitingtools writes <atom ...> </atom>; the schema requires empty content, so self-close them
        (outdir / "input.xml").write_text(re.sub(r"<(atom\b[^>]*)>\s*</atom>", r"<\1/>", inp.to_xml_str()))
        return {"files": ["input.xml", *species],
                "set_explicitly": {"xctype": XC[req.functional], "ngridk": " ".join(map(str, req.kmesh)),
                                   **{k: str(v) for k, v in extra.items()}},
                "defaults": {"source": "exciting schema (xml/schema/groundstate.xsd)", "values": schema_defaults(root)},
                "species_sha256": species,
                "units": "lattice vectors in bohr, positions fractional"}

    def read_back(self, outdir: Path, req: CalcRequest) -> ReadBack:
        root = ET.parse(outdir / "input.xml").getroot()
        crystal = root.find("structure/crystal")
        scale = float(crystal.get("scale", "1"))
        lattice = np.array([[float(x) for x in v.text.split()] for v in crystal.findall("basevect")]) * scale * Bohr
        symbols, coords = [], []
        for sp in root.findall("structure/species"):
            for at in sp.findall("atom"):
                symbols.append(sp.get("speciesfile").removesuffix(".xml"))
                coords.append([float(x) for x in at.get("coord").split()])
        cartesian = root.find("structure").get("cartesian", "false") == "true"
        atoms = Atoms(symbols=symbols, cell=lattice, pbc=True,
                      **({"positions": np.array(coords) * Bohr} if cartesian else {"scaled_positions": coords}))
        gs = root.find("groundstate")
        ngridk = gs.get("ngridk")
        extra = []
        from app.config import get_settings

        v = validate(outdir, get_settings().EXCITING_ROOT)
        if v["ok"] is not None:
            extra.append({"check": "input.xml valid against exciting's own schema", "ok": v["ok"], "detail": v["detail"] or "valid"})
        return ReadBack(atoms=atoms, kmesh=[int(x) for x in ngridk.split()] if ngridk else None,
                        functional_ok=gs.get("xctype") == XC[req.functional], functional_detail=f"xctype={gs.get('xctype')}",
                        extra_checks=extra)

    def run_args(self, outdir: Path) -> dict:
        return {"program": self.program, "args": [], "stdout": "exciting.log"}

    def parse_results(self, rundir: Path) -> Results | None:
        """From INFO.OUT (Hartree units): last total energy, Fermi energy, estimated gap, SCF count, convergence."""
        info = rundir / "INFO.OUT"
        if not info.is_file():
            return None
        text = info.read_text(errors="replace")

        def last(label: str) -> float | None:
            v = re.findall(rf"{label}\s*:\s*([-\d.Ee+]+)", text)
            return float(v[-1]) if v else None

        e, ef, gap = last("Total energy"), last("Fermi energy"), last("Estimated fundamental gap")
        iters = re.findall(r"SCF iteration number\s*:\s*(\d+)", text)
        converged = "Convergence targets achieved" in text
        stopped = re.search(r"EXCITING \w+ stopped", text) is not None
        warnings = [w for w, bad in (("SCF did not report convergence", not converged),
                                     ("INFO.OUT has no normal-stop line", not stopped)) if bad]
        return Results(converged=converged, total_energy_eV=e * EV_PER_HA if e is not None else None,
                       fermi_eV=ef * EV_PER_HA if ef is not None else None, gap_eV=gap * EV_PER_HA if gap is not None else None,
                       scf_iterations=int(iters[-1]) if iters else None, warnings=warnings,
                       raw={"total_energy_Ha": e, "fermi_Ha": ef, "gap_Ha": gap})
