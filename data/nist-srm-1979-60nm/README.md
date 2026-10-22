# NIST SRM 1979 — ZnO crystallite-size standard, 60 nm material, synchrotron scans

4 powder-CIF scans of the 60 nm nominal SRM 1979 zinc oxide, collected at the APS 11-BM beamline, from NIST
dataset mds2-2269 (DOI 10.18434/M32269), `srm_1979_cifs_20201110a.zip` (SHA-256 in
`../nist-srm-1979-15nm/srm_1979_cifs_20201110a.zip.sha256`; one zip holds both sizes). NIST open licence.
File names are `<scan>_60_nm_<bottle>.cif`.

Each file holds the raw 11-BM data, the same data on a corrected angle scale, and NIST's fit:
- `*_meas` (raw): loop `_pd_meas_angle_2theta`, `_pd_meas_intensity_total`, `_pd_meas_ls_weight`.
- `*_corrected_angles_meas`: loop `_pd_proc_2theta_corrected`, `_pd_proc_intensity_total`, `_pd_proc_ls_weight`
  (45 504 points, 2.0–47.5° 2θ). NIST corrected the angle scale by refining SRM 660c collected in the same run.
  **Use this block** for lattice parameters. Two blocks end in `_meas`; pick by the 2θ tag, not the suffix.
- The `data_cell_*` block and the `_calc` block are stripped before files reach the sandbox.

Facts an analysis needs:
- **Wavelength is in the file**: `_diffrn_radiation_wavelength 0.414190` Å, refined by NIST. Monochromatic: no Kα2.
- **Hexagonal wurtzite (P6₃mc)**: refine a and c, not a single cubic parameter.
- **Broad peaks**: these are nanocrystals (the SRM certifies crystallite size), with stacking-fault broadening of
  some reflections (certificate Tables 1–2 mark the unaffected ones). Use wide fitting windows.
- Temperature: the files give 295 with no unit (reads as kelvin).

Certified (certificate Table 4, k = 2, Type A + B, at 22.5 °C): a = 0.324 982 8 nm, c = 0.520 675 0 nm, ± 0.000 020 nm.
These values were certified from laboratory Cu Kα data on thin-film specimens, not from these synchrotron scans,
so a refinement of these files is a comparison, not a reproduction of the certification.
