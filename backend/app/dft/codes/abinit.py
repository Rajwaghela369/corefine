"""ABINIT (plane waves + norm-conserving pseudopotentials): abinit.abi written here, every length with its unit.

ASE's ABINIT writer is not used: it writes a shifted k-mesh, ixc 7 (LDA) regardless of the request and
Cartesian positions without units. Here the cell is in Å (acell ... angstrom), positions are reduced,
the k-mesh is Γ-centred, and the functional comes from the pseudopotentials (ixc is not set; the check
reads pspxc from each file). Pseudopotentials: PseudoDojo "standard" table (installable); ecut is the
largest "normal" hint of the elements present (PseudoDojo's recommendation), times basis_scale.
ABINIT requires an SCF stopping criterion and has no default: tolvrs 1e-10 is CoRefine's choice.
"""

import json
import math
import re
import shutil
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.data import atomic_numbers, chemical_symbols
from ase.units import Bohr, Hartree

from app.config import Settings
from app.dft.codes.base import CodeAdapter, ReadBack, Results
from app.dft.request import CalcRequest
from app.dft.structure import Cell

PSPXC = {11: "PBE", -101130: "PBE", -116133: "PBEsol", 7: "LDA", -1012: "LDA"}
TOLVRS = "1.0d-10"
METAL = {"occopt": 7, "tsmear": 0.01}  # Gaussian-like smearing, 0.01 Ha: CoRefine's choice, only when requested


def zion_of(psp8: Path) -> float:
    """Valence charge: second number on line 2 of a psp8 file (zatom, zion, pspd)."""
    return float(psp8.read_text(errors="replace").splitlines()[1].split()[1])


def pspxc_of(psp8: Path) -> int | None:
    lines = psp8.read_text(errors="replace").splitlines()
    if len(lines) > 2:
        try:
            return int(lines[2].split()[1])
        except (IndexError, ValueError):
            return None
    return None


class AbinitAdapter(CodeAdapter):
    name, label, method, main_file = "abinit", "ABINIT", "plane waves + norm-conserving pseudopotentials", "abinit.abi"
    program = "abinit"

    def library(self, functional: str) -> Path | None:
        from app.dft import tools

        return tools.managed_pseudo_dir(functional, kind="pseudodojo")

    def availability(self, s: Settings) -> tuple[bool, str]:
        libs = [lib.name for f in ("PBE", "LDA") if (lib := self.library(f))]
        if libs:
            return True, f"PseudoDojo pseudopotentials installed by CoRefine ({', '.join(libs)})"
        return False, "no pseudopotentials: install PseudoDojo from the Codes panel"

    def functionals(self) -> dict[str, str]:
        return {"PBE": "from pseudopotentials", "LDA": "from pseudopotentials"}

    def problems(self, req: CalcRequest) -> list[str]:
        out = super().problems(req)
        if not out and self.library(req.functional) is None:
            out.append(f"ABINIT: no {req.functional} PseudoDojo library installed")
        return out

    def write(self, cell: Cell, req: CalcRequest, outdir: Path, s: Settings, title: str) -> dict:
        outdir.mkdir(parents=True, exist_ok=True)
        lib = self.library(req.functional)
        table = json.loads((lib / "standard.djson").read_text())["pseudos_metadata"]
        species = list(dict.fromkeys(cell.symbols))
        missing = [el for el in species if el not in table]
        if missing:
            raise RuntimeError(f"PseudoDojo standard table has no pseudopotential for {missing}")
        for el in species:
            shutil.copy2(lib / table[el]["basename"], outdir / table[el]["basename"])
        ecut = round(max(table[el]["hints"]["normal"]["ecut"] for el in species) * req.basis_scale, 3)
        typat = [species.index(el) + 1 for el in cell.symbols]
        lines = [f"# CoRefine: {title}", "acell 3*1.0 angstrom", "rprim"]
        lines += ["  " + "  ".join(f"{x:.10f}" for x in row) for row in cell.lattice]
        lines += [f"natom {len(cell.symbols)}", f"ntypat {len(species)}",
                  "znucl " + " ".join(str(atomic_numbers[el]) for el in species), "typat " + " ".join(map(str, typat)), "xred"]
        lines += ["  " + "  ".join(f"{x:.10f}" for x in row) for row in cell.frac]
        lines += ['pp_dirpath "./"', 'pseudos "' + ", ".join(table[el]["basename"] for el in species) + '"',
                  f"ecut {ecut}", "kptopt 1", "ngkpt " + " ".join(map(str, req.kmesh)), "nshiftk 1", "shiftk 0 0 0",
                  f"tolvrs {TOLVRS}", "prtwf 0"]
        nband = None
        if req.occupations == "smearing":
            lines += [f"occopt {METAL['occopt']}", f"tsmear {METAL['tsmear']}"]
        else:  # ABINIT's default nband for insulators is the occupied count: add empty bands so the gap can be read
            nelec = sum(zion_of(lib / table[el]["basename"]) for el in cell.symbols)
            nocc = math.ceil(nelec / 2)
            nband = nocc + max(4, math.ceil(0.2 * nocc))
            lines += [f"nband {nband}"]
        (outdir / "abinit.abi").write_text("\n".join(lines) + "\n")
        return {"files": ["abinit.abi", *(table[el]["basename"] for el in species)],
                "set_explicitly": {"ngkpt": " ".join(map(str, req.kmesh)) + ", shiftk 0 0 0 (Gamma-centred)",
                                   "functional": f"{req.functional}, via the pseudopotentials",
                                   "tolvrs": f"{TOLVRS} (ABINIT has no default; CoRefine's choice)",
                                   **({"nband": f"{nband}: occupied + empty bands (20 %, at least 4), so the gap can be read"}
                                      if nband else {}),
                                   **({"occopt/tsmear": "7 / 0.01 Ha (CoRefine's choice)"} if req.occupations == "smearing" else {})},
                "defaults": {"source": "PseudoDojo hints (ecut) and ABINIT defaults",
                             "values": {"ecut_Ha": ecut, "ecut_source": f"largest PseudoDojo 'normal' hint x{req.basis_scale}",
                                        "nstep": "30 (ABINIT default)"}},
                "pseudopotentials": {el: table[el]["basename"] for el in species},
                "pseudo_md5": {table[el]["basename"]: table[el]["md5"] for el in species}}

    def read_back(self, outdir: Path, req: CalcRequest) -> ReadBack:
        text = (outdir / "abinit.abi").read_text()
        body = "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())

        def block(tag: str, rows: int) -> np.ndarray:
            m = re.search(rf"(?m)^\s*{tag}\s*\n((?:\s*[-\d.Ee+]+\s+[-\d.Ee+]+\s+[-\d.Ee+]+\s*\n){{{rows}}})", body)
            return np.array([[float(x) for x in ln.split()] for ln in m.group(1).strip().splitlines()])

        def ints(tag: str) -> list[int]:
            return [int(x) for x in re.search(rf"(?m)^\s*{tag}\s+([\d\s]+)$", body).group(1).split()]

        acell = re.search(r"(?m)^\s*acell\s+3\*([\d.]+)\s+(\w+)", body)
        unit = 1.0 if acell and acell.group(2).lower().startswith("ang") else Bohr
        natom = ints("natom")[0]
        lattice = block("rprim", 3) * float(acell.group(1)) * unit
        xred = block("xred", natom)
        znucl, typat = ints("znucl"), ints("typat")
        atoms = Atoms(symbols=[chemical_symbols[znucl[t - 1]] for t in typat], scaled_positions=xred, cell=lattice, pbc=True)
        shift = re.search(r"(?m)^\s*shiftk\s+([-\d.\s]+)$", body)
        files = re.search(r'pseudos\s+"([^"]+)"', body).group(1).split(",")
        xcs = {f.strip(): PSPXC.get(pspxc_of(outdir / f.strip())) for f in files}
        shift_txt = shift.group(1).strip() if shift else None
        extra = [{"check": "k-mesh is Gamma-centred like the other codes",
                  "ok": bool(shift) and all(float(x) == 0 for x in shift_txt.split()), "detail": f"shiftk {shift_txt}"},
                 {"check": "ixc not forced (functional from the pseudopotentials)", "ok": re.search(r"(?m)^\s*ixc\b", body) is None,
                  "detail": "no ixc line" if not re.search(r"(?m)^\s*ixc\b", body) else "ixc set explicitly"}]
        prov = outdir.parent / "provenance.json"
        generated = json.loads(prov.read_text()).get("generated", {}) if prov.is_file() else {}
        expected = (generated.get(self.name) or {}).get("pseudo_md5", {})
        import hashlib

        for f in files:
            want = expected.get(f.strip())
            if want:
                got = hashlib.md5((outdir / f.strip()).read_bytes()).hexdigest()
                extra.append({"check": f"{f.strip()} matches PseudoDojo's published MD5", "ok": got == want, "detail": got})
        return ReadBack(atoms=atoms, kmesh=ints("ngkpt"), functional_ok=all(v == req.functional for v in xcs.values()),
                        functional_detail=f"pseudopotential functionals {xcs}", extra_checks=extra)

    def run_args(self, outdir: Path) -> dict:
        return {"program": self.program, "args": ["abinit.abi"], "stdout": "abinit.log"}

    @staticmethod
    def gap(rundir: Path, abo: str) -> float | None:
        """Lowest empty minus highest occupied eigenvalue over the k-mesh, from abinito_EIG (fixed occupations only;
        the .abo prints no gap). None for smearing runs or when there are no empty bands."""
        occ = re.search(r"occopt:\s*([\d.Ee+-]+)", abo)
        nel = re.search(r"nelect:\s*([\d.Ee+-]+)", abo)
        eig = rundir / "abinito_EIG"
        if not (occ and nel and eig.is_file()) or int(float(occ.group(1))) != 1:
            return None
        nocc = round(float(nel.group(1))) // 2
        homo, lumo = [], []
        for block in re.split(r"kpt#\s*\d+,", eig.read_text())[1:]:
            vals = [float(v) for v in re.findall(r"[-]?\d+\.\d+", block.split("\n", 1)[1])]
            if len(vals) > nocc:
                homo.append(vals[nocc - 1])
                lumo.append(vals[nocc])
        return (min(lumo) - max(homo)) * Hartree if homo else None

    def parse_results(self, rundir: Path) -> Results | None:
        abo = rundir / "abinit.abo"
        if not abo.is_file():
            return None
        text = abo.read_text(errors="replace")
        e = re.findall(r"(?m)^\s*etotal\s+([-\d.Ee+]+)\s*$", text)
        conv = re.findall(r"At SCF step\s+(\d+).*=>converged\.", text)
        ef = re.findall(r"Fermi \(or HOMO\) energy \(hartree\)\s*=\s*([-\d.]+)", text)
        not_conv = "not enough SCF cycles to converge" in text
        return Results(converged=bool(conv) and not not_conv, total_energy_eV=float(e[-1]) * Hartree if e else None,
                       fermi_eV=float(ef[-1]) * Hartree if ef else None, gap_eV=self.gap(rundir, text),
                       scf_iterations=int(conv[-1]) if conv else None,
                       warnings=[] if conv and not not_conv else ["ABINIT did not report SCF convergence"],
                       raw={"etotal_Ha": float(e[-1]) if e else None})
