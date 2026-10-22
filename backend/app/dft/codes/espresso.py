"""Quantum ESPRESSO (plane waves + pseudopotentials, pw.x): pw.in written with ASE, pseudopotentials copied alongside.

Pseudopotentials come from the user's QE_PSEUDO_DIR (any library: SSSP, pslibrary, ...) or, if unset,
from the library CoRefine installs (app/dft/tools.py): SSSP for PBE/PBEsol, JTH PAW for LDA; nothing is guessed. For each element exactly
one candidate file must match; with several, the one whose header functional matches the request is
used, otherwise the request is refused with the list.
pw.x has no default plane-wave cutoff, so it is taken from (in order) an SSSP-style JSON in the pseudo
folder, or the cutoffs the pseudopotential file itself suggests; if neither exists the request is refused.
The functional is not forced in pw.in: QE takes it from the pseudopotentials, and the check verifies that
their header functional is the one requested.
"""

import json
import math
import re
import shutil
from pathlib import Path

from ase.io import read as ase_read
from ase.io import write as ase_write

from app.config import Settings
from app.dft.codes.base import CodeAdapter, ReadBack, Results
from app.dft.request import CalcRequest
from app.dft.structure import Cell

EV_PER_RY = 13.605693122994
# Used only when pw.x itself stops with "smearing is needed" (a metal run with the default fixed occupations).
# pw.x has no default smearing width; this is CoRefine's choice and is recorded with every run that uses it.
METAL_SMEARING = {"occupations": "smearing", "smearing": "mv", "degauss": 0.01}
SMEARING_NOTE = "smearing, Marzari-Vanderbilt, 0.01 Ry (CoRefine's choice)"


class EspressoSetupError(RuntimeError):
    pass


def upf_header(path: Path) -> dict:
    """Attributes of <PP_HEADER .../> (UPF v2) or the fields of the UPF v1 header, as far as needed here."""
    text = path.read_text(errors="replace")[:20000]
    m = re.search(r"<PP_HEADER(.*?)/?>", text, re.S)
    attrs = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', m.group(1))) if m else {}
    if not attrs:  # UPF v1: functional on the line ending with "Exchange-Correlation functional"
        f = re.search(r"^\s*(.+?)\s+Exchange-Correlation functional", text, re.M)
        if f:
            attrs["functional"] = f.group(1)
    return attrs


def functional_family(header_functional: str) -> str | None:
    f = header_functional.upper().replace("-", " ")
    if "PBESOL" in f or re.search(r"\bPSX\b", f):
        return "PBEsol"
    if "PBE" in f or (re.search(r"\bPBX\b", f) and re.search(r"\bPBC\b", f)):
        return "PBE"
    if re.search(r"\bPZ\b|\bPW\b", f) and not re.search(r"\bPB[XC]\b|GGA", f):
        return "LDA"
    return None


def candidates(pseudo_dir: Path, element: str) -> list[Path]:
    rx = re.compile(rf"^{element}[._-]", re.I)
    return sorted(p for p in pseudo_dir.iterdir() if p.suffix.lower() == ".upf" and rx.match(p.name))


def sssp_cutoffs(pseudo_dir: Path) -> dict:
    for f in sorted(pseudo_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and all(isinstance(v, dict) and "filename" in v for v in list(data.values())[:3]):
            return {"file": f.name, "table": data}
    return {}


class EspressoAdapter(CodeAdapter):
    name, label, method, main_file = "espresso", "Quantum ESPRESSO", "plane waves + pseudopotentials (pw.x)", "pw.in"
    program = "pw.x"

    def pseudo_dir(self, s: Settings, functional: str) -> Path | None:
        """Your own QE_PSEUDO_DIR if set, else the library CoRefine installed for that functional (SSSP or JTH)."""
        if s.QE_PSEUDO_DIR:
            return s.QE_PSEUDO_DIR
        from app.dft import tools

        return tools.managed_pseudo_dir(functional)

    def availability(self, s: Settings) -> tuple[bool, str]:
        if s.QE_PSEUDO_DIR:
            if not s.QE_PSEUDO_DIR.is_dir() or not any(s.QE_PSEUDO_DIR.glob("*.[uU][pP][fF]")):
                return False, f"no .UPF files in {s.QE_PSEUDO_DIR}"
            return True, f"pseudopotentials from {s.QE_PSEUDO_DIR}"
        installed = [f"{f}: {d.name}" for f in ("PBE", "PBEsol", "LDA") if (d := self.pseudo_dir(s, f))]
        if installed:
            return True, f"pseudopotentials installed by CoRefine ({', '.join(installed)})"
        return False, "no pseudopotentials: install SSSP from the Codes panel, or set QE_PSEUDO_DIR"

    def functionals(self) -> dict[str, str]:
        return {"PBE": "from pseudopotentials", "PBEsol": "from pseudopotentials", "LDA": "from pseudopotentials"}

    def problems(self, req: CalcRequest) -> list[str]:
        from app.config import get_settings

        if self.pseudo_dir(get_settings(), req.functional) is None:
            lib = "JTH LDA" if req.functional == "LDA" else f"SSSP {req.functional}"
            return [f"Quantum ESPRESSO: no {req.functional} pseudopotentials (install {lib} or set QE_PSEUDO_DIR)"]
        return []

    def choose_pseudos(self, elements: list[str], functional: str, pseudo_dir: Path) -> dict[str, Path]:
        sssp = sssp_cutoffs(pseudo_dir).get("table", {})
        chosen, problems = {}, []
        for el in elements:
            if el in sssp and (pseudo_dir / sssp[el]["filename"]).is_file():
                chosen[el] = pseudo_dir / sssp[el]["filename"]
                continue
            cands = candidates(pseudo_dir, el)
            matching = [c for c in cands if functional_family(upf_header(c).get("functional", "")) == functional]
            if len(cands) == 1:
                chosen[el] = cands[0]
            elif len(matching) == 1:
                chosen[el] = matching[0]
            elif not cands:
                problems.append(f"no pseudopotential for {el} in {pseudo_dir}")
            else:
                problems.append(f"several pseudopotentials for {el}: {[c.name for c in cands]}; keep one per element "
                                "(or add an SSSP-style JSON) so the choice is not a guess")
        if problems:
            raise EspressoSetupError("; ".join(problems))
        return chosen

    def write(self, cell: Cell, req: CalcRequest, outdir: Path, s: Settings, title: str) -> dict:
        outdir.mkdir(parents=True, exist_ok=True)
        elements = list(dict.fromkeys(cell.symbols))
        pdir = self.pseudo_dir(s, req.functional)
        if pdir is None:
            raise EspressoSetupError(f"no {req.functional} pseudopotentials available")
        pseudos = self.choose_pseudos(elements, req.functional, pdir)
        sssp = sssp_cutoffs(pdir)
        wfc, rho, source = [], [], None
        for el, p in pseudos.items():
            h = upf_header(p)
            fam = functional_family(h.get("functional", ""))
            if fam != req.functional:
                raise EspressoSetupError(f"{p.name} was generated with {h.get('functional') or 'an unknown functional'}, "
                                         f"not {req.functional}")
            entry = sssp.get("table", {}).get(el)
            if entry and entry.get("cutoff_wfc"):
                wfc.append(float(entry["cutoff_wfc"]))
                rho.append(float(entry.get("cutoff_rho") or 4 * float(entry["cutoff_wfc"])))  # 4x = pw.x default dual
                source = f"cutoff table {sssp['file']}" + ("" if entry.get("cutoff_rho") else "; ecutrho = pw.x default 4 x ecutwfc")
            elif float(h.get("wfc_cutoff") or 0) > 0:
                wfc.append(float(h["wfc_cutoff"]))
                rho.append(float(h.get("rho_cutoff") or 4 * float(h["wfc_cutoff"])))
                source = source or "suggested cutoffs in the pseudopotential headers"
            else:
                raise EspressoSetupError(f"no cutoff recommendation for {p.name} (header or SSSP JSON); pw.x has no default")
            shutil.copy2(p, outdir / p.name)
        ecutwfc, ecutrho = max(wfc) * req.basis_scale, max(rho) * req.basis_scale
        # pw.x computes only occupied bands for insulators, so no gap can be read; add empty bands by pw.x's own rule
        # for metals (20 % more, at least 4). Smearing runs already get them from pw.x.
        nelec = sum(float(upf_header(pseudos[el]).get("z_valence", "0").strip() or 0) for el in cell.symbols)
        nbnd = None
        if req.occupations != "smearing" and nelec > 0:
            nocc = math.ceil(nelec / 2)
            nbnd = nocc + max(4, math.ceil(0.2 * nocc))
        input_data = {"control": {"calculation": "scf", "prefix": "pwscf", "pseudo_dir": "./", "outdir": "./tmp",
                                  "title": title[:70], **({"tprnfor": True} if req.forces else {})},
                      "system": {"ecutwfc": ecutwfc, "ecutrho": ecutrho, **({"nbnd": nbnd} if nbnd else {}),
                                 **(METAL_SMEARING if req.occupations == "smearing" else {})}}
        with open(outdir / "pw.in", "w") as fd:
            ase_write(fd, cell.atoms, format="espresso-in", input_data=input_data,
                      pseudopotentials={el: p.name for el, p in pseudos.items()}, kpts=tuple(req.kmesh), koffset=(0, 0, 0),
                      crystal_coordinates=True)
        return {"files": sorted(f.name for f in outdir.iterdir()),
                "set_explicitly": {"K_POINTS": f"automatic {' '.join(map(str, req.kmesh))} 0 0 0 (Gamma-centred)",
                                   **({"cutoffs": f"x{req.basis_scale} the recommended ecutwfc/ecutrho"} if req.basis_scale != 1 else {}),
                                   "functional": f"{req.functional}, via the pseudopotentials",
                                   **({"nbnd": f"{nbnd}: {math.ceil(nelec / 2)} occupied + empty bands (pw.x's rule for metals: "
                                               "20 %, at least 4), so the gap can be read"} if nbnd else {}),
                                   **({"occupations": SMEARING_NOTE} if req.occupations == "smearing" else {})},
                "defaults": {"source": f"pw.x defaults; cutoffs from {source}",
                             "values": {"ecutwfc_Ry": ecutwfc, "ecutrho_Ry": ecutrho, "conv_thr": "1e-6 (pw.x default)",
                                        **({} if req.occupations == "smearing" else {"occupations": "fixed (pw.x default)"})}},
                "pseudopotentials": {el: p.name for el, p in pseudos.items()}, "pseudo_dir": str(pdir),
                "pseudo_md5": {p.name: (sssp.get("table", {}).get(el) or {}).get("md5") for el, p in pseudos.items()}}

    def read_back(self, outdir: Path, req: CalcRequest) -> ReadBack:
        atoms = ase_read(outdir / "pw.in", format="espresso-in")
        text = (outdir / "pw.in").read_text()
        k = re.search(r"K_POINTS\s*\{?\s*automatic\s*\}?\s*\n\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d)\s+(\d)\s+(\d)", text, re.I)
        species = re.findall(r"(?m)^\s*([A-Z][a-z]?)\s+[\d.]+\s+(\S+\.upf)\s*$", text, re.I)
        fams = {el: functional_family(upf_header(outdir / f).get("functional", "")) for el, f in species}
        extra = [{"check": "K_POINTS is Gamma-centred like the other codes", "ok": bool(k and k.group(4, 5, 6) == ("0", "0", "0")),
                  "detail": " ".join(k.groups()) if k else "no automatic K_POINTS"},
                 {"check": "pseudopotential files present next to pw.in", "ok": all((outdir / f).is_file() for _, f in species),
                  "detail": ", ".join(f for _, f in species)}]
        prov = outdir.parent / "provenance.json"
        expected = {}
        if prov.is_file():
            import json as _json

            expected = (_json.loads(prov.read_text()).get("generated", {}).get(self.name, {}) or {}).get("pseudo_md5", {})
        for _, f in species:
            if expected.get(f):
                import hashlib

                got = hashlib.md5((outdir / f).read_bytes()).hexdigest()
                extra.append({"check": f"{f} matches the library's published MD5", "ok": got == expected[f], "detail": got})
        return ReadBack(atoms=atoms, kmesh=[int(x) for x in k.group(1, 2, 3)] if k else None,
                        functional_ok=bool(fams) and all(f == req.functional for f in fams.values()),
                        functional_detail=f"pseudopotential functionals {fams}", extra_checks=extra)

    def run_args(self, outdir: Path) -> dict:
        return {"program": self.program, "args": ["-in", "pw.in"], "stdout": "pw.out"}

    def parse_results(self, rundir: Path) -> Results | None:
        out = rundir / "pw.out"
        if not out.is_file():
            return None
        text = out.read_text(errors="replace")
        e = re.findall(r"!\s+total energy\s+=\s+([-\d.]+)\s+Ry", text)
        conv = re.search(r"convergence has been achieved in\s+(\d+)\s+iterations", text)
        homo = re.search(r"highest occupied, lowest unoccupied level \(ev\):\s+([-\d.]+)\s+([-\d.]+)", text)
        homo_only = re.search(r"highest occupied level \(ev\):\s+([-\d.]+)", text)
        ef = re.search(r"the Fermi energy is\s+([-\d.]+)\s+ev", text)
        return Results(converged=bool(conv), total_energy_eV=float(e[-1]) * EV_PER_RY if e else None,
                       fermi_eV=float(ef.group(1)) if ef else (float(homo.group(1)) if homo else
                                                                (float(homo_only.group(1)) if homo_only else None)),
                       gap_eV=float(homo.group(2)) - float(homo.group(1)) if homo else None,
                       scf_iterations=int(conv.group(1)) if conv else None,
                       warnings=[] if conv else ["pw.x did not report convergence"])

    def heal(self, rundir: Path) -> dict | None:
        out = rundir / "pw.out"
        text = out.read_text(errors="replace") if out.is_file() else ""
        if "smearing is needed" not in text:
            return None
        pw = rundir / "pw.in"
        src = pw.read_text()
        if "occupations" in src:
            return None
        lines = [f"   {k:16s} = {repr(v) if isinstance(v, str) else v}" for k, v in METAL_SMEARING.items()]
        healed = re.sub(r"(&SYSTEM\b[^\n]*\n)", lambda m: m.group(1) + "\n".join(lines) + "\n", src, count=1, flags=re.I)
        if healed == src:
            return None
        pw.write_text(healed)
        return {"error": "pw.x: charge is wrong: smearing is needed (the system is metallic)",
                "change": "occupations='smearing', smearing='mv' (Marzari-Vanderbilt), degauss=0.01 Ry",
                "why": "pw.x defaults to fixed occupations, which cannot describe a metal; 0.01 Ry is CoRefine's choice"}

    def parse_forces(self, rundir: Path):
        out = rundir / "pw.out"
        if not out.is_file() or "Forces acting on atoms" not in out.read_text(errors="replace"):
            return None
        return ase_read(out, format="espresso-out").get_forces()
