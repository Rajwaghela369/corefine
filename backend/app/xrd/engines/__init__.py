"""Established refinement programs as analysis engines, next to the agents' own code: GSAS-II and MAUD.

Each engine gets the same inputs, prepared by code from Storage: the measured scan (sanitized pdCIF -> 2θ,
intensity, σ from the file's least-squares weights), the reference structure's CIF, and the instrument facts from
the manifest (wavelength, whether Kα2 is present, lab or synchrotron). Each returns the same result shape, so runs
from different engines can be compared side by side. Nothing here invents an instrument value: what the manifest
does not give comes from the engine's own documented defaults, and the result says which.
"""

import json
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import gemmi
import numpy as np

from app.storage import datasets
from app.storage.objects import get_store
from app.storage.sanitize import sanitize_pdcif

ENGINES = {
    "agents": {"label": "Agents (Python)", "tool": None,
               "about": "Claude plans the analysis and writes the fitting code; every step runs in a sandbox"},
    "gsas2": {"label": "GSAS-II", "tool": "gsas2",
              "about": "Rietveld refinement with GSAS-II (APS): background, cell and displacement, profile, size, strain"},
    "maud": {"label": "MAUD", "tool": "maud",
             "about": "Rietveld refinement with MAUD (Lutterotti) in batch mode: background and scale, then cell and basic "
                      "parameters, then microstructure"},
}
TIMEOUT_S = 1800


class EngineError(RuntimeError):
    pass


@dataclass
class Prepared:
    workdir: Path
    scan: Path            # 2θ, intensity, σ
    cif: Path
    wavelength_A: float
    ka2: bool
    source: str           # "lab" | "synchrotron"
    measured_file: str
    reference_id: str
    notes: list[str] = field(default_factory=list)


def available(engine: str) -> tuple[bool, str]:
    from app.dft import tools

    tool = ENGINES[engine]["tool"]
    if tool is None:
        return True, "built in"
    exe = tools.managed_executable(tool)
    return (True, str(exe)) if exe else (False, f"{ENGINES[engine]['label']} is not installed; click Install next to it")


def reference_for(measured_id: str, chosen: list[str]) -> str:
    """The reference structure among the selected datasets, else the one in Storage for the same material."""
    m = datasets.load_manifest(measured_id)
    for i in chosen:
        if datasets.load_manifest(i).role == "reference_structure":
            return i
    same = [r.id for r in datasets.list_indexed() if r.role == "reference_structure" and r.material == m.material]
    if not same:
        raise EngineError(f"no reference structure for {m.material} in Storage; add one (a CIF) to refine against")
    return same[0]


def prepare(measured_id: str, reference_id: str, workdir: Path, file: str | None = None) -> Prepared:
    store = get_store()
    m = datasets.load_manifest(measured_id, store)
    if m.format != "pdcif":
        raise EngineError(f"{measured_id}: engines read pdCIF scans; {m.format} is not supported yet")
    inst = m.instrument
    if not inst or not inst.wavelength_A:
        raise EngineError(f"{measured_id}: the manifest has no wavelength; an engine cannot refine without one")
    keys = datasets.dataset_files(m, store)
    key = next((k for k in keys if k.endswith("/" + file)), None) if file else keys[0]
    if not key:
        raise EngineError(f"{file} is not in {measured_id}")
    doc = gemmi.cif.read_string(sanitize_pdcif(store.get(key).decode(errors="replace"))[0])
    block = next((b for b in doc if b.find_values("_pd_proc_2theta_corrected")), None)
    if block is None:
        raise EngineError(f"{key}: no _pd_proc_2theta_corrected loop")
    x = np.array(block.find_values("_pd_proc_2theta_corrected"), float)
    y = np.array(block.find_values("_pd_proc_intensity_total"), float)
    wv = block.find_values("_pd_proc_ls_weight")
    notes = []
    if wv:
        w = np.array(wv, float)
        sig = np.where(w > 0, 1 / np.sqrt(np.where(w > 0, w, 1)), np.nan)
        sig = np.where(np.isnan(sig), np.nanmax(sig), sig)
        notes.append("σ = 1/√weight from _pd_proc_ls_weight")
    else:
        sig = np.sqrt(np.maximum(y, 1))
        notes.append("no weights in the file: σ = √intensity")
    workdir.mkdir(parents=True, exist_ok=True)
    scan = workdir / "scan.xye"
    np.savetxt(scan, np.c_[x, y, sig], fmt="%.6f %.6g %.6g")
    ref = datasets.load_manifest(reference_id, store)
    ref_keys = datasets.dataset_files(ref, store)
    if not ref_keys:
        raise EngineError(f"{reference_id} has no CIF")
    cif = workdir / "phase.cif"
    cif.write_bytes(store.get(ref_keys[0]))
    extra = inst.model_extra or {}
    source = "synchrotron" if inst.synchrotron else "lab"
    return Prepared(workdir, scan, cif, float(inst.wavelength_A), bool(extra.get("ka2_present")), source,
                    key.rsplit("/", 1)[-1], reference_id, notes)


def _run(cmd: list[str], cwd: Path, log: Path) -> None:
    with open(log, "a") as fh:
        p = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, timeout=TIMEOUT_S)
    if p.returncode != 0:
        raise EngineError(f"{cmd[0]} exited {p.returncode}; see {log.name}")


# --- GSAS-II -------------------------------------------------------------------------

def run_gsas2(pr: Prepared) -> dict:
    from app.dft import tools

    py = tools.managed_executable("gsas2")
    if not py:
        raise EngineError("GSAS-II is not installed")
    out = pr.workdir / "gsas2"
    job = {"data": str(pr.scan), "cif": str(pr.cif), "out": str(out), "wavelength_A": pr.wavelength_A,
           "ka2": pr.ka2, "source": pr.source}
    (pr.workdir / "gsas2_job.json").write_text(json.dumps(job, indent=1))
    script = Path(__file__).parent / "gsas2_refine.py"
    _run([str(py), str(script), str(pr.workdir / "gsas2_job.json")], pr.workdir, pr.workdir / "gsas2.log")
    r = json.loads((out / "result.json").read_text())
    fit = np.genfromtxt(out / "fit.csv", delimiter=",", names=True)
    return {"engine": "gsas2", "cell": r["cell"], "cell_esd": r["cell_esd"], "Rwp_percent": r["Rwp_percent"],
            "zero_deg": r["zero_deg"], "displacement_um": r.get("displacement_um"), "size_um": r["size_um"],
            "microstrain": r["microstrain"] * 1e-6, "stages": r["stages"],  # GSAS-II reports microstrain in units of 1e-6
            "settings": {"instrument": r["instrument_defaults"],
            "profile": r["profile"]}, "warnings": [],
            "curve": {"x": fit["two_theta"].tolist(), "observed": fit["observed"].tolist(),
                      "calculated": fit["calculated"].tolist(), "background": fit["background"].tolist()}}


# --- MAUD ------------------------------------------------------------------------------
# Batch mode (com.radiographema.MaudText) reads an instruction file whose loop rows each load an analysis (.par),
# optionally add a data file and import a phase from a CIF, apply one of MAUD's refinement wizards, iterate and save.
# Wizard indices from MAUD's FilePar.refineWizard: 0 background + scale, 1 + basic phase parameters (cell, offset),
# 2 + microstructure. The starting analysis is MAUD's own files/default.par (Bragg-Brentano, Cu Kα1 + Kα2).

MAUD_STAGES = [(0, "background and scale", 5), (1, "cell and basic parameters", 10), (2, "microstructure", 10)]


def _maud_paths() -> tuple[Path, Path]:
    """MAUD's own Java and the folder with Maud.jar: Maud/jdk/bin/java + Maud/lib on Linux,
    Maud.app/Contents/PlugIns/Home/bin/java + Maud.app/Contents/Java in the macOS app bundle."""
    from app.dft import tools

    java = tools.managed_executable("maud")
    if not java:
        raise EngineError("MAUD is not installed")
    for lib in (java.parents[2] / "lib", java.parents[3] / "Java"):
        if (lib / "Maud.jar").is_file():
            return java, lib
    raise EngineError(f"MAUD is installed but Maud.jar is not next to {java}")


def maud_template(lib: Path, pr: Prepared) -> str:
    with zipfile.ZipFile(lib / "Maud.jar") as z:
        t = z.read("files/default.par").decode()
    # the wavelength is the dataset's; Kα2 (MAUD's default line and weight) stays only when the manifest says it is present
    t = t.replace("_diffrn_radiation_wavelength 1.5405982 #min", f"_diffrn_radiation_wavelength {pr.wavelength_A} #min")
    if not pr.ka2:
        t = re.sub(r"#subordinateObject_2\n.*?#end_subordinateObject_2\n", "", t, flags=re.S)
    if pr.source == "synchrotron":  # transmission/capillary: no Bragg-Brentano corrections (as in MILK's synchrotron template)
        t = (t.replace("#subordinateObject_Bragg-Brentano", "#subordinateObject_No Corrections")
              .replace("#end_subordinateObject_Bragg-Brentano", "#end_subordinateObject_No Corrections")
              .replace("_pd_instr_geometry 'Bragg-Brentano'", "_pd_instr_geometry 'No Corrections'")
              .replace("#subordinateObject_Theta-2Theta", "#subordinateObject_2Theta")
              .replace("#end_subordinateObject_Theta-2Theta", "#end_subordinateObject_2Theta")
              .replace("_diffrn_measurement_method 'Theta-2Theta'", "_diffrn_measurement_method '2Theta'"))
    # weights from the data's own σ, not MAUD's default √I (the NIST intensities are normalised, not counts)
    return t.replace("_pd_proc_ls_weight_scheme sqrt", "_pd_proc_ls_weight_scheme Default")


def _maud_ins(workdir: Path, rows: list[str], cols: list[str]) -> str:
    return "_maud_working_directory\n '" + str(workdir) + "/'\n\nloop_\n" + "\n".join(cols) + "\n" + "\n".join(rows) + "\n"


def _par_value(text: str, tag: str) -> tuple[float | None, float | None]:
    m = re.search(rf"^{re.escape(tag)} ([-\d.Ee+]+)(?:\(([-\d.Ee+]+)\))?", text, re.M)
    return (float(m.group(1)), float(m.group(2)) if m.group(2) else None) if m else (None, None)


def run_maud(pr: Prepared) -> dict:
    java_exe, lib = _maud_paths()
    out = pr.workdir / "maud"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pr.scan, out / "scan.xye")
    shutil.copy2(pr.cif, out / "phase.cif")
    (out / "start.par").write_text(maud_template(lib, pr))
    java = [str(java_exe), "-Xmx2g", "-Djava.awt.headless=true", "--enable-native-access=ALL-UNNAMED",
            "--add-opens", "java.base/java.net=ALL-UNNAMED", "-cp", str(lib) + "/*", "com.radiographema.MaudText"]
    stages, prev = [], "start.par"
    for i, (wizard, name, iters) in enumerate(MAUD_STAGES):
        nxt = f"stage{i + 1}.par"
        if i == 0:
            cols = ["_riet_analysis_file", "_riet_analysis_iteration_number", "_riet_analysis_wizard_index",
                    "_riet_analysis_fileToSave", "_riet_meas_datafile_name", "_maud_import_phase", "_riet_append_simple_result_to"]
            row = f" '{prev}' {iters} {wizard} '{nxt}' 'scan.xye' 'phase.cif' 'results.txt'"
        else:
            cols = ["_riet_analysis_file", "_riet_analysis_iteration_number", "_riet_analysis_wizard_index",
                    "_riet_analysis_fileToSave", "_riet_append_simple_result_to"]
            row = f" '{prev}' {iters} {wizard} '{nxt}' 'results.txt'"
        ins = out / f"stage{i + 1}.ins"
        ins.write_text(_maud_ins(out, [row], cols))
        _run([*java, "-f", str(ins)], out, pr.workdir / "maud.log")
        if not (out / nxt).is_file():
            raise EngineError(f"MAUD wrote no {nxt}; see maud.log")
        lines = (out / "results.txt").read_text().strip().splitlines()
        stages.append({"stage": name, "wizard": wizard, "Rwp_percent": float(lines[-1].split("\t")[1])})
        prev = nxt
    par = (out / prev).read_text()
    cell = {k: _par_value(par, f"_cell_{k}") for k in ("length_a", "length_b", "length_c", "angle_alpha", "angle_beta", "angle_gamma")}
    biso, _ = _par_value(par, "_atom_site_B_iso_or_equiv")
    offset = re.search(r"_riet_par_2-theta_offset\n\s*([-\d.Ee+]+)", par)
    size, _ = _par_value(par, "_riet_par_cryst_size")
    strain, _ = _par_value(par, "_riet_par_rs_microstrain")
    warnings = []
    if biso is not None and biso < 0:
        warnings.append(f"B_iso refined to {biso:.3g} Å² (negative, unphysical): MAUD's default instrument profile does "
                        "not match this instrument; treat its intensities with care")
    return {"engine": "maud", "cell": {k: v for k, (v, _) in cell.items()},
            "cell_esd": {k: e for k, (_, e) in cell.items() if k.startswith("length")},
            "Rwp_percent": stages[-1]["Rwp_percent"], "zero_deg": float(offset.group(1)) if offset else None,
            "displacement_um": None, "size_um": size / 1e4 if size else None, "microstrain": strain,
            "stages": stages, "warnings": warnings, "B_iso_A2": biso,
            "settings": {"instrument": "MAUD files/default.par, Caglioti PV profile, "
                                       + ("no geometry corrections (synchrotron)" if pr.source == "synchrotron" else "Bragg-Brentano")
                                       + "; wavelength from the dataset"
                                       + ("; Kα2 line and weight: MAUD default" if pr.ka2 else "; Kα1 only"),
                         "weights": "σ from the data file (weight scheme Default)"},
            "curve": None,  # batch mode does not export MAUD's computed pattern
            }


RUNNERS = {"gsas2": run_gsas2, "maud": run_maud}
