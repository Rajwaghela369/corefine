# Spec v2: verified corrections and implementation decisions

Each item below was checked against the real data or source on 2026-10-21. `docs/SPEC.md` is the
spec exactly as written; this file records where the build differs and why. Raise with the team
before editing the spec itself.

## Errors in the spec (verified)

1. **COD 9008416 is not silicon.** It is dodecasil 3C, a SiO₂ framework, with a = 19.369 Å
   (Könnecke et al., Z. Kristallogr. 201, 1992). Silicon is **COD 9008565** (Wyckoff, a = 5.4307 Å).
   The build uses `cod-9008565-si`.
2. **The 640f files have no wavelength tag.** All 20 scans carry only `_diffrn_radiation_type 'Cu K\a'`,
   a Ge 111 monochromator and a DOI for the emission spectrum. The rule "use the file's wavelength,
   never a default" can never be met as written. The build reads λ from the dataset manifest:
   1.5405929 Å, from **Table 1 of the NIST certificate** (λ = 0.15405929 nm). The source is recorded in
   the manifest and in every `wavelength` metric. A null wavelength stops the run.
3. **No Kα2 doublet.** The Ge 111 Johansson incident-beam monochromator removes Kα2, so the build fits
   single peaks.
4. **`temperature_C: 22.5` is the certificate's reference temperature, not the scan temperature.** Each
   scan records its own (`_pd_spec_temperature`, 20.36–20.56 °C). The manifest leaves it null and
   scripts read it per scan.

## Problems the spec does not mention

5. **The answer is inside the input.** Every scan file contains `data_cell_SRM_640f` with
   `_cell_length_a 5.431144`, plus a `*_calc` block holding NIST's own fit. The claim checker cannot
   catch a copied answer, because the number really is in a file. The backend strips both blocks
   (`app/storage/sanitize.py`) before staging, and `reference_values` is hidden from the Planner
   and Coder.
6. **2θ is already corrected** (`_pd_proc_2theta_corrected`), and each scan records its specimen
   displacement. The zero shift refines to about −0.022°. On scan 1 the residuals show no trend
   (t = −0.08). The demo story "residuals trend, so rerun with a displacement term" will probably not
   happen with this data.
7. **Uncertainty.** The certificate gives ± 0.000008 nm (k = 2), i.e. ± 0.00008 Å.

## Gate 1 result (gold analysis, `backend/skills/examples/gold_analysis.py`)

| | value |
|---|---|
| scan 1 refined a | 5.430862 ± 0.000035 Å, zero shift −0.0225°, 11 peaks |
| all 20 scans | mean 5.430868 Å, standard deviation 0.000071 Å, range 5.430712–5.430986 Å |
| difference from certified | mean −0.000276 Å; every scan within the 0.0005 Å target |
| residuals | within ±2.4 mdeg, no angle trend |

The constant −0.00028 Å offset is about 3.5× the certificate uncertainty. The likely cause is that a
symmetric pseudo-Voigt does not model the asymmetric instrument profile, which NIST's FPA/TOPAS
certification does. This is a hypothesis, not tested.

## Implementation decisions

- **Python 3.14.8 for the backend**, not 3.11: it is the newest release where every dependency has
  wheels. 3.15.0 (released 2026-10-09) has no wheels yet for gemmi, parts of the langchain stack or
  fastembed's dependencies. **The sandbox snapshot uses Python 3.13**, the newest series Daytona's
  `Image.debian_slim` accepts.
- **Local mode** (`COREFINE_MODE=local`): disk instead of S3, SQLite instead of Neon, local Qdrant,
  a subprocess runner instead of Daytona. Used for development, tests and the
  venue-Wi-Fi fallback. Cloud mode uses the managed services.
- **The local runner is not network-isolated.** There is no Docker and unprivileged user namespaces are
  blocked on the dev laptop, so `LocalDockerRunner` became a subprocess runner. A sitecustomize hook
  refuses socket connections; this stops accidental network use but is not a security boundary.
  `DaytonaRunner` creates sandboxes with `network_block_all=True`.
- **Each step gets a clean `outputs/`.** Earlier outputs a step declares in `uses_previous_outputs`
  are staged into `inputs/previous/`, which keeps the "read only from inputs" contract. Per-step
  files go to `runs/<id>/outputs/step_NN/`; the latest version of each also goes to `runs/<id>/outputs/`.
- **Comparison numbers are computed in code**, not by the Analyst: `difference_from_certified`,
  `difference_relative_percent`, `difference_in_sigma`, `within_target`. They are written to
  `outputs/comparison.json` and ingested like any other metric. The spec's classification table is
  applied in code first, and the Analyst agrees or explains why not.
- **What the claim checker checks:** every number with a decimal point or an exponent must equal an
  allowed value (metrics, uncertainties, manifest values) when rounded to the printed precision.
  Power-of-ten unit changes (Å↔nm) are allowed only for numbers with ≥ 3 significant digits.
  Integers are not checked (hkl, counts, dates). If the report fails, the Analyst gets one retry
  with the untraced numbers listed.
- **`start_run` in chat only proposes a run.** It starts only when the user clicks Confirm in the UI.
- **The schema is created with SQLAlchemy `create_all`** (idempotent), not Alembic migrations.
- **shadcn/ui-style components are hand-written** with Tailwind; the shadcn generator was not run.
- **Langfuse removed.** Tracing was dropped on request (2026-10-22); `/health` checks five services
  and no `LANGFUSE_*` settings exist. The spec items about Langfuse traces no longer apply.
- **Theory ↔ Experiment removed** (2026-10-22, on request): the `/bridge` endpoints, the comparison page and the
  co-pilot's `theory_vs_experiment` tool are gone. The per-run reasoning story used by the XRD *Reasoning* tab moved
  to `app/orchestration/story.py`; the Storage pattern comparison (`/xrd/compare`) stays.
- **LangChain and LangGraph throughout** (2026-10-22): every Claude call is a LangChain `ChatAnthropic` model from
  `app/agents/llm.py` (structured output via `with_structured_output(method="json_schema")`, with thinking, effort,
  streaming and server-side fallbacks as before). GSAS-II/MAUD runs and the DFT workflow became LangGraph graphs like
  the agent run graph; the DFT workflow pauses before its runs (checkpointer) and resumes them in the background.
  The raw Anthropic SDK is used only for the token-free health check and its exception types.
