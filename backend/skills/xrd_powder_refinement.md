# XRD powder refinement of a cubic lattice parameter

Use this for: measure a cubic lattice parameter from a powder XRD scan and compare it to a reference.

## Reading the NIST SRM 640f powder CIFs (exact tags, verified)
pymatgen reads crystal structures, **not** measured patterns. Read scans with gemmi:

```python
doc = gemmi.cif.read(str(path))
meas = next(b for b in doc if b.name.endswith("_meas"))       # measured block
tt = np.array(meas.find_values("_pd_proc_2theta_corrected"), float)
y  = np.array(meas.find_values("_pd_proc_intensity_total"), float)
w  = np.array(meas.find_values("_pd_proc_ls_weight"), float)   # least-squares weights (≈ 1/σ²)
spec = next(b for b in doc if b.name.startswith("pd_spec_"))
temp_c = float(spec.find_value("_pd_spec_temperature"))
```
- Each file is one scan: 28 099 points, 2θ 18.1–157.15°. There are 20 scans; use one unless told otherwise.
- **The files have no wavelength tag.** Take `instrument.wavelength_A` from the dataset's
  `dataset.yaml`. If it is null, stop with `SystemExit` — never fall back to a default.
- Radiation is Cu Kα1 only (Ge 111 Johansson monochromator), so fit **single** peaks, not Kα1/Kα2 doublets.

## Steps
1. Read scan + manifest (above).
2. Expected reflections: `Structure.from_file(<reference cif>)`, then
   `XRDCalculator(wavelength=λ).get_pattern(structure, two_theta_range=(lo, hi))`; keep lines with
   intensity ≥ 0.5 (% of max) and take `hkls[i][0]["hkl"]` (absolute values) as the label.
3. Background: a linear term in each peak's local window is enough for these scans.
4. Fit each peak in a ±0.6° window with `PseudoVoigtModel(prefix="pv_") + LinearModel(prefix="bg_")`
   from lmfit, `weights=np.sqrt(w)`. Record centre, its stderr, FWHM and reduced χ².
5. Refine a and a zero shift with `scipy.optimize.least_squares` on
   `2θ = 2·asin(λ·√(h²+k²+l²) / (2a)) + zero` (degrees), residuals divided by each centre's stderr.
   Covariance = inv(JᵀJ) · (Σr² / dof). Report a, zero and their 1σ uncertainties.
6. Write `peaks.csv` (columns at least: h, k, l, two_theta_calc, two_theta_obs, two_theta_obs_err,
   residual_deg), `metrics.json` with at least `a_refined` (angstrom), `zero_shift` (degree),
   `wavelength` (angstrom, method naming its source), `scan_temperature` (degC), `n_peaks`, and a
   `fit.png` with the pattern (log y) and a residual-vs-2θ panel.

## Common errors
- `Structure.from_file` on a 640f scan → fails or gives nonsense: it is a pattern, not a structure.
- Taking the first data block of a scan → it is the radiation block, not the data. Pick `*_meas`.
- `two_theta_obs_err` None from lmfit when a fit fails → widen the window or improve initial values
  (centre = argmax in window, sigma ≈ 0.02°).
- Peaks above ~130° are broad; keep the window at ±0.6°, not smaller.

## Worked example (the gold analysis, human-checked)
Below is the reference script. On scan `cif_gen_20180612_073551.10.0.tan.cif` it gives
a = 5.430862 ± 0.000035 Å, zero shift −0.0225°, 11 peaks, residuals within ±2.4 mdeg with no trend.
Over all 20 scans the scan-to-scan standard deviation of a is 0.000071 Å.

```python
{{GOLD_ANALYSIS}}
```
