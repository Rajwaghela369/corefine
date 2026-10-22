# CoRefine in plain words

This page is for anyone who opens the project and thinks "what is this, and what do I click?" You
don't need to know DFT or X-ray diffraction. Read the first two sections, try the tour, and use the
glossary whenever a word is new.

## The idea in one minute

A crystal (salt, silicon, the chip in your phone) is a pattern of atoms repeating in space. Two
different kinds of people study it:

- **Experimentalists measure it.** They shine X-rays on a powder of the material and record a
  *diffraction pattern*: a curve with peaks. The peak positions tell you how big the repeating box
  of atoms is (the *lattice parameter*, written *a*, in ångström; 1 Å is one ten-billionth of a metre).
- **Theorists calculate it.** They give a computer the atoms and ask quantum mechanics (*DFT*) for
  the energy, the size of the box and the *band gap* (the energy the material needs before it
  conducts light or electricity).

Normally these two groups never see each other's work in one place. CoRefine puts them side by side:

```
          measurement                                    calculation
   (X-ray pattern of silicon)                      (the same silicon, six DFT programs)
              │                                                   │
   agents fit the peaks  ───────►  a = 5.4311 Å   ◄───────   a = 5.40 – 5.48 Å
              │                          │                        │
              └────────────  "how far apart are they, and why?"  ─┘
```

One rule makes the results trustworthy: **language models plan and explain, ordinary code produces
every number.** An AI never types a number into a report, and every number points to the file that
made it.

## The three screens

Open the app and pick **Lab**. It has three parts.

| Screen | You bring | You get |
|---|---|---|
| **Experiment · XRD** | a diffraction scan (the NIST silicon, LaB6 and ZnO scans are included) | the lattice parameter, the fit quality, a written report, and the reasoning behind each step |
| **Theory · DFT** | a material name such as `GaAs` | ready-to-run input files for six DFT programs, a check that each one says what you meant, a run on your laptop, the band gap and a convergence study |
| **Theory ↔ Experiment** | nothing; it reads the other two | the measured and the calculated lattice parameter side by side, with the steps that led to each |

## Your first ten minutes

Set-up commands are in the [README](../Readme.md#try-it-on-your-laptop). Once the app is open:

1. **Look first, break nothing.** *Lab → Experiment · XRD* already has silicon data. Open any past
   analysis and read the **Overview** and **Reasoning** tabs. Reasoning shows who did each step (a
   language model, plain code or a scientific program) and why.
2. **Run a calculation without installing anything.** *Lab → Theory · DFT*, click **install** on
   Quantum ESPRESSO, search `GaAs`, click **Generate**, then run it from **Runs**. The band gap
   appears under **Overview**.
3. **See both worlds.** *Lab → Theory ↔ Experiment* for silicon. Read it top to bottom: the left
   story is the experiment, the right is the calculation, and the last box compares them.

If nothing is configured (no API key), steps 1 to 3 still work. Only the AI agents and the chat need
an `ANTHROPIC_API_KEY`.

## How the project is built

```
 frontend/ (React)  ───────►  backend/ (FastAPI)
  what you see                 │
                               ├── app/xrd/           fit peaks, compare a model with a scan, identify a phase
                               ├── app/agents/        Planner, Coder, Analyst, claim checker, chat co-pilot
                               ├── app/orchestration/ runs an analysis step by step, keeps a log
                               ├── app/sandbox/       runs the AI-written code in isolation
                               ├── app/dft/           materials → settings → input files → runs → studies
                               │     └── codes/       one small file per DFT program
                               └── app/storage/       files, database, datasets
```

- **To add a DFT program:** write one adapter in `backend/app/dft/codes/` (how to write its input,
  read it back, launch it and parse its answer) and add one line to the registry. Nothing else changes.
- **To add a dataset:** put a `dataset.yaml` (certificate value, licence, checksum, wavelength and
  where each came from) in `data/` and add the download to `scripts/fetch_data.py`.
- **To follow one analysis:** its folder under `backend/.local/` holds the plan, every attempt's code,
  the outputs and the report. Everything the UI shows is read from those files.

## Glossary

| Word | Meaning |
|---|---|
| **XRD** | X-ray diffraction. Peaks appear where X-rays bounce off planes of atoms in step. |
| **Powder pattern** | Intensity against the angle 2θ for a powdered sample. Peak positions give the lattice parameter. |
| **Lattice parameter (a, c)** | The edge length of the crystal's repeating box, in Å. Cubic crystals need one, hexagonal ones two. |
| **Certified value** | The number the standards institute (NIST) guarantees for a reference powder. We use it as the answer key. |
| **Kα1 / Kα2** | The two close X-ray wavelengths a copper tube emits. They split every peak into a doublet. |
| **Rietveld refinement** | Fitting the whole pattern with a model of the crystal and the instrument. GSAS-II and MAUD do this. |
| **Rwp** | How badly the fit misses the data, in percent. Lower is better. |
| **DFT** | Density functional theory: a way to compute a material's energy and electrons from the atoms alone. |
| **Functional (PBE, LDA)** | The approximation inside DFT. LDA tends to give a slightly small crystal, PBE a slightly large one. |
| **k-mesh** | How finely the calculation samples the crystal's momentum space. Finer is slower and more accurate. |
| **SCF** | The loop a DFT code repeats until the electrons stop changing. "Converged" means it finished. |
| **Cutoff / basis** | How many waves or functions describe the electrons. More is slower and more accurate. |
| **Pseudopotential** | A stand-in for the atom's inner electrons that makes the calculation cheaper. |
| **Band gap** | The smallest energy to excite an electron. Zero for a metal. DFT usually underestimates it. |
| **Convergence** | Increasing k-mesh and cutoff until the answer stops moving. Without it a number means little. |
| **Equation of state (EOS)** | Energy at several volumes, giving the equilibrium size and stiffness (bulk modulus). |
| **Δ-gauge** | A standard score for how closely two codes agree on an EOS, in meV per atom. Under 1 is excellent. |
| **Raman / IR** | Ways light probes atomic vibrations. Which vibrations are visible follows from the crystal's symmetry. |
| **COD / Materials Project** | Free online databases of crystal structures. |
| **Claim checker** | Plain code that rejects any number in a report that no output file supports. |
| **Sandbox** | A locked room where AI-written code runs, so it cannot reach your files or the network. |

## Questions people ask

**Do I need an API key?** No. Everything works without one except the AI agents, Claude's review of
DFT plans and the chat. Add `ANTHROPIC_API_KEY` to `backend/.env` for those.

**Does it send my data anywhere?** In the default `local` mode nothing leaves your computer except
downloads (datasets, programs, Materials Project lookups). `cloud` mode uses S3, Neon, Qdrant, Daytona
and Langfuse, and needs your own accounts.

**Can the AI invent a result?** It can write wrong code, but it cannot put a number in the report that
the code did not produce: the claim checker rejects it and the run retries.

**Why do codes disagree by a little?** Each uses different pseudopotentials and numerics. Agreement
within about 1 meV per atom on silicon is normal. A bigger gap is worth investigating, and that is
what the checks are for.

**Why does my DFT band gap differ from the textbook?** Standard DFT underestimates gaps. The app shows
Materials Project's value next to yours so you can see the usual size of the gap.

**The install button failed.** Check your internet connection and free disk space (a few GB). Everything
lands in `backend/.local/tools/`; delete that folder and click install again.

**The app says a code is not available.** exciting and Questaal are not one-click. Build them and set
`EXCITING_ROOT` or `QUESTAAL_BIN` in `backend/.env`. VASP is commercial and needs your own licence.

**Something is broken.** `cd backend && uv run pytest` should pass. If it does not, the failing test
name usually says which part is at fault.

## Where to read next

- [README](../Readme.md): full details of every feature, the numbers, and the configuration.
- [SPEC_CORRECTIONS.md](SPEC_CORRECTIONS.md): what the original plan got wrong and how it was fixed.
- [SPEC.md](SPEC.md): the original hackathon plan (historical; the README describes what exists now).
