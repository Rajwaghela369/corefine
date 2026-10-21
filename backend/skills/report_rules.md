# Report rules (Analyst)

## The one rule
Every number you write must be copied from the metrics or manifest values you were given, at the
same or fewer decimal places. Never compute a new number (no differences, ratios, percentages, unit
conversions you did yourself) — the orchestrator already computed `difference_from_certified`,
`difference_relative_percent`, `difference_in_sigma` and `within_target`. A code claim checker rejects
any decimal number it cannot trace. If a number you want does not exist, describe it in words.

Cite a metric right after the number: `5.430862 Å [a_refined]`.

## Sections (in this order, as `##` headings)
1. **Result** — refined a with uncertainty, certified a, difference, whether within the success target.
2. **Method** — the steps run, in plain language; wavelength and its source.
3. **Peaks and residuals** — what the residual plot shows; mention any trend or outlier peak.
4. **Classification** — one of the classes below, and why.
5. **Caveats** — what the analysis did not model. Do not invent causes.

## Classification table (applied in order)
| Observation | Classification | Suggested action |
|---|---|---|
| Residuals trend with angle | `missing_geometric_correction` | Rerun with specimen-displacement term |
| Difference within target, no trend | `agreement` | None |
| Beyond target, no trend, wavelength taken from a default | `metadata_issue` | Rerun with wavelength from manifest |
| Peak fit uncertainty large on some peaks | `weak_or_overlapping_peaks` | Exclude those peaks and rerun |
| None of the above | `unexplained` | Flag for a human; give no cause |

You are given a rule-based classification computed in code. Agree with it unless the plot clearly
shows something the rule missed; if you disagree, say so in the Classification section and why.

## Known physics you may state (no numbers)
- A symmetric pseudo-Voigt does not model the asymmetric instrument profile (axial divergence, the
  monochromator band-pass); this can bias peak centres slightly. NIST certified 640f with a full
  fundamental-parameters (FPA) Pawley fit in TOPAS, which models these effects.
- The certified value refers to 22.5 °C; the scans were taken a little cooler (see the scan
  temperature metric). Silicon's thermal expansion makes this a very small effect.
- A zero-shift term absorbs a constant angular offset; specimen displacement gives an offset that varies as cos θ.
