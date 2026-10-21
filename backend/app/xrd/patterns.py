"""Powder XRD for inspection: measured scans from Storage, simulated patterns from any structure.

Shared by experimentalists (look at a scan, see which reflections are where) and theorists (see where a
DFT lattice puts the peaks relative to a measured scan). Technique-specific code lives under app/xrd;
other spectroscopies get their own modules with the same shape (measured series + simulated lines).

Simulated: pymatgen XRDCalculator kinematic intensities (no instrument profile, no Kα2) at the wavelength
of the measurement it is compared with; an optional pseudo-Voigt broadening is only for drawing.
"""

import io

import gemmi
import numpy as np
from ase import Atoms
from pymatgen.analysis.diffraction.xrd import XRDCalculator
from pymatgen.io.ase import AseAtomsAdaptor

from app.storage import datasets
from app.storage.objects import get_store
from app.storage.sanitize import sanitize_pdcif

MAX_POINTS = 6000


class PatternError(ValueError):
    pass


def decimate(x: np.ndarray, y: np.ndarray, max_points: int = MAX_POINTS) -> tuple[list, list]:
    """Min-max decimation: keeps every peak top and trough visible when a scan has more points than pixels."""
    if len(x) <= max_points:
        return x.tolist(), y.tolist()
    buckets = max_points // 2
    edges = np.linspace(0, len(x), buckets + 1, dtype=int)
    xs, ys = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        seg = y[a:b]
        for i in sorted((a + int(np.argmin(seg)), a + int(np.argmax(seg)))):
            xs.append(float(x[i]))
            ys.append(float(y[i]))
    return xs, ys


def measured(dataset_id: str, file: str | None = None, lo: float | None = None, hi: float | None = None) -> dict:
    """A measured scan from Storage. pdCIF: the *_meas block (answer blocks are stripped as for the agents)."""
    store = get_store()
    m = datasets.load_manifest(dataset_id, store)
    if m.role != "measured_pattern":
        raise PatternError(f"{dataset_id} is a {m.role}, not a measured pattern")
    keys = datasets.dataset_files(m, store)
    if not keys:
        raise PatternError(f"{dataset_id} has no data files")
    key = next((k for k in keys if k.endswith("/" + file)), None) if file else keys[0]
    if key is None:
        raise PatternError(f"{file} not in {dataset_id}")
    raw = store.get(key).decode("utf-8", errors="replace")
    if m.format == "pdcif":
        doc = gemmi.cif.read_string(sanitize_pdcif(raw)[0])
        block = next((b for b in doc if b.find_values("_pd_proc_2theta_corrected") or b.find_values("_pd_meas_2theta_scan")), None)
        if block is None:
            raise PatternError("no 2θ loop in the file")
        tag = "_pd_proc_2theta_corrected" if block.find_values("_pd_proc_2theta_corrected") else "_pd_meas_2theta_scan"
        x = np.array(block.find_values(tag), float)
        ytag = next(t for t in ("_pd_proc_intensity_total", "_pd_meas_counts_total", "_pd_meas_intensity_total")
                    if block.find_values(t))
        y = np.array(block.find_values(ytag), float)
    elif m.format in ("xy", "csv"):
        arr = np.loadtxt(io.StringIO(raw), delimiter="," if m.format == "csv" else None, comments="#", usecols=(0, 1))
        x, y = arr[:, 0], arr[:, 1]
    else:
        raise PatternError(f"format {m.format} is not a pattern")
    sel = np.ones_like(x, bool)
    if lo is not None:
        sel &= x >= lo
    if hi is not None:
        sel &= x <= hi
    xs, ys = decimate(x[sel], y[sel])
    inst = m.instrument.model_dump() if m.instrument else {}
    return {"dataset": dataset_id, "file": key.rsplit("/", 1)[-1], "files": [k.rsplit("/", 1)[-1] for k in keys],
            "x": xs, "y": ys, "n_points": int(sel.sum()), "range": [float(x.min()), float(x.max())],
            "wavelength_A": inst.get("wavelength_A"), "wavelength_source": inst.get("wavelength_source"),
            "radiation": inst.get("radiation")}


def simulate(atoms: Atoms, wavelength_A: float, two_theta: tuple[float, float] = (10, 150), label: str = "") -> dict:
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    xrd = XRDCalculator(wavelength=wavelength_A)
    # hkl are reported in the cell given; use the conventional standard cell so (111) reads as people expect
    conv = SpacegroupAnalyzer(AseAtomsAdaptor.get_structure(atoms), symprec=1e-3).get_conventional_standard_structure()
    pat = xrd.get_pattern(conv, two_theta_range=two_theta)
    peaks = [{"two_theta": float(t), "intensity": float(i), "d_A": float(d),
              "hkl": " ".join(str(v) for v in h[0]["hkl"]), "multiplicity": int(h[0]["multiplicity"])}
             for t, i, d, h in zip(pat.x, pat.y, pat.d_hkls, pat.hkls) if i >= 0.1]
    return {"label": label, "wavelength_A": wavelength_A, "peaks": peaks,
            "note": "kinematic intensities; no instrument profile, no Kα2"}


def atoms_from_dataset(dataset_id: str) -> Atoms:
    from app.dft import sources

    return sources.load(f"dataset:{dataset_id}").atoms


def measured_full(dataset_id: str, file: str | None = None):
    """Full-resolution scan (x, y, wavelength, file) for analysis; same reading rules as measured()."""
    store = get_store()
    m = datasets.load_manifest(dataset_id, store)
    keys = datasets.dataset_files(m, store)
    key = next((k for k in keys if k.endswith("/" + file)), None) if file else (keys[0] if keys else None)
    if key is None or m.format != "pdcif":
        raise PatternError("analysis currently reads powder-CIF (pdcif) scans")
    doc = gemmi.cif.read_string(sanitize_pdcif(store.get(key).decode("utf-8", errors="replace"))[0])
    block = next((b for b in doc if b.find_values("_pd_proc_2theta_corrected") or b.find_values("_pd_meas_2theta_scan")), None)
    if block is None:
        raise PatternError("no 2θ loop in the file")
    tag = "_pd_proc_2theta_corrected" if block.find_values("_pd_proc_2theta_corrected") else "_pd_meas_2theta_scan"
    ytag = next(t for t in ("_pd_proc_intensity_total", "_pd_meas_counts_total", "_pd_meas_intensity_total") if block.find_values(t))
    wl = m.instrument.wavelength_A if m.instrument else None
    if not wl:
        raise PatternError(f"{dataset_id} has no wavelength in its manifest")
    return (np.array(block.find_values(tag), float), np.array(block.find_values(ytag), float), float(wl),
            key.rsplit("/", 1)[-1], m)
