# NIST SRM 640f — raw XRPD scans

20 powder-CIF scans of SRM 640f silicon, from NIST dataset mds2-2251 (DOI 10.18434/M32251),
`srm640f_cifs_20200601a.zip` (SHA-256 in `srm640f_cifs_20200601a.zip.sha256`). NIST open licence.

Each file holds several CIF data blocks. The measured pattern is the block ending `_meas`, with loop
`_pd_proc_2theta_corrected`, `_pd_proc_intensity_total`, `_pd_proc_ls_weight` (28 099 points, 18.1–157.15° 2θ).

Things the files do *not* say, and where the values come from instead:
- **Wavelength**: no wavelength tag. Cu Kα1, λ = 1.5405929 Å, from Table 1 of the certificate.
- **Kα2**: removed by the Ge 111 Johansson incident-beam monochromator, so fit single peaks.

The files also contain the certified lattice parameter (`data_cell_*` block) and NIST's own fitted pattern
(block ending `_calc`). The backend strips both before files reach the sandbox, so the Coder cannot copy the answer.

Certified value: a = 5.431144 Å ± 0.00008 Å (k = 2) at 22.5 °C. Scans were taken at about 20.5 °C.
