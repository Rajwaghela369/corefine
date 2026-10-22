"""VASP (plane waves + PAW): POSCAR, KPOINTS, INCAR, and POTCAR when the user's licensed POTCARs are configured.

POTCARs are licensed and are never downloaded or shipped. With VASP_PP_PATH set (ASE's convention:
<VASP_PP_PATH>/potpaw_PBE/<El>/POTCAR for GGA, <VASP_PP_PATH>/potpaw/<El>/POTCAR for LDA) the POTCAR is
assembled; otherwise the other three files are written and the POTCAR check is reported as not done.
LDA has no GGA tag: VASP then takes the functional from the POTCAR (LEXCH = CA in the LDA set).

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

# GGA tag values (VASP wiki: GGA); PBE and PBEsol use the PBE PAW set. LDA: no GGA tag, LDA PAW set.
GGA = {"PBE": "PE", "PBEsol": "PS", "LDA": None}
POTCAR_SET = {"PBE": "potpaw_PBE", "PBEsol": "potpaw_PBE", "LDA": "potpaw"}
LEXCH = {"potpaw_PBE": "PE", "potpaw": "CA"}  # functional the POTCAR set was generated with
EV_PER_HA = 27.211386245988


def outcar_gap(text: str) -> float | None:
    """Lowest empty minus highest occupied band energy over all k-points of the last eigenvalue listing in OUTCAR
    ("band No.  band energies  occupation" blocks). Occupations above half of the maximum count as occupied."""
    last = text.rsplit("E-fermi", 1)
    if len(last) < 2:
        return None
    rows = re.findall(r"(?m)^\s+\d+\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$", last[1].split("-" * 40)[0])
    if not rows:
        return None
    occ_max = max(float(o) for _, o in rows)
    occupied = [float(e) for e, o in rows if float(o) > occ_max / 2]
    empty = [float(e) for e, o in rows if float(o) <= occ_max / 2]
    if not occupied or not empty:
        return None
    return max(0.0, min(empty) - max(occupied))


class VaspAdapter(CodeAdapter):
    name, label, method, main_file = "vasp", "VASP", "plane waves + PAW", "INCAR"
    program = "vasp_std"

    def availability(self, s: Settings) -> tuple[bool, str]:
        if s.VASP_PP_PATH and s.VASP_PP_PATH.is_dir():
            return True, f"POTCARs from {s.VASP_PP_PATH}"
        return True, "inputs without POTCAR (licensed; set VASP_PP_PATH to assemble it)"

    def functionals(self) -> dict[str, str]:
        return {f: (f"GGA = {g}" if g else "no GGA tag; LDA POTCARs") for f, g in GGA.items()}

    def problems(self, req: CalcRequest) -> list[str]:
        from app.config import get_settings

        out = super().problems(req)
        if req.basis_scale != 1.0 and not get_settings().VASP_PP_PATH:
            out.append("VASP: a basis scan needs the POTCAR (ENCUT is set relative to its ENMAX)")
        return out

    def write(self, cell: Cell, req: CalcRequest, outdir: Path, s: Settings, title: str) -> dict:
        outdir.mkdir(parents=True, exist_ok=True)
        atoms = cell.atoms
        ase_write(outdir / "POSCAR", atoms, format="vasp", direct=True, sort=True)
        species = list(dict.fromkeys(sorted(atoms.get_chemical_symbols())))
        k = " ".join(map(str, req.kmesh))
        (outdir / "KPOINTS").write_text(f"Gamma-centred {k} mesh\n0\nGamma\n {k}\n 0 0 0\n")
        incar = f"SYSTEM = {title}\n" + (f"GGA = {GGA[req.functional]}\n" if GGA[req.functional] else "")
        (outdir / "INCAR").write_text(incar)
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
                if req.basis_scale != 1.0:
                    enmax = max(float(x) for x in re.findall(r"ENMAX\s*=\s*([\d.]+)", "".join(parts)))
                    (outdir / "INCAR").write_text(incar + f"ENCUT = {enmax * req.basis_scale:.1f}\n")
        return {"files": sorted(f.name for f in outdir.iterdir()),
                "set_explicitly": {"GGA": GGA[req.functional] or f"not set ({req.functional}: functional from the POTCAR)",
                                   "POTCAR set": POTCAR_SET[req.functional], "KPOINTS": f"Gamma-centred {k}"},
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
            lexch = re.findall(r"LEXCH\s*=\s*(\w+)", potcar.read_text())
            want_x = LEXCH[POTCAR_SET[req.functional]]
            extra.append({"check": f"POTCAR functional (LEXCH) is {want_x}", "ok": bool(lexch) and set(lexch) == {want_x},
                          "detail": f"LEXCH {sorted(set(lexch))}"})
        else:
            extra.append({"check": "POTCAR assembled", "ok": None,
                          "detail": "not assembled: POTCARs are licensed; set VASP_PP_PATH to include them"})
        got = gga.group(1) if gga else None
        return ReadBack(atoms=atoms, kmesh=kmesh, functional_ok=got == GGA[req.functional],
                        functional_detail=f"GGA={got}" + ("" if GGA[req.functional] else " (LDA: no GGA tag expected)"),
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
                       fermi_eV=float(efermi[-1]) if efermi else None, gap_eV=outcar_gap(text), scf_iterations=steps or None,
                       warnings=warnings, raw={"NELM": int(nelm.group(1)) if nelm else None})
