"""Gold reference analysis: refine the Si lattice parameter from one NIST SRM 640f scan.

Follows the step contract (see skills/step_contract.md): reads only $COREFINE_WORK/inputs,
writes only $COREFINE_WORK/outputs, writes metrics.json, prints a one-line summary last.

Inputs:
  inputs/nist-srm-640f/dataset.yaml + raw/*.cif   (sanitized: no cell block, no _calc block)
  inputs/cod-9008565-si/dataset.yaml + raw/9008565.cif
Env:
  SCAN  optional file name of the scan to use (default: first in sorted order)
"""

import json
import math
import os
from pathlib import Path

import gemmi
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from lmfit.models import LinearModel, PseudoVoigtModel
from pymatgen.analysis.diffraction.xrd import XRDCalculator
from pymatgen.core import Structure
from scipy.optimize import least_squares

WORK = Path(os.environ.get("COREFINE_WORK", "/work"))
IN, OUT = WORK / "inputs", WORK / "outputs"
OUT.mkdir(parents=True, exist_ok=True)

# --- 1. Read scan + metadata -------------------------------------------------
manifest = yaml.safe_load((IN / "nist-srm-640f" / "dataset.yaml").read_text())
wavelength = manifest["instrument"]["wavelength_A"]
if wavelength is None:
    raise SystemExit("manifest has no wavelength_A; refusing to use a default")
scans = sorted((IN / "nist-srm-640f" / "raw").glob("*.cif"))
scan = next(s for s in scans if s.name == os.environ["SCAN"]) if os.environ.get("SCAN") else scans[0]

doc = gemmi.cif.read(str(scan))
meas = next(b for b in doc if b.name.endswith("_meas"))
tt = np.array(meas.find_values("_pd_proc_2theta_corrected"), dtype=float)
counts = np.array(meas.find_values("_pd_proc_intensity_total"), dtype=float)
ls_weight = np.array(meas.find_values("_pd_proc_ls_weight"), dtype=float)
spec = next(b for b in doc if b.name.startswith("pd_spec_"))
temp_c = float(spec.find_value("_pd_spec_temperature"))

# --- 2. Expected reflections from the reference structure --------------------
structure = Structure.from_file(IN / "cod-9008565-si" / "raw" / "9008565.cif")
pattern = XRDCalculator(wavelength=wavelength).get_pattern(structure, two_theta_range=(tt.min() + 1, tt.max() - 1))
reflections = []
for two_theta, intensity, hkls in zip(pattern.x, pattern.y, pattern.hkls):
    if intensity < 0.5:  # % of strongest; drops structure-factor-forbidden (222)-type lines
        continue
    h, k, l = (abs(i) for i in hkls[0]["hkl"])
    reflections.append({"h": h, "k": k, "l": l, "two_theta_calc": float(two_theta)})

# --- 3 + 4. Local linear background + pseudo-Voigt per peak ------------------
rows = []
half_window = 0.6
for ref in reflections:
    m = np.abs(tt - ref["two_theta_calc"]) < half_window
    x, y, w = tt[m], counts[m], np.sqrt(ls_weight[m])
    model = PseudoVoigtModel(prefix="pv_") + LinearModel(prefix="bg_")
    params = model.make_params(
        pv_center=x[np.argmax(y)], pv_sigma=0.02, pv_amplitude=(y.max() - y.min()) * 0.05,
        pv_fraction=0.5, bg_slope=0.0, bg_intercept=float(np.median(y[:20])),
    )
    params["pv_fraction"].set(min=0, max=1)
    params["pv_sigma"].set(min=1e-4, max=0.3)
    params["pv_center"].set(min=x.min(), max=x.max())
    fit = model.fit(y, params, x=x, weights=w)
    center = fit.params["pv_center"]
    rows.append({
        **ref,
        "two_theta_obs": center.value,
        "two_theta_obs_err": center.stderr if center.stderr is not None else float("nan"),
        "fwhm": fit.params["pv_fwhm"].value,
        "redchi": fit.redchi,
    })
peaks = pd.DataFrame(rows)

# --- 5. Least-squares refinement of a + zero shift ---------------------------
q = np.sqrt(peaks.h**2 + peaks.k**2 + peaks.l**2).to_numpy()
obs = peaks.two_theta_obs.to_numpy()
sig = peaks.two_theta_obs_err.to_numpy()


def two_theta_model(p):
    a, zero = p
    return np.degrees(2 * np.arcsin(wavelength * q / (2 * a))) + zero


res = least_squares(lambda p: (two_theta_model(p) - obs) / sig, x0=[5.43, 0.0])
dof = len(obs) - 2
s2 = float(np.sum(res.fun**2) / dof)
cov = np.linalg.inv(res.jac.T @ res.jac) * s2
(a_ref, zero), (a_err, zero_err) = res.x, np.sqrt(np.diag(cov))
peaks["two_theta_fit"] = two_theta_model(res.x)
peaks["residual_deg"] = peaks.two_theta_obs - peaks.two_theta_fit
peaks["d_obs_A"] = wavelength / (2 * np.sin(np.radians((obs - zero) / 2)))
slope = float(np.polyfit(obs, peaks.residual_deg, 1)[0])

# --- 6. Outputs --------------------------------------------------------------
peaks.to_csv(OUT / "peaks.csv", index=False)
metrics = [
    {"name": "a_refined", "value": float(a_ref), "unit": "angstrom", "uncertainty": float(a_err),
     "method": "weighted LSQ of pseudo-Voigt centres, a + zero shift"},
    {"name": "zero_shift", "value": float(zero), "unit": "degree", "uncertainty": float(zero_err),
     "method": "same fit"},
    {"name": "wavelength", "value": wavelength, "unit": "angstrom", "uncertainty": None,
     "method": f"manifest: {manifest['instrument'].get('wavelength_source', 'unknown')}"},
    {"name": "scan_temperature", "value": temp_c, "unit": "degC", "uncertainty": None,
     "method": "file tag _pd_spec_temperature"},
    {"name": "n_peaks", "value": len(peaks), "unit": "count", "uncertainty": None, "method": "fitted reflections"},
    {"name": "reduced_chi2_refinement", "value": s2, "unit": "dimensionless", "uncertainty": None,
     "method": "sum of squared normalised residuals / dof"},
    {"name": "residual_slope", "value": slope, "unit": "degree_per_degree", "uncertainty": None,
     "method": "linear fit of residual vs 2theta (trend check)"},
]
(OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), height_ratios=[3, 1], constrained_layout=True)
ax1.plot(tt, counts, lw=0.6, label=f"measured ({scan.name})")
for r in peaks.itertuples():
    ax1.axvline(r.two_theta_fit, color="tab:red", lw=0.5, alpha=0.6)
ax1.set(yscale="log", ylabel="counts", title=f"SRM 640f: a = {a_ref:.6f} ± {a_err:.6f} Å")
ax1.legend()
ax2.errorbar(peaks.two_theta_obs, peaks.residual_deg * 1e3, yerr=peaks.two_theta_obs_err * 1e3, fmt="o")
ax2.axhline(0, color="k", lw=0.5)
ax2.set(xlabel="2θ (deg)", ylabel="residual (mdeg)")
fig.savefig(OUT / "fit.png", dpi=110)

print(f"a_refined={a_ref:.6f}+/-{a_err:.6f} A zero={zero:.5f} deg peaks={len(peaks)} scan={scan.name}")
