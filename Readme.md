# CoRefine

CoRefine turns raw X-ray diffraction data into an analysed result. A researcher describes the
experiment in plain language, and agents plan the analysis, write and run the code, and explain
the result. **Every number in the result is traced back to a file produced by executed code.**

The first experiment it runs: measure silicon's lattice parameter *a* from the NIST SRM 640f
powder scans and compare it with the certified value, 5.431144 Å ± 0.00008 Å at 22.5 °C.

## How a run works

```
prompt + selected datasets
   │
   ▼
Planner (Claude) ──▶ plan.json: 1–6 steps, each with declared output files
   │
   ▼  for each step
Coder (Claude) ──▶ step_NN_<name>.py ──▶ sandbox (Daytona, no network) ──▶ outputs + logs
   │                     ▲                                                  │
   │                     └──── retry (max 2): code + stderr tail + reason ◀─┤ output checker (code)
   ▼                                                                        │
comparison metrics + rule-based classification (code) ◀─────────────────────┘
   │
   ▼
Analyst (Claude, reads the plot) ──▶ report.md ──▶ claim checker (code): every decimal number traced?
```

Three ideas keep it honest:

1. **Agents write code; code produces numbers.** The LLMs never put a number in a report that is
   not in `metrics.json`, a manifest or a database row. Differences, percentages and the success
   test are computed by the orchestrator, not the model.
2. **The Coder never sees the answer.** The certified value is hidden from the Planner and Coder, and
   the NIST files are stripped of the certified lattice parameter and NIST's own fit before staging.
3. **Everything is in files.** Each run folder holds the plan, every attempt's code, stdout/stderr,
   outputs, an experiment log and the report. Neon indexes it and the UI shows it.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.14 itself) and Node ≥ 20.19.

```bash
# backend
cd backend
cp .env.example .env                 # fill in keys, or keep COREFINE_MODE=local
uv sync --extra embed                # Python 3.14 env with the backend and science libraries
uv run python scripts/fetch_data.py  # NIST 640f scans (SHA-256 checked) + COD 9008565
uv run python scripts/setup.py       # tables, bucket prefixes, Qdrant collections, seed datasets
uv run python scripts/setup.py --snapshot   # cloud only, once: Daytona snapshot with sandbox libs
uv run uvicorn app.main:app --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

`GET /health` (or `http://localhost:5173/api/health`) checks Neon, S3, Qdrant, Daytona, Anthropic and
Langfuse. In local mode it names the local stand-in it is using for each.

### Modes

| | `COREFINE_MODE=local` | `COREFINE_MODE=cloud` |
|---|---|---|
| Files | `backend/.local/bucket/` | AWS S3 |
| Database | SQLite | Neon Postgres |
| Search | local Qdrant + FastEmbed | Qdrant Cloud |
| Sandbox | subprocess (network blocked by hook, **not** isolated) | Daytona, `network_block_all` |
| Tracing | off | Langfuse Cloud |
| LLM | Anthropic API (key needed) | Anthropic API |

In cloud mode, a missing key stops startup and the error names it.

## Environment keys

See `backend/.env.example`: `ANTHROPIC_API_KEY`, `MODEL_MAIN`, `MODEL_FAST`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET`, `DATABASE_URL`, `QDRANT_URL`, `QDRANT_API_KEY`,
`EMBED_PROVIDER`, `EMBED_MODEL`, `EMBED_DIM`, `DAYTONA_API_KEY`, `DAYTONA_SNAPSHOT`,
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.

## Tests

```bash
cd backend && uv run pytest     # 38 tests; LLM mocked, sandbox and checks real
```

They cover the contracts, the step contract and claim checker, sanitizing, the gold analysis
through the runner, network blocking, timeouts and output limits, a full run that recovers from a
broken first script and an invented number in the report, the dataset API's refusals, and the
SSE stream.

## Gold result (Gate 1)

`backend/skills/examples/gold_analysis.py`, checked by hand, on the 20 SRM 640f scans: mean
a = 5.430868 Å, scan-to-scan standard deviation 0.000071 Å. Every scan is within the 0.0005 Å
target, about 0.00028 Å below the certified value. See `docs/SPEC_CORRECTIONS.md` for this result,
the spec errors found while building, and the design decisions.

## Data sources

- NIST SRM 640f raw XRPD data, mds2-2251, [doi:10.18434/M32251](https://doi.org/10.18434/M32251), NIST open licence.
- NIST SRM 640f certificate (26 Feb 2019): certified value and the Table 1 wavelength.
- COD 9008565, silicon (Wyckoff), [crystallography.net](https://www.crystallography.net/cod/9008565.html).

## DFT inputs for any code (Lab → DFT inputs)

`backend/app/dft/` turns a structure into checked ground-state inputs for every DFT code configured
on the server. Code writes every input; the LLM only turns a plain-language request into typed
settings. It is built to be shared: no machine-specific paths in the code, and each code is a plug-in.

**Codes are adapters.** `app/dft/codes/` holds one module per code implementing `CodeAdapter`
(`codes/base.py`): whether the code is usable on this server, which functionals it maps, how to write
its input, how to read that input back the way the code itself will, how to launch it and how to
parse its results. Register it in `codes/__init__.py`, and the request API, the checks, the runner
and the UI pick it up automatically. Shipped: exciting (FP-(L)APW+lo), Questaal (FP-LMTO),
Quantum ESPRESSO (pw.x; pseudopotentials from your `QE_PSEUDO_DIR`, cutoffs from an SSSP JSON or the
pseudopotential headers, never guessed) and VASP (POSCAR/KPOINTS/INCAR; the licensed POTCAR is
assembled only from your own `VASP_PP_PATH`). All codes use the same Γ-centred k-mesh. Settings a request does not specify are left at
the code's own documented defaults, and the adapter reports them.

```bash
cd backend
uv run python scripts/dft_inputs.py --source cod:9008565 --xc PBE --kmesh 2 2 2 --out runs/si-pbe
uv run python scripts/dft_inputs.py --source mp:mp-149 --codes exciting --out runs/si-mp
uv run python scripts/dft_inputs.py --prompt "DFT PBE for Si (mp-149), simple 2x2x2 k-mesh, normal inputs" --out runs/si
```

Sources: a local `.cif`, `cod:<id>`, `mp:<mp-id>` (Materials Project via its public OPTIMADE endpoint,
no key) or `dataset:<id>` (a structure in CoRefine storage). The structure is reduced to the standard
primitive cell (spglib). Then every input is read back and compared with the source and with the other
codes: formula, space group, volume per atom, nearest-neighbour distance, k-mesh, functional, plus
each code's own checks (exciting: schema validation; Questaal: `lmchk` symmetry and sphere overlap).
Output: one folder per code, plus `checks.json`, `provenance.json` and `SUMMARY.md`, downloadable as a zip.

### Codes for people who have nothing installed

The DFT panel offers one-click installs of open-source codes and their data, into
`backend/.local/tools/` (no root, no system changes), each verified before use:

| Tool | What | Source | Licence | Check |
|---|---|---|---|---|
| micromamba | package installer (single binary) | official mamba-org GitHub release | BSD-3 / MIT | SHA-256 from the release |
| Quantum ESPRESSO 7.6 | `pw.x` and friends | conda-forge `qe` (OpenMPI build) | GPL-2.0 | binary present, `ldd` finds every library |
| SSSP 1.3 PBE / PBEsol efficiency | pseudopotentials + recommended cutoffs | Materials Cloud Archive | CC-BY 4.0 | MD5 from the archive's file listing; per-file MD5 rechecked in every input set |

Installed codes become runnable locally with no configuration (an implicit `local` target). exciting and
Questaal are open source but not packaged on conda-forge (build from source and set `EXCITING_BIN` /
`QUESTAAL_BIN`); VASP is commercial and cannot be installed, so only its inputs are generated.
Note: the conda-forge `qe` 7.6 build links ELPA without declaring it, so the recipe requests ELPA explicitly.

### Running the calculations

Where things run is per-user configuration: copy `backend/compute.example.yaml` to `compute.yaml`
(not committed). Each *target* lists the codes it can run:

- `kind: local`: runs the program in the set's folder with a thread limit and timeout. Codes whose
  SCF can continue from saved density (Questaal) are restarted automatically if they stop unconverged.
- `kind: slurm`: copies the folder to your cluster over SSH (your own `~/.ssh/config` and keys, no
  passwords stored), fills in *your* job-script template, submits with `sbatch`, polls `sacct`, copies
  results back. The UI asks for confirmation before any cluster submission.

Results come only from each code's own output files: convergence, SCF iterations, gap, Fermi level,
total energy. Runs done elsewhere can be imported (upload the output files) and are parsed the same
way. Run state lives in `<set>/runs/<code>.json`.

Configure the codes you have in `backend/.env`: `EXCITING_ROOT` (exciting tree: species + schema),
`QUESTAAL_BIN` (blm, lmfa, lmchk) and, for Spack builds, `QUESTAAL_LIB_ROOT`; `QE_PSEUDO_DIR`;
`VASP_PP_PATH`. Codes left unset are shown as unavailable, with the reason.
