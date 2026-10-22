# LaB6 and ZnO reference facts (with sources)

| Fact | Value | Source |
|---|---|---|
| LaB6 structure | primitive cubic, Pm-3m (No. 221), 1 formula unit per cell | COD 1000057 |
| LaB6 reference structure | COD **1000057** (a = 4.1570 Å, single crystal, Kristallografiya 1986) | crystallography.net |
| Certified lattice parameter, SRM 660c | 0.415 682 6 nm ± 0.000 008 nm (k = 2) at 22.5 °C, i.e. 4.156826 Å ± 0.00008 Å | NIST SRM 660c certificate, 29 Oct 2015, p. 1 |
| Wavelength for 660c data | Cu Kα1, λ = 0.154 059 29 nm = 1.5405929 Å; Kα2 present (no incident-beam monochromator) | certificate, Table 1; files |
| 660c scan temperature | 20.85 °C in all 20 scans (`_pd_spec_temperature`) | 660c CIFs |
| ZnO structure | wurtzite, P6₃mc (No. 186), 2 formula units per cell | COD 2300450 |
| ZnO reference structure | COD **2300450** (a = 3.249308 Å, c = 5.205709 Å, powder, 298 K, J. Appl. Cryst. 47 (2014) 659) | crystallography.net |
| Certified lattice parameters, SRM 1979, 15 nm | a = 0.324 966 4 nm, c = 0.520 833 0 nm, each ± 0.000 030 nm (k = 2, Type A + B), at 22.5 °C | NIST SRM 1979 certificate, 04 June 2021, Table 3 |
| Certified lattice parameters, SRM 1979, 60 nm | a = 0.324 982 8 nm, c = 0.520 675 0 nm, each ± 0.000 020 nm (k = 2, Type A + B), at 22.5 °C | certificate, Table 4 |
| Wavelength for 1979 data | 0.41419 Å, APS 11-BM, refined by NIST (`_diffrn_radiation_wavelength`) | 1979 CIFs |

Caveats to state in a report:
- SRM 1979's lattice parameters were certified from laboratory Cu Kα data on thin-film specimens, not from the
  11-BM synchrotron scans in CoRefine. A refinement of these scans is a comparison with the certified value,
  not a reproduction of the certification.
- SRM 1979 certifies crystallite size (mean column lengths); its peaks are intentionally broad.
- The 1979 files give the temperature as 295 with no unit; treat the unit as unknown unless the run says otherwise.
- 660c: a fit with single peaks instead of Kα1/Kα2 doublets biases the centres high in 2θ, so a comes out low.
