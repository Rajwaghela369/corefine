# XRD refinement on the other NIST standards: LaB6 (SRM 660c) and ZnO (SRM 1979)

Use this together with `xrd_powder_refinement.md` (same steps, same outputs) when the measured dataset is
`nist-srm-660c` or `nist-srm-1979-15nm` / `nist-srm-1979-60nm`. Only what differs from the 640f recipe is here.
Read `instrument` in the dataset's `dataset.yaml` first; never replace a null value with a default.

## SRM 660c, LaB6 (cubic, Pm-3m) — Kα1/Kα2 doublets
- Reading: identical tags to 640f (`*_meas` block, `_pd_proc_2theta_corrected`, `_pd_proc_intensity_total`,
  `_pd_proc_ls_weight`). 5 332 points, 20.3–150.9° 2θ. Temperature: `_pd_spec_temperature` in `pd_spec_*`.
- `instrument.wavelength_A` is Cu **Kα1** (from the certificate). `instrument.ka2_present` is true: there is no
  incident-beam monochromator, so every reflection is a Kα1 + Kα2 doublet.
- `instrument.ka2_wavelength_A` is null (the certificate does not state it). Do not type in a Kα2 wavelength.
  Fit each reflection as **two** pseudo-Voigts (`prefix="k1_"`, `prefix="k2_"`) plus a linear background, with
  the Kα2 centre free but above the Kα1 centre, the two widths tied (`k2_sigma` expr `k1_sigma`), and both
  amplitudes free. Use only the Kα1 centre in the lattice refinement; report the fitted Kα2 offsets in peaks.csv.
- The doublet splitting grows with 2θ; widen the window with angle (e.g. ±0.6° at low angle up to ±1.0° above
  120°) so both components stay inside it.
- Primitive cubic: every hkl is allowed, so lines are dense. Keep reflections whose expected Kα1 position is at
  least one window width away from a neighbour, or fit neighbours together in one window.
- Refinement: as for 640f, `2θ = 2·asin(λ·√(h²+k²+l²) / (2a)) + zero`. Metric names as for 640f (`a_refined`).

## SRM 1979, ZnO (hexagonal wurtzite, P6₃mc) — synchrotron, a and c
- **Two blocks end in `_meas`.** The raw one uses `_pd_meas_angle_2theta` / `_pd_meas_intensity_total`; the one
  to use is `*_corrected_angles_meas` with `_pd_proc_2theta_corrected`, `_pd_proc_intensity_total`,
  `_pd_proc_ls_weight` (NIST corrected its angle scale against SRM 660c). Select the block by the presence of
  `_pd_proc_2theta_corrected`, not by its suffix. 45 504 points, 2.0–47.5° 2θ.
- Wavelength: `instrument.wavelength_A` (0.41419 Å, from `_diffrn_radiation_wavelength` in the file). Monochromatic,
  no Kα2: single peaks.
- Temperature: the files give `_pd_spec_temperature 295` with no unit. Write `scan_temperature` with unit `K`
  and say in its method that the unit is inferred, or omit it; do not convert silently.
- The powder is nanocrystalline (15 nm or 60 nm): peaks are broad and some are stacking-fault broadened. Use
  windows of several FWHM; estimate FWHM from the strongest peak before choosing windows.
- Expected reflections: `XRDCalculator(wavelength=λ)` on the ZnO reference structure (`cod-2300450-zno`),
  labels from `hkls[i][0]["hkl"]` — for hexagonal cells pymatgen gives four indices (h, k, i, l); use h, k, l.
- Refinement: two lattice parameters and a zero shift,
  `1/d² = 4(h² + hk + k²) / (3a²) + l² / c²`, `2θ = 2·asin(λ / (2d)) + zero`.
  Write `a_refined` and `c_refined` (angstrom) with 1σ uncertainties, plus `zero_shift`, `wavelength`, `n_peaks`.
- peaks.csv needs h, k, l, two_theta_calc, two_theta_obs, two_theta_obs_err, residual_deg as before.
