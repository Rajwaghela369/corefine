"""VASP (plane waves + PAW): POSCAR, KPOINTS, INCAR, and POTCAR when the user's licensed POTCARs are configured.

POTCARs are licensed and are never downloaded or shipped. With VASP_PP_PATH set (the same convention
ASE and pymatgen use: <VASP_PP_PATH>/potpaw_PBE/<El>/POTCAR) the POTCAR is assembled; otherwise the
other three files are written and the POTCAR check is reported as not done, with the reason.

INCAR carries only what the request asks for (functional); ENCUT, PREC, smearing and convergence are
left to VASP's defaults, which then depend on the POTCAR (ENCUT defaults to the largest ENMAX).
"""

import hashlib
import re
from pathlib import Path

from ase.io import read as ase_read
from ase.io import write as ase_write

from app.config import Settings
from app.dft.codes.base import CodeAdapter, ReadBack, Results
from app.dft.request import CalcRequest
from app.dft.structure import Cell

# GGA tag values (VASP wiki: GGA); both use the PBE PAW set
GGA = {"PBE": "PE", "PBEsol": "PS"}
POTCAR_SET = {"PBE": "potpaw_PBE", "PBEsol": "potpaw_PBE"}
EV_PER_HA = 27.211386245988


class VaspAdapter(CodeAdapter):
    name, label, method, main_file = "vasp", "VASP", "plane waves + PAW", "INCAR"
    program = "vasp_std"

    def availability(self, s: Settings) -> tuple[bool, str]:
        if s.VASP_PP_PATH and s.VASP_PP_PATH.is_dir():
            return True, f"POTCARs from {s.VASP_PP_PATH}"
        return True, "inputs without POTCAR (licensed; set VASP_PP_PATH to assemble it)"

    def functionals(self) -> dict[str, str]:
        return GGA

    def write(self, cell: Cell, req: CalcRequest, outdir: Path, s: Settings, title: str) -> dict:
        outdir.mkdir(parents=True, exist_ok=True)
        atoms = cell.atoms
        ase_write(outdir / "POSCAR", atoms, format="vasp", direct=True, sort=True)
        species = list(dict.fromkeys(sorted(atoms.get_chemical_symbols())))
        k = " ".join(map(str, req.kmesh))
        (outdir / "KPOINTS").write_text(f"Gamma-centred {k} mesh\n0\nGamma\n {k}\n 0 0 0\n")
        (outdir / "INCAR").write_text(f"SYSTEM = {title}\nGGA = {GGA[req.functional]}\n")
        potcar = {"assembled": False, "reason": "VASP_PP_PATH not set (POTCARs are licensed)", "species": species}
        if s.VASP_PP_PATH and s.VASP_PP_PATH.is_dir():
            parts, titles = [], []
            for el in species:
                f = s.VASP_PP_PATH / POTCAR_SET[req.functional] / el / "POTCAR"
                if not f.is_file():
                    potcar["reason"] = f"no POTCAR at {f}"
                    break
                text = f.read_text()
                parts.append(text)
                titles += re.findall(r"TITEL\s*=\s*(.+)", text)[:1]
            else:
                (outdir / "POTCAR").write_text("".join(parts))
                potcar = {"assembled": True, "titles": titles, "sha256": hashlib.sha256("".join(parts).encode()).hexdigest()}
        return {"files": sorted(f.name for f in outdir.iterdir()),
                "set_explicitly": {"GGA": GGA[req.functional], "KPOINTS": f"Gamma-centred {k}"},
                "defaults": {"source": "VASP defaults (VASP wiki); ENCUT follows the POTCAR's largest ENMAX",
                             "values": {"ENCUT": "max ENMAX of POTCAR", "PREC": "Normal", "ISMEAR": 1, "SIGMA": 0.2,
                                        "EDIFF": "1E-4", "NELM": 60}},
                "potcar": potcar}

    def read_back(self, outdir: Path, req: CalcRequest) -> ReadBack:
        atoms = ase_read(outdir / "POSCAR", format="vasp")
        lines = (outdir / "KPOINTS").read_text().splitlines()
        kmesh = [int(x) for x in lines[3].split()[:3]] if len(lines) > 3 and lines[2].strip().lower().startswith("g") else None
        incar = (outdir / "INCAR").read_text()
        gga = re.search(r"(?im)^\s*GGA\s*=\s*(\w+)", incar)
        extra = [{"check": "KPOINTS is Gamma-centred like the other codes", "ok": lines[2].strip().lower().startswith("g"),
                  "detail": lines[2].strip()}]
        potcar = outdir / "POTCAR"
        if potcar.is_file():
            titel = re.findall(r"TITEL\s*=\s*\S+\s+(\w+)", potcar.read_text())
            want = list(dict.fromkeys(atoms.get_chemical_symbols()))
            extra.append({"check": "POTCAR species match POSCAR order", "ok": titel == want, "detail": f"POTCAR {titel}, POSCAR {want}"})
        else:
            extra.append({"check": "POTCAR assembled", "ok": None,
                          "detail": "not assembled: POTCARs are licensed; set VASP_PP_PATH to include them"})
        got = gga.group(1) if gga else None
        return ReadBack(atoms=atoms, kmesh=kmesh, functional_ok=got == GGA[req.functional], functional_detail=f"GGA={got}",
                        extra_checks=extra)

    def run_args(self, outdir: Path) -> dict:
        return {"program": self.program, "args": [], "stdout": "vasp.out"}

    def parse_results(self, rundir: Path) -> Results | None:
        outcar = rundir / "OUTCAR"
        if not outcar.is_file():
            return None
        text = outcar.read_text(errors="replace")
        toten = re.findall(r"free\s+energy\s+TOTEN\s*=\s*([-\d.]+)\s*eV", text)
        efermi = re.findall(r"E-fermi\s*:\s*([-\d.]+)", text)
        nelm = re.search(r"NELM\s*=\s*(\d+)", text)
        steps = len(re.findall(r"-{10,}\s*Iteration\s+\d+\(\s*\d+\)", text))
        converged = "aborting loop because EDIFF is reached" in text
        warnings = [] if converged else ["electronic loop did not report reaching EDIFF"]
        return Results(converged=converged, total_energy_eV=float(toten[-1]) if toten else None,
                       fermi_eV=float(efermi[-1]) if efermi else None, gap_eV=None, scf_iterations=steps or None,
                       warnings=warnings, raw={"NELM": int(nelm.group(1)) if nelm else None})
