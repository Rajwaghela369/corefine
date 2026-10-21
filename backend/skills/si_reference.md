# Silicon reference facts (with sources)

| Fact | Value | Source |
|---|---|---|
| Structure | diamond cubic, space group Fd-3m (No. 227), Z = 8 | COD 9008565 |
| Reference structure file | COD **9008565** (Si, a = 5.4307 Å). COD 9008416 is dodecasil 3C SiO₂, **not** Si | crystallography.net |
| Certified lattice parameter, SRM 640f | 0.543 114 4 nm ± 0.000 008 nm (k = 2) at 22.5 °C, i.e. 5.431144 Å ± 0.00008 Å | NIST SRM 640f certificate, 26 Feb 2019, p. 1 |
| Wavelength for 640f data | Cu Kα1, λ = 0.15405929 nm = 1.5405929 Å | certificate, Table 1 |
| Scan temperature | per scan, file tag `_pd_spec_temperature`, about 20.4–20.6 °C | 640f CIFs |

Certificate Table 1 (information values, Cu Kα1) — 2θ in degrees:
(111) 28.441 · (220) 47.301 · (311) 56.120 · (400) 69.127 · (331) 76.373 · (422) 88.026 ·
(511)/(333) 94.947 · (440) 106.702 · (531) 114.085 · (620) 127.535 · (533) 136.882

Allowed reflections for diamond cubic: h, k, l all odd, or all even with h + k + l divisible by 4.
(200) and (222) are forbidden in the spherical-atom model.

The certified value is visible only to the Analyst and the claim checker. The Coder never receives it,
and the scans are stripped of the `data_cell_*` block and the NIST `_calc` fit before staging.
