# NIST SRM 660c — LaB6 line-position standard, raw XRPD scans

20 powder-CIF scans of SRM 660c lanthanum hexaboride, from NIST dataset mds2-2315 (DOI 10.18434/mds2-2315),
`srm_660c_cifs_20201029_081700.zip` (SHA-256 in `srm_660c_cifs_20201029_081700.zip.sha256`). NIST open licence.
NIST divergent-beam diffractometer (Bragg-Brentano, 217.5 mm), scintillator point detector, graphite analyzer.

Each file holds several CIF data blocks. The measured pattern is the block ending `_meas`, with loop
`_pd_proc_2theta_corrected`, `_pd_proc_intensity_total`, `_pd_proc_ls_weight` (5 332 points, 20.3–150.9° 2θ).

Differences from the SRM 640f scans that an analysis must handle:
- **Kα2 is present.** There is no incident-beam monochromator (only a graphite analyzer after the specimen),
  so every reflection is a Cu Kα1/Kα2 doublet. The certificate does not state the Kα2 wavelength; NIST
  modelled the Cu Kα spectrum after Hölzer et al. (certificate ref. 10). `ka2_wavelength_A` is therefore null:
  fit the Kα2 position, or supply a sourced value — never a default.
- **Wavelength**: no wavelength tag. Cu Kα1, λ = 1.5405929 Å, from Table 1 of the certificate.
- Primitive cubic (Pm-3m): every hkl is allowed, so there are many more lines than for silicon.

The files also contain the lattice parameter used for NIST's fit (`data_cell_*` block) and NIST's own fitted
pattern (block ending `_calc`). The backend strips both before files reach the sandbox.

Certified value: a = 4.156826 Å ± 0.00008 Å (k = 2) at 22.5 °C. All 20 scans were taken at 20.85 °C.
Primary paper (cited in each file): "Certification of Standard Reference Material 660c for powder diffraction",
Powder Diffraction (2020), doi:10.1017/S0885715620000068.
