"""GSAS-II Rietveld refinement of one powder scan. Runs inside the GSAS-II environment (not the backend's):

    python gsas2_refine.py job.json

job.json: {"data": "scan.xye", "cif": "phase.cif", "out": "<folder>", "wavelength_A": 1.5405929,
           "ka2": false, "source": "lab" | "synchrotron"}

Starting instrument values are GSAS-II's own defaults (GSASII/defaultIparms.py: "CuKa lab data" for lab scans,
"APS 30keV 11BM" for synchrotron scans); only the wavelength is replaced by the dataset's. With Kα2 present, Lam2
and I(L2)/I(L1) stay at GSAS-II's defaults. The refinement sequence is the usual one from the GSAS-II scripting
tutorials: background + scale, then cell (+ specimen displacement, "Shift", for Bragg-Brentano lab scans), then the
Gaussian instrument profile (U, V, W) and asymmetry (SH/L), then isotropic size and microstrain. The Lorentzian
instrument terms X and Y stay at 0 so that size and microstrain carry the Lorentzian broadening (refining both
makes them 100 % correlated).
Writes result.json (every refined value with its esd and the residuals after each stage) and fit.csv (2θ, observed,
calculated, background).
"""

import json
import sys
from pathlib import Path

from GSASII import GSASIIscriptable as G2sc
from GSASII import defaultIparms

STAGES = [
    ("background and scale", {"set": {"Background": {"type": "chebyschev-1", "no. coeffs": 6, "refine": True}}}),
    ("cell and displacement", {"set": {"Cell": True}}),
    ("instrument profile", {"set": {"Instrument Parameters": ["U", "V", "W", "SH/L"]}}),
    ("size and microstrain", {"set": {"Size": {"type": "isotropic", "refine": True},
                                      "Mustrain": {"type": "isotropic", "refine": True}}}),
]


def instprm(job: dict, out: Path) -> tuple[Path, str]:
    label = "APS 30keV 11BM" if job["source"] == "synchrotron" else "CuKa lab data"
    lines = defaultIparms.defaultIparms[defaultIparms.defaultIparm_lbl.index(label)]
    text = "".join(lines)
    lam = f"{job['wavelength_A']:.7f}"
    if job["source"] == "synchrotron":
        text = text.replace("Lam:0.413263", f"Lam:{lam}")
    elif job["ka2"]:
        text = text.replace("Lam1:1.5405", f"Lam1:{lam}")
    else:  # monochromatic Kα1: one wavelength, no Kα2 terms
        text = text.replace("Lam1:1.5405;Lam2:1.5443;", f"Lam:{lam};").replace(";I(L2)/I(L1):0.5", "")
    p = out / "instrument.instprm"
    p.write_text(text)
    return p, label


def main() -> None:
    job = json.loads(Path(sys.argv[1]).read_text())
    out = Path(job["out"])
    out.mkdir(parents=True, exist_ok=True)
    prm, label = instprm(job, out)
    gpx = G2sc.G2Project(newgpx=str(out / "refinement.gpx"))
    hist = gpx.add_powder_histogram(job["data"], str(prm), fmthint="xye")
    if job["source"] == "lab":  # GSAS-II assumes Debye-Scherrer for single-wavelength data; a lab diffractometer is BB
        # the same entries GSAS-II's own reader sets for Bragg-Brentano (GSASIIfiles.py)
        hist.SampleParameters.update({"Type": "Bragg-Brentano", "Shift": [0.0, False], "Transparency": [0.0, False],
                                      "SurfRoughA": [0.0, False], "SurfRoughB": [0.0, False]})
    phase = gpx.add_phase(job["cif"], phasename="phase", histograms=[hist], fmthint="CIF")
    gpx.set_Controls("cycles", 10)
    stages = []
    for name, step in STAGES:
        sets = step["set"]
        hist_keys = {k: v for k, v in sets.items() if k in ("Background", "Instrument Parameters")}
        phase_keys = {k: v for k, v in sets.items() if k == "Cell"}
        hap_keys = {k: v for k, v in sets.items() if k in ("Size", "Mustrain")}
        if hist_keys:
            hist.set_refinements(hist_keys)
        if phase_keys:
            phase.set_refinements(phase_keys)
        if hap_keys:
            phase.set_HAP_refinements(hap_keys)
        if name == "background and scale":
            hist.SampleParameters["Scale"][1] = True
        if name == "cell and displacement" and job["source"] == "lab":  # Bragg-Brentano: specimen displacement is "Shift"
            hist.set_refinements({"Sample Parameters": ["Shift"]})
        gpx.refine()
        stages.append({"stage": name, "Rwp_percent": hist.get_wR(), "GOF": gpx.data["Covariance"]["data"]["Rvals"].get("GOF")})
    cell, esd = phase.get_cell_and_esd()[:2]
    hap = phase.getHAPvalues(hist)
    inst = hist.getHistEntryValue(["Instrument Parameters"])[0]
    result = {
        "engine": "GSAS-II", "version": G2sc.GSASIIpath.GetVersionNumber() if hasattr(G2sc, "GSASIIpath") else None,
        "instrument_defaults": f"GSAS-II defaultIparms '{label}'; wavelength replaced by the dataset's",
        "cell": {k: cell[k] for k in ("length_a", "length_b", "length_c", "angle_alpha", "angle_beta", "angle_gamma", "volume")},
        "cell_esd": {k: esd.get(k) for k in ("length_a", "length_b", "length_c", "volume")},
        "zero_deg": inst["Zero"][1],
        "displacement_um": hist.SampleParameters["Shift"][0] if job["source"] == "lab" else None,
        "profile": {k: inst[k][1] for k in ("U", "V", "W", "X", "Y", "SH/L") if k in inst},
        "size_um": hap["Size"][1][0], "microstrain": hap["Mustrain"][1][0],
        "stages": stages, "Rwp_percent": hist.get_wR(),
    }
    (out / "result.json").write_text(json.dumps(result, indent=1, default=float))
    x, yo, yc, bg = (hist.getdata(k) for k in ("x", "yobs", "ycalc", "background"))
    with open(out / "fit.csv", "w") as fh:
        fh.write("two_theta,observed,calculated,background\n")
        for row in zip(x, yo, yc, bg):
            fh.write(",".join(f"{v:.6g}" for v in row) + "\n")
    gpx.save()
    print(json.dumps({"a": cell["length_a"], "Rwp": result["Rwp_percent"]}))


if __name__ == "__main__":
    main()
