# CoRefine

**Measure a crystal. Predict the same crystal with six DFT codes. See both on one screen, with
every number traced to the file that produced it.**

Experimentalists and theorists usually look at the same material through different windows: one
has a diffraction scan and a refinement, the other has a folder of input files and a total energy.
CoRefine puts both in one place:

| | What it does | Who it's for |
|---|---|---|
| **Experiment · XRD** | Agents plan an analysis of raw powder-diffraction data, write the code, run it in a sandbox and explain the result. | anyone with a scan |
| **Theory · DFT** | Pick a material. CoRefine plans the calculation, writes checked inputs for six codes, installs the open-source ones, runs them on your laptop and shows each code's band gap and convergence. | anyone who wants a DFT number they can trust, including people with no DFT code installed yet |
| **Theory ↔ Experiment** | The lattice constant from the scan next to the lattice constant from each code, with the differences, and the scan overlaid with what each model predicts. | both, in the same meeting |

One rule runs through all three: **language models plan and explain, code produces numbers.** No
LLM writes an input file, and no number reaches a report unless a file or a database row backs it.

---

## Contents

1. [Try it on your laptop](#try-it-on-your-laptop)
2. [Experiment: agentic XRD refinement](#experiment-agentic-xrd-refinement)
3. [Theory: DFT for every code, for everyone](#theory-dft-for-every-code-for-everyone)
4. [Theory ↔ Experiment](#theory--experiment)
5. [Where the calculations run](#where-the-calculations-run)
6. [Configuration](#configuration)
7. [Tests](#tests)
8. [Data sources and credits](#data-sources-and-credits)

---

## Try it on your laptop

You need two free tools: [uv](https://docs.astral.sh/uv/) (it fetches Python 3.14 itself) and
Node ≥ 20.19. **No DFT code and no API key are required.**

```bash
git clone https://github.com/Rajwaghela369/corefine.git
cd corefine && git checkout theory

# backend
cd backend
cp .env.example .env                 # works as-is: COREFINE_MODE=local, no cloud accounts
uv sync --extra embed                # Python 3.14 env with the backend and science libraries
uv run python scripts/fetch_data.py  # NIST 640f/660c/1979 scans (SHA-256 checked) + COD structures
uv run python scripts/setup.py       # tables, local bucket, Qdrant collections, seed datasets
uv run uvicorn app.main:app --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                          # open http://localhost:5173
```

Then try this five-minute tour:

1. **Lab → Theory · DFT.** The code cards show what runs on your machine. Click **install** on
   Quantum ESPRESSO. CoRefine downloads it and the SSSP pseudopotentials into
   `backend/.local/tools/`, with no admin rights and nothing else on your system touched.
2. Search `GaAs`, pick the stable phase and click **Generate**. You get inputs for every code, each
   one read back and checked.
3. Open **Runs** and run it. Each code's band gap appears under **Overview**; **Theory ↔ Experiment** shows how each step went.
4. **Lab → Experiment · XRD** has the silicon scans. **Lab → Theory ↔ Experiment** puts both sides
   together.

What works where:

| | |
|---|---|
| Linux | Tested. |
| macOS | Should work: the installer has Intel and Apple-silicon builds. Not tested yet. |
| Windows | Use WSL (Linux inside Windows). The installer has no native Windows builds. |
| API keys | All optional. An `ANTHROPIC_API_KEY` turns on the XRD agents and Claude's review of DFT plans. An `MP_API_KEY` gives richer Materials Project data. |

---

## Experiment: agentic XRD refinement

CoRefine turns raw X-ray diffraction data into an analysed result. A researcher describes the
experiment in plain language, and agents plan the analysis, write and run the code, and explain
the result. **Every number in the result is traced back to a file produced by executed code.**

The first experiment it runs: measure silicon's lattice parameter *a* from the NIST SRM 640f
powder scans and compare it with the certified value, 5.431144 Å ± 0.00008 Å at 22.5 °C.

### Datasets

Three NIST powder-diffraction standards, each with its certificate values, licence and checksum in
`dataset.yaml`, and a COD structure to index it. They were chosen because each one tests the analysis
differently:

| Dataset | Material | Scans | What it tests | Certified (22.5 °C, k = 2) |
|---|---|---|---|---|
| `nist-srm-640f` | Si, cubic | 20, Cu Kα1 (Ge 111 monochromator) | single peaks, one lattice parameter | a = 5.431144 ± 0.00008 Å |
| `nist-srm-660c` | LaB6, primitive cubic | 20, Cu Kα (graphite analyzer) | **Kα1/Kα2 doublets**, dense lines | a = 4.156826 ± 0.00008 Å |
| `nist-srm-1979-15nm` | ZnO, hexagonal | 5, synchrotron 0.41419 Å (APS 11-BM) | **two lattice parameters**, broad nanocrystal peaks | a = 3.249664, c = 5.208330 ± 0.00030 Å |
| `nist-srm-1979-60nm` | ZnO, hexagonal | 4, synchrotron 0.41419 Å | same, narrower peaks | a = 3.249828, c = 5.206750 ± 0.00020 Å |

Reference structures: COD 9008565 (Si), 1000057 (LaB6), 2300450 (ZnO). The wavelengths come from the
certificates (640f, 660c) or from the files themselves (1979). The 660c certificate gives no Kα2
wavelength, so the manifest leaves it null and the skill tells the Coder to fit it. Each README lists
what the files do *not* say. SRM 1979's lattice parameters were certified from laboratory data, not from
these synchrotron scans, so a refinement of them is a comparison, not a reproduction.

### The co-pilot

The chat answers questions from both sides of the project: a data curator's (is this dataset documented,
licensed, traceable?) and a scientist's (does the measurement agree with the simulation, and what next?).
It reads only through tools, and every number it states must come from a tool result in the same turn:

- runs: `list_runs`, `get_run`, `query_metrics`, `read_artifact`, `compare_runs`, `search_knowledge`;
- data: `list_datasets`, `get_dataset`, `check_dataset_metadata` (code checks for a persistent identifier,
  licence, checksum, wavelength and its source, temperature, reference-value source and uncertainty;
  it lists what is present and missing, it does not grade FAIRness);
- theory: `list_dft_sets`, `get_dft_set` (request, defaults, checks, results, studies);
- both: `theory_vs_experiment`, `compare_pattern`, `identify_phase`;
- `start_run` proposes a run; nothing starts until you confirm.

It says plainly what CoRefine cannot do yet: ARPES and band-structure comparison, surface slabs,
supercells and defect models.

### How a run works

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

### Choose the engine: agents, GSAS-II or MAUD

*Experiment · XRD* is laid out like *Theory · DFT*. On the left are the form (measured scan, reference structure,
analysis tools) and the list of analyses. On the right, the selected analysis has a header, summary cells and the
tabs **Overview**, **Reasoning**, **Compare tools**, **Plots**, **Data** and **Report**. **Reasoning** shows each tool's
steps top to bottom: who acted (language model, code or program), each decision taken before fitting and why
(wavelength source, Kα2, geometry, what is refined and what stays fixed), what each refinement stage changed in
Rwp, and the result against the certificate.

The same scan can be refined three ways, chosen under **Analysis tools**:

- **Agents (Python)**: Claude plans the analysis and writes the fitting code (peak positions, then the lattice
  parameter). It needs an Anthropic key.
- **GSAS-II** (APS): Rietveld refinement with a fixed recipe written by code. The stages are background and scale, then
  cell and specimen displacement, then the Gaussian instrument profile and asymmetry, then isotropic size and
  microstrain. Starting instrument values are GSAS-II's own defaults (`CuKa lab data`, or `APS 30keV 11BM`) with the
  dataset's wavelength. Zero is not refined, because the scans' 2θ is already calibrated by NIST.
- **MAUD** (Lutterotti): Rietveld refinement in MAUD's batch mode, starting from MAUD's own default analysis. Its wizard
  steps are background and scale, then cell and basic parameters, then microstructure.

Pick more than one tool and each gets its own run, all in one comparison group. **Compare tools** shows three things.
The first is each tool's lattice parameter against the certificate (with 1σ bars and the ±0.0005 Å target). The second
is Rwp after each refinement stage. The third overlays the measured scan, GSAS-II's calculated pattern and each tool's
reflection positions from its refined cell. A table next
to it lists every refined value against the certificate. Both programs install from the Experiment form: GSAS-II is
built from a pinned commit (it is on neither PyPI nor conda-forge), and MAUD comes from its GitHub release with the
SHA-256 GitHub records for it.

One scan each, run on this laptop on 22 Oct 2026:

| Dataset | GSAS-II a (Å) | Δ certified | Rwp | MAUD a (Å) | Δ certified | Rwp |
|---|---|---|---|---|---|---|
| Si, SRM 640f | 5.431256 ± 0.000014 | +0.00011 | 21.7 % | 5.43137 ± 0.00013 | +0.00023 | 73.9 % |
| LaB6, SRM 660c | 4.156978 ± 0.000019 | +0.00015 | 17.4 % | 4.15628 ± 0.00015 | −0.00055 | 60.9 % |
| ZnO 60 nm, SRM 1979 | 3.250289 (c 5.207451) | +0.00046 (c +0.00070) | 9.6 % | 3.25430 (c 5.21392) | +0.0045 (c +0.0072) | 74.6 % |

GSAS-II lands within 0.0005 Å on all three. MAUD gets close on the lab scans, but its default instrument
model is a generic Bragg–Brentano lab diffractometer. It fits these narrow NIST peaks poorly (Rwp 60–75 %, a
negative B on Si and ZnO, which the report flags), and it fails on the synchrotron ZnO data. A real MAUD analysis
starts from an instrument calibrated on a standard; CoRefine does not have one yet, and the comparison makes that
visible. MAUD's batch mode also does not export its calculated pattern, so it appears in the overlay by its
reflection positions only.

### Gold result (Gate 1)

`backend/skills/examples/gold_analysis.py`, checked by hand, on the 20 SRM 640f scans: mean
a = 5.430868 Å, scan-to-scan standard deviation 0.000071 Å. Every scan is within the 0.0005 Å
target, about 0.00028 Å below the certified value. See `docs/SPEC_CORRECTIONS.md` for this result,
the spec errors found while building, and the design decisions.

### Modes

| | `COREFINE_MODE=local` | `COREFINE_MODE=cloud` |
|---|---|---|
| Files | `backend/.local/bucket/` | AWS S3 |
| Database | SQLite | Neon Postgres |
| Search | local Qdrant + FastEmbed | Qdrant Cloud |
| Sandbox | subprocess (network blocked by hook, **not** isolated) | Daytona, `network_block_all` |
| LLM | Anthropic API (key needed) | Anthropic API |

In cloud mode, a missing key stops startup and the error names it. `GET /health` (or
`http://localhost:5173/api/health`) checks Neon, S3, Qdrant, Daytona and Anthropic. In
local mode it names the local stand-in it is using for each.

---

## Theory: DFT for every code, for everyone

### Why this exists

Running the same calculation in two DFT codes should be routine: it's the best check that a number
is physics and not an artefact of one code. In practice it costs a day per code. Each code has its
own input language, its own units, its own default k-mesh shift and its own idea of where the
pseudopotentials live. Mistakes are silent. A shifted mesh, a functional quietly forced to LDA, or a
lattice in Bohr read as Å all still converge and still print an energy.

CoRefine takes that day away and makes the silent mistakes loud:

```
material ──▶ plan ──▶ inputs for every code ──▶ read-back checks ──▶ local runs ──▶ studies
(MP, COD,    (typed,    (one adapter      (each input parsed the    (one code     (convergence,
 CIF,         every      per code)          way its code will read    at a time)    EOS + Δ-gauge,
 Storage)     choice                        it, then compared                       Raman)
              sourced)                      across codes)
```

### 1. A material, from anywhere

Search Materials Project by formula (`GaAs`, `TiO2`) or by elements (`Ga,As`); stable phases come
first. Materials Project works without a key through its public OPTIMADE endpoint, and with
`MP_API_KEY` CoRefine uses the current summary API: band gap, magnetic ordering, energy above hull.
Other sources are a COD id, an uploaded CIF, or any structure in Storage. Every structure is reduced
to its standard primitive cell with spglib, so all codes start from the same atoms.

### 2. A plan you can read

Every setting is a typed field with a value, a reason and a source (*you*, *rule*,
*Materials Project* or *Claude*):

- **Functional**: PBE unless you ask otherwise.
- **k-mesh**: Γ-centred, from a 0.3 Å⁻¹ k-point spacing. The planned mesh is shown before anything is
  generated, and a mesh you type replaces it for every code.
- **Occupations**: smearing for materials Materials Project marks as metallic.
- **Magnetism**: magnetic ground states are refused for now rather than run wrongly as non-magnetic.

With an Anthropic key and a goal ("quick check", "accurate gap"), Claude may review the plan and
adjust it within limits. It changes fields; it never writes input files.

### 3. Inputs for six codes, all from one structure

Each code is a plug-in, a `CodeAdapter` in `backend/app/dft/codes/`. An adapter knows whether its
code is usable here, how to write its input and read it back, how to launch it, how to parse its
results, and the one documented fix for its common failures. Adding a code means writing one adapter
and adding one registry line. The API, the checks, the runner and the UI pick it up from there.

| Code | Method | Inputs | Runs locally |
|---|---|---|---|
| **exciting** | all-electron FP-(L)APW+lo | `input.xml` + species | if you have a build (`EXCITING_ROOT`) |
| **Questaal** | all-electron FP-LMTO | `init` → `ctrl` via `blm`, `lmfa`, `lmchk` | if you have a build (`QUESTAAL_BIN`) |
| **Quantum ESPRESSO** | plane waves + pseudopotentials | `pw.in` + SSSP | ✅ one-click install |
| **GPAW** | PAW, plane waves (through ASE) | `gpaw_scf.py` + `structure.json` | ✅ one-click install |
| **ABINIT** | plane waves + norm-conserving | `abinit.abi` + PseudoDojo | ✅ one-click install |
| **VASP** | PAW (commercial) | POSCAR/KPOINTS/INCAR; POTCAR only from your own `VASP_PP_PATH` | inputs only |

Settings you didn't ask for stay at each code's own documented defaults, and the generated set lists
them, so nothing is decided invisibly. Some choices were made deliberately:

- **ABINIT has its own writer.** ASE's writer forces `ixc 7` (LDA), a shifted k-mesh and unitless
  positions. CoRefine writes `acell … angstrom`, reduced positions and `shiftk 0 0 0`, and takes the
  functional from the pseudopotentials.
- **Cutoffs are never guessed.** They come from SSSP's recommendations, PseudoDojo's "normal" hints,
  the JTH table's hints (QE with LDA), or the code's default.
- **LDA means the same LDA everywhere**: Slater exchange + Perdew–Wang 92 correlation. exciting
  `LDA_PW`, GPAW `LDA`, ABINIT and QE from PW92 pseudopotentials, VASP from the LDA POTCAR set (no
  `GGA` tag). Questaal's `blm` has no LDA switch and its built-in default is Barth–Hedin, so CoRefine
  writes the libxc ids `xcfun=0,1,12` into `ctrl` and the read-back checks them.
- **Every code gets the same Γ-centred mesh**, so cross-code differences mean physics, not sampling.

### 4. Sanity checks: read every input back

Writing an input is easy; writing the input you meant is the hard part. After generation, each input
is parsed back the way its code will read it and compared with the source structure and with the
other codes:

- formula and space group;
- volume per atom and nearest-neighbour distance;
- k-mesh, Γ-centring and functional;
- each code's own checks: exciting's XML schema, Questaal's `lmchk` sphere overlaps, ABINIT's
  `pspxc` per pseudopotential, MD5 of every pseudopotential file against its publisher's listing.

Si with PBE on a 2×2×2 mesh passes 19 checks across exciting and Questaal alone. A set either shows
**all passed** or names the check that failed.

### 5. Runs, and studies that answer real questions

Runs go one code at a time, to spare a laptop's memory. Results come only from each code's own
output: convergence, SCF iterations, total energy, Fermi level and gap. If a code stops with a known
error, its adapter applies the documented fix once. For example, QE's `smearing is needed` switches
to smearing, and Questaal restarts from its saved density. Runs done elsewhere, such as exciting on
your cluster, can be uploaded and are parsed the same way.

**Convergence.** A k-mesh series (spacing 0.5 → 0.15 Å⁻¹), then a basis series (×0.8 … ×2 of the
default cutoff). A setting counts as converged when it is within 1 meV/atom of the most accurate
point **and a denser point confirms it**. One lucky point is not convergence.

*The equation-of-state and Raman studies below remain in the backend and API (`/dft/jobs/{id}/studies/…`, the
co-pilot's `theory_vs_experiment`) but are no longer shown in the UI, which concentrates on runs, band gaps and
convergence.*

**Equation of state across codes.** Seven volumes from 94 to 106 % (the Δ-test protocol), a
Birch–Murnaghan fit per code (V₀, B₀, B′, cubic a₀), and the Δ-gauge between every pair of codes. For
elemental crystals, the all-electron WIEN2k reference from the Δ-test is included. Silicon, PBE, on a
laptop:

| Code | a₀ (Å) | Δ vs WIEN2k (meV/atom) |
|---|---|---|
| WIEN2k (reference) | 5.4695 | – |
| Quantum ESPRESSO + SSSP | 5.4696 | 0.03 |
| ABINIT + PseudoDojo | 5.4690 | 0.12 |
| Questaal | 5.4728 | 0.74 |
| GPAW | 5.4757 | 1.35 |

Four independent codes agree with the all-electron reference to within about 1 meV/atom.

The same study with **LDA** (8×8×8 mesh for every code, this laptop, 22 Oct 2026), next to PBE from the same run:

| Code | LDA a₀ (Å) | PBE a₀ (Å) | LDA B₀ (GPa) | PBE B₀ (GPa) |
|---|---|---|---|---|
| Quantum ESPRESSO (JTH PAW / SSSP) | 5.4026 | 5.4700 | 95.2 | 88.9 |
| ABINIT + PseudoDojo | 5.3943 | 5.4691 | 96.3 | 88.4 |
| Questaal | 5.4034 | 5.4729 | 98.6 | 89.9 |
| GPAW | 5.4068 | 5.4759 | 96.7 | 88.8 |

LDA overbinds and PBE underbinds, on either side of the measured 5.431 Å; that is the textbook
behaviour, reproduced by four codes. There is no all-electron LDA reference in the Δ-test, so no Δ is
shown for LDA. The
equilibrium structure from any code can be saved to Storage with one click, and from there it's a
model for the XRD side.

**Raman and IR from symmetry.** `phonopy` displaces the atoms, each displaced cell runs as an
ordinary checked set, and the Γ-point modes come out labelled by irreducible representation. Whether a
mode is Raman-active, IR-active or silent follows from group theory, as the overlap of its characters
with the vector representation (IR) and its symmetric square (Raman), not from a lookup table. Codes
that return forces do this: Quantum ESPRESSO and GPAW.

| Crystal | Mode | Frequency (cm⁻¹) | Active in |
|---|---|---|---|
| Si | T2g | 510.5 (QE), 509.5 (GPAW) | Raman |
| GaAs | T2 | 256 | Raman and IR |
| MgO | T1u | 409 | IR only |

The selection rules are exact. The frequencies are PBE and TO-like: LO–TO splitting needs Born
charges, and Raman intensities need dielectric derivatives, neither of which is computed yet.

### Codes for people who have nothing installed

| Tool | What | Source | Licence | Verified by |
|---|---|---|---|---|
| micromamba | package installer (single binary) | mamba-org GitHub release | BSD-3 / MIT | SHA-256 from the release |
| Quantum ESPRESSO 7.6 | `pw.x` and friends | conda-forge `qe` | GPL-2.0 | binary present; `ldd` finds every library |
| SSSP 1.3 PBE / PBEsol efficiency | pseudopotentials + cutoffs | Materials Cloud Archive | CC-BY 4.0 | MD5 from the archive; rechecked in every set |
| GPAW 26.7 + gpaw-data | PAW code + setups | conda-forge | GPL-3.0 | `ldd` |
| ABINIT 10.0.3 | `abinit` | conda-forge | GPL-3.0 | `ldd` |
| PseudoDojo NC PBE v0.4 (standard) | pseudopotentials + cutoff hints | github.com/PseudoDojo | CC-BY 4.0 | MD5 from `standard.djson`; rechecked per set |
| PseudoDojo NC LDA v0.4 (standard) | ABINIT pseudopotentials for LDA | github.com/PseudoDojo | CC-BY 4.0 | MD5 from `standard.djson` |
| JTH v1.1 LDA PAW (UPF) | QE pseudopotentials for LDA (SSSP has no LDA) | github.com/PseudoDojo (UPF), github.com/abinit/paw_jth_datasets (hints) | GPL-3.0 | UPF generation input identical to the JTH v1.1 input; SHA-256 recorded |

Everything lands in `backend/.local/tools/`. Delete that folder and it's all gone. A footnote for the
curious: conda-forge's `qe` 7.6 links ELPA without declaring it, so the installer asks for ELPA
explicitly, and the `ldd` check is how that was caught.

exciting and Questaal are open source but not on conda-forge. Build them from source and point
`.env` at them; until then CoRefine still writes and checks their inputs. VASP is commercial: inputs
only, and your licensed POTCARs never leave your machine.

### From the command line

```bash
cd backend
uv run python scripts/dft_inputs.py --source cod:9008565 --xc PBE --kmesh 2 2 2 --out runs/si-pbe
uv run python scripts/dft_inputs.py --source mp:mp-149 --codes exciting --out runs/si-mp
uv run python scripts/dft_inputs.py --prompt "DFT PBE for Si (mp-149), simple 2x2x2 k-mesh" --out runs/si
```

Each set is a folder with one subfolder per code, plus `checks.json`, `provenance.json` and
`SUMMARY.md`. In the app it downloads as a zip. Sets made in the app are kept in
`backend/.local/dft/`.

---

## Theory ↔ Experiment

This is where the two halves meet. It is useful to a theorist who has never refined a scan and to an
experimentalist who has never run DFT.

**How each side got its answer.** For one material, *Lab → Theory ↔ Experiment* tells both stories side by side,
read top to bottom. Each step says who took it (a language model, plain code or a scientific program), what it did,
the reason recorded at the time, and any retries or automatic fixes.

- **Experiment:** inputs (scan and reference structure, with the answer hidden) → plan (Claude, or a fixed recipe for
  GSAS-II/MAUD) → each step with its goal, status and attempts → comparison with the certificate (code) → report
  and claim check. Every agent's notes from the experiment log open underneath.
- **Theory:** structure source → every setting with its reason (your request, a CoRefine rule or Materials Project) →
  inputs for six codes and their read-back checks → each code's SCF run (iterations, gap, any self-heal) → band gaps
  next to Materials Project's.
- **Where the two meet:** the lattice parameter the calculation assumed against the refined measurement.

Everything on the page is read from run and set files (`GET /bridge/story?material=…`).

**Your structure against a real scan.** Open any measured pattern in Storage and choose a model
structure: a DFT equilibrium structure, a COD or Materials Project entry, anything in Storage.
CoRefine then:

1. finds the measured peaks (pseudo-Voigt fits with uncertainties);
2. matches them to the model's reflections (conventional-cell *hkl*);
3. fits one isotropic scale and a zero shift.

Out comes what a theorist actually wants to know: how far off the model is, and in which direction.
The QE equilibrium structure against the NIST 640f scan:

- **11 of 11** peaks matched;
- linear strain **−0.705 %**;
- implied a = **5.43107 Å**, against the certified 5.431144 Å;
- with the bulk modulus from the same equation of state, an **equivalent pressure of 1.87 GPa**, the
  pressure that would squeeze the PBE crystal onto the measured one.

**Identify the phase.** With no model at all, CoRefine scores every Materials Project polymorph of the
formula by how many strong peaks it explains after its own scale fit, and penalises strong lines the
scan doesn't show. On the silicon scan, diamond-structure Si (mp-149) comes out first.

All of this is deterministic code (`app/xrd/analysis.py`): no LLM, no hidden fitting.

---

## Where the calculations run

**On your own computer.** Pressing *Run* starts the program as a local process in the set's folder,
with a thread limit and a timeout. Nothing is sent to a cloud or a cluster unless you set that up.

Sometimes a laptop isn't enough: big cells, dense meshes, or exciting on your group's machine. For
those, copy `backend/compute.example.yaml` to `compute.yaml` (it's not committed) and add a Slurm
target. CoRefine copies the folder over SSH using your own `~/.ssh/config` (no passwords stored),
fills in your job-script template, submits it, polls and copies the results back. The UI asks before
every cluster submission. Each person writes their own `compute.yaml`; no machine is built into the
code.

---

## Configuration

Everything goes in `backend/.env` (template: `backend/.env.example`), and it's all optional in local
mode.

| Group | Keys |
|---|---|
| Agents | `ANTHROPIC_API_KEY`, `MODEL_MAIN`, `MODEL_FAST` |
| Cloud mode | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET`, `DATABASE_URL`, `QDRANT_URL`, `QDRANT_API_KEY`, `EMBED_PROVIDER`, `EMBED_MODEL`, `EMBED_DIM`, `DAYTONA_API_KEY`, `DAYTONA_SNAPSHOT` |
| Materials | `MP_API_KEY` (a current Materials Project key) |
| Your own DFT builds | `EXCITING_ROOT`, `QUESTAAL_BIN`, `QUESTAAL_LIB_ROOT` (Spack builds), `QE_PSEUDO_DIR`, `VASP_PP_PATH` |
| Compute | `COMPUTE_CONFIG` (default `backend/compute.yaml`) |

Secrets are read only by the backend. The browser and the sandbox never see them, and `.env` is never
committed.

---

## Tests

```bash
cd backend && uv run pytest        # 91 tests; LLM mocked, everything else real
uv run pytest -m integration       # the 3 that call real services (keys needed)
```

**XRD side:**
- the contracts, the step contract and the claim checker;
- sanitizing, and the dataset API's refusals;
- the gold analysis through the runner;
- network blocking, timeouts and output limits;
- a full run that recovers from a broken first script and from an invented number in the report;
- the SSE stream.

**DFT and bridge side:**
- every adapter's write-and-read-back on several materials;
- the Materials Project ID handling;
- result parsing against real output files (exciting from a cluster, Questaal, GPAW and ABINIT kept
  as fixtures), Questaal's automatic restart, and the Slurm flow against a fake cluster;
- the convergence rule, the EOS fit and the Δ-gauge;
- Raman selection rules;
- peak matching, scale fitting and phase identification;
- the bridge aggregation.

---

## Data sources and credits

- NIST SRM 640f raw XRPD data, mds2-2251, [doi:10.18434/M32251](https://doi.org/10.18434/M32251), NIST open licence.
- NIST SRM 640f certificate (26 Feb 2019): certified value and the Table 1 wavelength.
- NIST SRM 660c raw XRPD data, mds2-2315, [doi:10.18434/mds2-2315](https://doi.org/10.18434/mds2-2315), NIST open licence; certificate (29 Oct 2015).
- NIST SRM 1979 11-BM data, mds2-2269, [doi:10.18434/M32269](https://doi.org/10.18434/M32269), NIST open licence; certificate (04 June 2021), Tables 3–4.
- COD 1000057 (LaB6) and 2300450 (ZnO), [crystallography.net](https://www.crystallography.net/cod/).
- JTH PAW table: Jollet, Torrent, Holzwarth, *Comput. Phys. Commun.* **185**, 1246 (2014).
- COD 9008565, silicon (Wyckoff), [crystallography.net](https://www.crystallography.net/cod/9008565.html).
- [Materials Project](https://materialsproject.org) (CC-BY 4.0), through its API and OPTIMADE endpoint.
- SSSP: Prandini *et al.*, *npj Comput. Mater.* **4**, 72 (2018), Materials Cloud Archive.
- PseudoDojo: van Setten *et al.*, *Comput. Phys. Commun.* **226**, 39 (2018).
- Δ-test and WIEN2k reference: Lejaeghere *et al.*, *Science* **351**, aad3000 (2016), via `ase.collections.dcdft`.
- Built on ASE, spglib, pymatgen, phonopy, gemmi, lmfit, excitingtools, FastAPI, LangGraph, React and uPlot.
