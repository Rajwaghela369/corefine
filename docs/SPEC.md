# CoRefine — Build Spec v2

Oct 21, 2026 · @Raj

## Verdict and what changed from v1

Build it, but narrow it: CoRefine wins if one prompt takes the NIST SRM 640f silicon scan from S3 to a refined lattice parameter within a stated tolerance of the certified value, with every number traceable to a file. That single loop is the product; everything else is stretch.

The idea is strong for this hackathon. Agents that write and run real analysis code, track their work in files and explain results map directly onto the event's agentic-science focus. The risk is breadth: v1 describes a dynamic DAG engine, a canvas, an S3 tree UI, multimodal RAG, Neon, Langfuse and a self-healing loop — too much for 48 hours.

What v2 fixes:

- **A science error that judges will catch.** v1 states the certified lattice parameter as 5.431144 nm. It is in ångström (Å); 1 nm = 10 Å. Silicon's a is about 0.543 nm.
- **The sample code loads the wrong file.** v1 parses the 640f powder scan with `Structure.from_file`. A powder-pattern CIF holds 2θ–intensity data, not a crystal structure. The structure comes from COD 9008416; the 640f file is the measured pattern to fit against.
- **Simulation alone is not the experiment.** A pymatgen stick pattern has no instrument profile, no Kα2 line, no background. The MVP must fit peaks and refine the lattice parameter — that refinement is what the name CoRefine should mean.
- **Credentials inside the sandbox.** v1 calls boto3 from inside the sandbox. On Daytona's lower tiers outbound network is restricted anyway, so the backend stages files in and out; no cloud keys enter generated code.
- **One rule from CROSSCHECK is kept.** Agents write and run code freely, but no number reaches a report unless it appears in an executed output file. A code-only claim checker enforces this.
- **Stack fixed to managed services.** Nothing is self-hosted or built from scratch: AWS S3, Neon Postgres, Qdrant Cloud, Daytona, Langfuse Cloud and the Anthropic API, all with existing credentials, behind a FastAPI backend and a React + Vite frontend.
- **Inconsistencies removed.** v1 mixed 3- and 5-agent models, GPT-4o and Claude, "RAG over skills", and a self-healing node that "uses Langfuse and AST". v2 has one agent model and one stack.

## Aim, hypothesis and success criteria

**Aim.** Let a researcher who does not write code go from raw data in object storage to a verified, explained analysis result by describing the experiment in plain language.

**Hypothesis.** An agent team that writes and executes its own analysis code, keeps its state in plain files, and is barred from reporting any number not produced by executed code can reproduce a certified reference result from raw data with no human-written analysis code — and can explain where and why its result differs.

**How we test it** (the demo is the experiment):

| Criterion | Target | Measured from |
| --- | --- | --- |
| Refined Si lattice parameter vs certified 640f value | within 0.0005 Å (≈0.01 %), to be tightened after first runs | `metrics.json` of the run |
| End-to-end success from one prompt | 4 of 5 fresh runs finish with a report | run table in Neon |
| Self-healing | at least 1 run recovers from a real code error within 2 retries | run logs |
| Traceability | 100 % of numbers in the report found in an output file | claim checker result |
| Time to result | under 5 minutes per run | run timestamps |
| Honest failure | 1 deliberately bad input refused with a clear reason | demo |

The 0.0005 Å target is a starting value: peak-position refinement without a full Rietveld model, zero-shift and displacement correction usually lands near this range, not at the certificate's uncertainty. Agree the final number after the first silicon run.

## MVP scope vs stretch

The MVP is one experiment type done end to end; the "dynamic workflow" is an LLM-written plan rendered as steps, run by a fixed agent graph.

| Feature | MVP (must ship) | Stretch (only if day-1 gate passes) | Cut for the hackathon |
| --- | --- | --- | --- |
| Experiment | Si XRD: peak fit + lattice refinement vs 640f | Second sample or instrument (640g, a COD structure with strain) | DFT, battery imaging, PyBaMM |
| Workflow canvas | Plan steps drawn read-only from `plan.json`, live status colours | User edits a step's parameters and reruns | Drag-and-drop node editor |
| Agents | Planner, Coder, Analyst + code claim checker | Optimizer that proposes the next run | Free-form agent teams |
| Data intake | Upload with folder + `dataset.yaml` manifest; tree view; tag a folder | Validate manifest against file contents | Arbitrary external APIs |
| Storage | AWS S3 (one bucket) + Neon Postgres | Presigned direct-to-bucket upload | Multi-bucket, multi-user ACLs |
| Retrieval | Qdrant: past run reports, dataset READMEs, short reference notes | Research-paper PDFs with figures (multimodal) | Fine-tuning, re-ranking |
| Sandbox | Daytona with files staged in/out by backend | Pre-built snapshot with all libs | Local Docker fallback (keep ready, not demoed) |
| Results | 4 tabs, runs listed, report per run | Side-by-side comparison of two runs | PDF export |
| Chat | Claude co-pilot using run files, metrics and Qdrant search; can start a new run | Paper-grounded brainstorming of next experiments | Voice, multi-user |
| Observability | Langfuse traces for every LLM call | Prompt versions in Langfuse | Cost dashboards |

Qdrant is in the MVP with a narrow job — finding past runs and notes for the chat. Full research-paper RAG with figures is the natural next module once the core loop works.

## The science case the MVP runs

The MVP measures silicon's lattice parameter from a real X-ray scan and checks it against NIST's certified value. In plain terms: the scan shows bright peaks at certain angles; their exact angles reveal the spacing between atom layers; that spacing gives the size of the crystal's repeating cube, a.

**Inputs**

- Measured pattern: NIST SRM 640f raw XRPD scan, 2θ vs intensity, in powder-CIF form ([DOI 10.18434/M32251](https://doi.org/10.18434/M32251)).
- Reference structure: COD 9008416, silicon, diamond-cubic (space group Fd-3m). Tells the code which peaks to expect and roughly where.
- Target: the certified a for SRM 640f, 5.431144 Å at 22.5 °C. Confirm digits and uncertainty from the NIST certificate before the demo.

**Steps the Coder agent writes code for**

1. Read the scan and its metadata: wavelength, radiation (Cu Kα1 only, or Kα1 + Kα2), step size. Use the file's wavelength, never a default.
2. Compute expected reflections (hkl) from the COD structure with pymatgen. The first, (111), sits near 28.4° 2θ for Cu Kα.
3. Subtract the background (polynomial or rolling minimum).
4. Fit each peak with a pseudo-Voigt profile; if Kα2 is present, fit the doublet with a fixed 0.5 intensity ratio. Output each peak's centre and its fit uncertainty.
5. Convert centres to d-spacings and refine a by least squares, with a zero-shift term for the instrument.
6. Compare refined a to the certified value; report per-peak residuals and a plot of measured vs fitted pattern.

```latex
n\lambda = 2d\sin\theta \qquad d_{hkl} = \frac{a}{\sqrt{h^2+k^2+l^2}} \qquad 2\theta_{obs} = 2\theta_{calc}(a) + 2\theta_{zero}
```

**What a good result looks like**: refined a within the success target, residuals with no trend across angle (a trend means a missing correction such as specimen displacement), and a stated reason for any leftover offset. Temperature matters little here: silicon expands about 2.6 × 10⁻⁶ per kelvin, so 1 K moves a by roughly 0.00001 Å.

**Why this is a fair benchmark**: the answer is known and certified, the run takes seconds, and every error has a physical name (zero shift, displacement, wrong wavelength). That lets the Analyst classify a difference rather than guess.

Open question for day 1: check that the 640f download really contains powder-CIF scans with wavelength metadata, and how many scans there are.

## Architecture

The browser talks only to the FastAPI backend; the backend is the only part that holds credentials and talks to the six managed services.

&#91;embedded content: system architecture · 3 backend parts, 6 managed services\]

A run flows top to bottom: the chat or the run button calls the orchestrator, which plans with Claude, executes in Daytona, stores files in S3 and numbers in Neon, indexes the report in Qdrant, and streams status back to the browser.

## Data layer

Agents find data through a manifest file in each dataset folder, not by guessing paths: the folder says what it holds, the database indexes it, and the planner reads the index.

**Storage.** AWS S3 holds every file (inputs and run outputs); Neon Postgres holds the index and all metrics; Qdrant holds searchable text. Only the backend holds S3 credentials — browser uploads use presigned URLs, and the sandbox never sees keys.

**Bucket layout** (one bucket, fixed top-level folders):

```text
corefine/
  datasets/                      # inputs; one folder per dataset
    nist-srm-640f/
      dataset.yaml               # manifest (required)
      raw/                       # files exactly as downloaded
      README.md                  # source, licence, notes
    cod-9008416-si/
      dataset.yaml
      raw/9008416.cif
  runs/                          # outputs; written only by the backend
    run-2026-10-24-001/
      plan.json  plan.md
      code/step_02_fit.py
      logs/step_02.stdout
      outputs/metrics.json  outputs/fit.png  outputs/peaks.csv
      report.md
      experiment_log.md          # agents' running notes
```

**Manifest** — written by the upload form, editable by the user, read by agents:

```yaml
id: nist-srm-640f
role: measured_pattern          # measured_pattern | reference_structure | reference_value
technique: xrd_powder
material: Si
format: pdcif                   # pdcif | xy | csv | cif
files: [raw/*.cif]
instrument:
  radiation: CuKa1              # fill from the file; upload form pre-fills if found
  wavelength_A: null            # null = agent must read it from the file
temperature_C: 22.5
source: https://doi.org/10.18434/M32251
reference_values:
  a_A: 5.431144                 # certified; confirm against certificate
```

**Upload and path UI**

- Upload panel: pick or create a dataset folder, drop files, fill a short form (role, technique, material, format). The form writes `dataset.yaml`; files go to `raw/`.
- Tree view of the bucket with a badge per folder showing its role; folders without a manifest show a warning and cannot be used in a run.
- "Use in run" toggles: the chat request carries the selected dataset ids, so the planner never searches the bucket.
- Backend indexes each manifest into Neon on upload and on a "Rescan" button.

**Neon tables** (Postgres; JSONB for anything shaped by the experiment):

| Table | Key columns | Written by |
| --- | --- | --- |
| datasets | id, role, technique, material, format, prefix, manifest JSONB, updated\_at | Upload API, rescan |
| runs | id, prompt, dataset\_ids, status, plan JSONB, started\_at, finished\_at, parent\_run\_id | Orchestrator |
| steps | run\_id, idx, name, status, attempts, code\_key, stdout\_key, error | Orchestrator |
| artifacts | run\_id, step\_idx, kind (plot, csv, json, report), key, sha256 | Orchestrator |
| metrics | run\_id, name, value, unit, uncertainty, source\_key | Parsed from `metrics.json` only |
| messages | session\_id, run\_id, role, content, created\_at | Chat API |

The `metrics` table is filled by code that reads `metrics.json`, never from agent text. That table is what the chat and cross-run comparison query.

**Qdrant collections** (Qdrant Cloud; one collection per kind, payload filters on every query):

| Collection | What is indexed | Payload used for filtering | Written when |
| --- | --- | --- | --- |
| run\_reports | Each `report.md` split by section, plus the plan summary | run\_id, parent\_run\_id, dataset\_ids, technique, material, status, created\_at | Run finishes |
| dataset\_docs | Each dataset's `README.md` and manifest text | dataset\_id, role, technique, material | Upload or rescan |
| reference\_notes | Short curated notes (certificate summary, method notes) | source, technique, material | Seeded on day 1 |

The chat filters before it searches (for example `material = Si` and `status = done`), so results never mix materials or failed runs. Qdrant stores text for finding things; numbers are always read back from Neon, never from a retrieved chunk.

**Embeddings.** The Anthropic API has no embedding endpoint, so embeddings come from elsewhere. Preferred: the embedding model offered by your Qdrant Cloud cluster (cloud inference), so no extra account is needed. Fallback: FastEmbed in the backend. Check which your plan offers on day 1 and fix the model and vector size in config.

## Agent system

Three LLM agents write plans, code and reports; plain code runs everything, checks every output and owns all state. The graph itself is fixed (LangGraph); what varies per prompt is the plan the Planner writes and the code the Coder writes.

| Part | Type | Input | Output | May not |
| --- | --- | --- | --- | --- |
| Orchestrator | Code (LangGraph `StateGraph`) | Run request | Step sequencing, retries, Neon rows, file staging | — |
| Planner | LLM | Prompt, selected manifests, skills index | `plan.json` (validated by a Pydantic schema) + `plan.md` | Write code; reference a dataset not selected |
| Coder | LLM | One step from the plan, manifests, listing of earlier outputs, matching skill file, last error (on retry) | One Python file per step | Use network; write outside `/work/outputs`; skip `metrics.json` |
| Runner | Code | Python file + staged inputs | stdout, stderr, exit code, output files | Retry on its own |
| Output checker | Code | Step's declared outputs | Pass, or an error message for the Coder | Be skipped |
| Analyst | LLM (multimodal) | `metrics.json`, `peaks.csv`, plot image, manifest reference values, skill rules | `report.md` with a classification | State a number not in a metric or manifest |
| Claim checker | Code | `report.md`, metrics, manifests | Pass, or a list of untraced numbers | Be overridden by an agent |
| Chat co-pilot | LLM (LangChain Deep Agent) | Conversation, run index, run files | Answers; new run requests | Edit a finished run |

**The step contract** every generated script must follow (stated in the Coder prompt and enforced by the output checker):

- Read only from `/work/inputs/`; write only to `/work/outputs/`.
- Write `metrics.json` as a list of `{name, value, unit, uncertainty, method}`.
- Write any table as CSV and any plot as PNG with the names declared in the plan.
- Print a one-line summary as the last stdout line.

**Self-healing, bounded.** On a non-zero exit or a failed output check, the Coder gets the code, the last 60 lines of stderr and the check message, and writes a new version. Maximum 2 retries per step, then the step and run are marked failed with the error shown in the UI. Timeouts are not retried.

**Experiment memory in files.** Each run folder holds `plan.md`, one code file per attempt (`step_02_fit.v2.py`), and `experiment_log.md`, which the orchestrator appends with each agent's short note (what it tried, why it retried). Agents read the logs of the parent run when the user asks for a follow-up, so a second run builds on the first. Neon holds the index; the files hold the story.

**Skills folder** (local, in the repo, loaded by file name — not retrieved by search):

- `skills/xrd_powder_refinement.md` — the six steps above, library calls that work, common errors.
- `skills/step_contract.md` — the contract, with a minimal example script.
- `skills/report_rules.md` — report sections, how to cite a metric, the classification table below.
- `skills/si_reference.md` — expected peaks, space group, certified values and their source.

**How the Analyst classifies a difference** (applied in order; thresholds tuned after first runs):

| Observation | Classification | Suggested action |
| --- | --- | --- |
| Residuals trend with angle | Missing geometric correction | Rerun with specimen-displacement term |
| Difference from certified a within target, no trend | Agreement | None |
| Difference beyond target, no trend, wavelength taken from a default | Metadata issue | Rerun with wavelength from file |
| Peak fit uncertainty large on some peaks | Weak or overlapping peaks | Exclude those peaks and rerun |
| None of the above | Unexplained | Flag for a human; give no cause |

Models: all LLM calls go to the Anthropic API. Use a Claude Sonnet-class model for Planner, Coder and Analyst (the Analyst reads the plot image, which Claude supports), and a Haiku-class model for chat summaries and routing. Keep model names in one config file and wrap every call with the Langfuse callback.

## Sandbox

Daytona runs the generated code; the backend moves files in and out through the SDK, so the sandbox never needs cloud credentials or open internet. This fits Daytona's free entry tier, where outbound network is restricted and cannot be overridden per sandbox, while package registries stay reachable ([Daytona network limits](https://www.daytona.io/docs/en/network-limits), [isolation](https://www.daytona.io/docs/en/isolation.md)). New accounts get $200 of free compute and Tier 1 caps the organisation at 10 vCPU / 10 GiB RAM ([limits](https://www.daytona.io/docs/limits), [comparison](https://www.agent37.com/blog/daytona-alternative)) — ample for second-long XRD fits.

**Per run**

1. Create one sandbox per run from a prepared snapshot (Python 3.11 + the libraries in the stack table), or install them once at create time.
2. Upload the selected dataset files to `/work/inputs/` and earlier step outputs as needed.
3. Upload the step's script; execute with a 120 s timeout.
4. Download `/work/outputs/*`, stdout and stderr; push them to `runs/<id>/` in the bucket and record keys and SHA-256 in Neon.
5. Delete the sandbox when the run ends (or let auto-stop handle a crash).

**Limits**: 120 s per step, 3 attempts per step, 6 steps per run, 50 MB of outputs per run. Exceeding a limit fails the step with the reason; the run never loops.

**One interface, two runners.** Code calls `SandboxRunner.run(script, inputs) -> Result`. Implement `DaytonaRunner` first and keep a `LocalDockerRunner` (subprocess in a container with no network, same limits) as the venue-Wi-Fi fallback. E2B fits the same interface if credits run out.

## UI

Three columns: data on the left, conversation in the middle, results on the right; a run list above the result tabs ties every tab to one run.

| Area | What it shows | What the user does |
| --- | --- | --- |
| Left: Data | Bucket tree with a role badge per dataset; upload panel; manifest editor | Upload files, fill the manifest form, tick datasets to use |
| Middle: Chat | Conversation with the co-pilot; a run card when a run starts (status, link to its tabs) | Describe an experiment, ask about results, ask for a follow-up run |
| Right, top: Runs | List of runs, newest first: id, status, key metric (refined a), parent run | Select a run; tick two to compare (stretch) |
| Tab 1: Plan | Steps from `plan.json` as boxes, coloured by status (pending, running, retrying, done, failed); click a step for its code and log | Inspect; rerun from a step (stretch) |
| Tab 2: Plots | PNGs from `outputs/` (measured vs fitted pattern, residuals vs 2θ) | Zoom, download |
| Tab 3: Data | `metrics` rows for the run (name, value, unit, uncertainty, source file) and CSV previews | Sort, download CSV |
| Tab 4: Report | Rendered `report.md` with the claim-checker badge (all numbers traced, or the untraced list) | Read, copy, download |

**Build**: React + Vite + TypeScript, with Tailwind and shadcn/ui for panels and tabs, React Flow (read-only) for the Plan tab, react-markdown for reports, and TanStack Query for API calls. Live updates come from Server-Sent Events on `/runs/{id}/events`, so step colours change as steps finish. No node editor.

## Conversation and cross-run analysis

When a run finishes, the orchestrator posts a run-complete event into the chat session; the co-pilot then opens the conversation with a short summary built from that run's metrics and report, and answers follow-ups from the files, not from memory.

**Co-pilot tools** (all read-only except `start_run`):

- `list_runs(filter)` — runs with status and headline metrics from Neon.
- `get_run(run_id)` — plan, step statuses, report.
- `query_metrics(run_ids, names)` — metric rows across runs, the basis of every comparison.
- `read_artifact(run_id, path)` — a CSV, log or code file (text only, size-capped). Plus \`search\_knowledge(query, filters)\` — filtered Qdrant search over reports, dataset docs and notes.
- `compare_runs(run_a, run_b)` — code that diffs plans, parameters and metrics and returns a table.
- `start_run(prompt, dataset_ids, parent_run_id)` — the only write; the UI asks the user to confirm before it fires.

**Example exchange**

- User: "Why do the residuals slope upward at high angle?"
- Co-pilot reads `peaks.csv` and the report, sees the Analyst's "missing geometric correction" class, explains specimen displacement in two sentences, and offers a follow-up run.
- User: "Yes, rerun with that correction."
- `start_run` with `parent_run_id`; the Planner reads the parent's `plan.md` and `experiment_log.md`, changes one step, and the new run appears above the old one. The co-pilot then reports the change in refined a and residual trend between the two runs, using `compare_runs`.

Same rule as the reports: any number the co-pilot states must come from a tool result in that turn. The chat answer is checked by the same claim checker before display.

## Tech stack and API

Two codebases (FastAPI backend, React + Vite frontend) and six managed services you already have credentials for; nothing is self-hosted. Pin every version in a lock file on day 1.

| Layer | Choice | Client library | Used for |
| --- | --- | --- | --- |
| Backend | FastAPI, Python 3.11, Pydantic | — | API, SSE, typed contracts |
| Frontend | React + Vite + TypeScript | Tailwind, shadcn/ui, React Flow, TanStack Query | Three-column UI, live status |
| LLM | Anthropic API (Claude) | `langchain-anthropic` / `anthropic` | Planner, Coder, Analyst, chat |
| Orchestration | LangGraph | `langgraph` | Fixed run graph, retries, checkpoints |
| Chat agent | LangChain Deep Agents | `deepagents` | Planning, file access, skills loading |
| Database | Neon Postgres (cloud) | `psycopg` / SQLAlchemy | Runs, steps, metrics, manifests, chat history |
| Object storage | AWS S3 | `boto3` | All input and output files; presigned uploads |
| Vector DB | Qdrant Cloud | `qdrant-client` | Filtered search over reports and docs |
| Sandbox | Daytona (cloud) | `daytona` SDK | Running generated code; Docker fallback |
| Observability | Langfuse Cloud | `langfuse` (LangChain callback) | Trace per run and per chat turn |

**Configuration** — one `.env` read by the backend only; the frontend gets nothing secret:

```text
ANTHROPIC_API_KEY=            MODEL_MAIN=   MODEL_FAST=
AWS_ACCESS_KEY_ID=            AWS_SECRET_ACCESS_KEY=   AWS_REGION=   S3_BUCKET=
DATABASE_URL=                 # Neon pooled connection string
QDRANT_URL=                   QDRANT_API_KEY=   EMBED_MODEL=   EMBED_DIM=
DAYTONA_API_KEY=              DAYTONA_SNAPSHOT=
LANGFUSE_PUBLIC_KEY=          LANGFUSE_SECRET_KEY=   LANGFUSE_HOST=
```

**Libraries inside the sandbox**

| Library | Used for |
| --- | --- |
| gemmi | Reading powder-CIF loops (2θ, intensity, wavelength) generically |
| pymatgen | Reading the COD structure, computing expected reflections |
| numpy, scipy | Arrays, least-squares refinement of a and zero shift |
| lmfit | Pseudo-Voigt peak fitting with parameter uncertainties |
| pandas | Peak tables, CSV output |
| matplotlib | Measured-vs-fit and residual plots |
| ase | Optional; structure format conversion |

Note: pymatgen reads crystal-structure CIFs, not measured powder patterns. Reading the 640f scan needs gemmi (or a small custom parser); put this in `skills/xrd_powder_refinement.md` so the Coder does not rediscover it.

**API**

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/datasets` | Create dataset folder + manifest |
| POST | `/datasets/{id}/files` | Upload files (or return a presigned URL) |
| GET | `/datasets` | Tree + roles for the left panel |
| POST | `/datasets/rescan` | Re-index manifests into Neon |
| POST | `/chat` | Send a message; streams the reply |
| POST | `/runs` | Start a run: prompt, dataset ids, optional parent |
| GET | `/runs`, `/runs/{id}` | Run list and detail (plan, steps, metrics) |
| GET | `/runs/{id}/events` | SSE stream of step status changes |
| GET | `/runs/{id}/artifacts/{path}` | Plot, CSV or report |
| GET | `/runs/compare?a=&b=` | Metric and plan diff (stretch) |

## Implementation plan for Claude Code

Five phases, each a self-contained brief for one Claude Code session; every task has a "done when" check, and no phase starts until the previous gate passes.

**How to hand this over**

1. Export this doc as Markdown into the repo as `docs/SPEC.md`.
2. Create `CLAUDE.md` at the repo root containing the conventions below and a pointer to `docs/SPEC.md`.
3. Start each session with: "Read CLAUDE.md and docs/SPEC.md. Implement Phase N only. Plan first, then build, then run every done-when check and report results."
4. Tick tasks here as phases finish, so the team sees progress.

**Conventions for CLAUDE.md**

- Use the managed services in the stack table through their official SDKs; never self-host or reimplement them.
- Backend: FastAPI, Python 3.11, Pydantic models for every contract (run request, plan, step, step result, metric, manifest). Frontend: React + Vite + TypeScript.
- Secrets live only in the backend `.env`; the frontend and sandbox never receive keys.
- All LLM calls go through one client module with the Langfuse callback attached and model names from config.
- No number may appear in a report or chat answer unless it comes from `metrics.json`, a manifest or a Neon row.
- Unit tests with pytest for each backend module; mock LLM and sandbox calls in unit tests, use real services only in marked integration tests.
- Repo layout: `backend/app/` (api, agents, orchestration, sandbox, storage, retrieval, models), `backend/skills/`, `backend/tests/`, `frontend/src/` (panels, tabs, api), `docs/`.

### Phase 0 — Setup (hours 0–2)

- [ ] Scaffold the monorepo: FastAPI backend and Vite React TS frontend. Done when both start locally and the frontend calls a backend ping.
- [ ] Settings module reading `.env` (keys listed in the stack section). Done when a missing key fails startup with its name.
- [ ] `/health` endpoint checking Neon, S3, Qdrant, Daytona, Anthropic and Langfuse. Done when all six report OK.
- [ ] Neon schema migrations for datasets, runs, steps, artifacts, metrics, messages. Done when migrations apply cleanly on an empty database.
- [ ] Create S3 prefixes `datasets/` and `runs/`, and Qdrant collections with payload indexes. Done when a setup script is idempotent (runs twice without error).
- [ ] Daytona snapshot or create-time install with the sandbox libraries. Done when a trivial script runs and its output file comes back.

### Phase 1 — Data and gold answer (hours 2–6)

- [ ] Dataset API: create folder + manifest, upload via presigned URL, list as tree, rescan, manifest validation. Done when an upload without a valid manifest is rejected with a reason.
- [ ] Load NIST SRM 640f and COD 9008416 through that API with their manifests. Done when both appear in the dataset list with correct roles.
- [ ] Produce the reference analysis (see Risks section) in a notebook, human-checked. Done when refined a meets the success target and exact file tags are recorded.
- [ ] Write the four skills files from the agent section, including the reference analysis as the worked example. Done when a teammate reviews them for physics errors.

**Gate 1:** gold metrics exist and match the certified value within target.

### Phase 2 — Core agent loop, API only (hours 6–14)

- [ ] Pydantic contracts for run request, plan, step, step result, metric. Done when tests cover valid and invalid examples.
- [ ] `SandboxRunner` interface with `DaytonaRunner`: stage inputs, upload script, run with timeout, collect outputs, push to S3, record artifacts with SHA-256. Done when the gold analysis run through it reproduces the gold metrics.
- [ ] `LocalDockerRunner` with the same interface and no network. Done when the same check passes locally.
- [ ] Output checker enforcing the step contract. Done when a script that skips `metrics.json` fails with a clear message.
- [ ] Planner agent producing a validated `plan.json` and `plan.md` from prompt, selected manifests and skills. Done when three differently worded prompts all give valid plans.
- [ ] Coder agent with the bounded retry loop (max 2, last 60 lines of stderr fed back). Done when a deliberately broken first attempt is fixed on retry.
- [ ] Analyst agent writing `report.md` with a classification from the table. Done when it classifies the gold run as agreement.
- [ ] Claim checker. Done when a report containing an invented number is flagged and the run shows it.
- [ ] LangGraph run graph wiring the above, updating Neon step status and appending `experiment_log.md`. Done when a run's rows and files match.
- [ ] Metrics ingestion from `metrics.json` into Neon. Done when values match the file exactly.
- [ ] `POST /runs` and the SSE events stream. Done when a curl client sees each step change status.

**Gate 2:** one prompt through the API yields a report with refined a within target and all numbers traced, visible as one Langfuse trace.

### Phase 3 — Product surface (hours 14–30)

- [ ] Three-column layout with run list above four result tabs. Done when it works at 1280 px width.
- [ ] Data panel: bucket tree with role badges, upload with manifest form, dataset selection. Done when a new dataset can be added and used in a run from the browser.
- [ ] Chat panel with streamed replies and a run card per started run. Done when starting a run from chat shows its live status.
- [ ] Plan tab (read-only React Flow, colours from SSE, click a step for its code and log), Plots, Data and Report tabs with the claim badge. Done when every tab shows the selected run.
- [ ] Qdrant indexing of run reports on finish and dataset docs on upload, with the chosen embedding model. Done when a filtered search returns only matching material and status.
- [ ] Chat co-pilot (Deep Agent) with the seven tools; `start_run` needs user confirmation in the UI. Done when it answers a question about the last run using tool results only.
- [ ] Run-complete event posts a summary into the chat. Done when it appears without user input.

**Gate 3:** the full demo script runs from the browser with no terminal.

### Phase 4 — Harden and rehearse (hours 30–48)

- [ ] Follow-up runs with `parent_run_id`, and the compare view. Done when the demo's follow-up run shows a two-run comparison.
- [ ] Honest-failure paths: missing manifest, broken CIF, step timeout. Done when each shows a clear reason in the UI.
- [ ] Enforce limits: 120 s per step, 3 attempts, 6 steps, 50 MB outputs. Done when each limit has a test.
- [ ] Run five fresh runs and fill in the success-criteria table. Done when results are recorded in this doc.
- [ ] Record a fallback run video and rehearse the 4-minute demo twice.
- [ ] README with setup steps and the `.env` key list. Done when a teammate sets it up from scratch.

If Gate 2 slips past hour 18, drop Qdrant indexing and the follow-up flow first; keep the end-to-end run and the honest-failure case.

## Risks, demo script and reference analysis

The biggest risk is not the agents but the data: if the 640f file format surprises us, everything downstream waits, so it is checked in the first two hours.

| Risk | Likelihood | Effect | Mitigation |
| --- | --- | --- | --- |
| 640f file tags or format differ from expectations | Medium | Coder cannot parse; pipeline stalls | Hand-parse it in hour 1; record exact tags in the skill file |
| Coder writes wrong physics (e.g. default wavelength) | High | Plausible but wrong a | Reference analysis as gold; skill file rules; Analyst checks wavelength source |
| Daytona network restricted on our tier | Certain | Sandbox cannot reach S3 | Already designed for: backend stages files |
| Venue Wi-Fi or service outage during demo | Medium | Live run fails | Docker runner fallback; a recorded run ready to show |
| Anthropic rate limits during retries | Low | Slow runs | Retry cap of 2; Haiku-class model for chat |
| Qdrant embedding option not on our plan | Low | No search | FastEmbed in backend |
| Scope creep into canvas editing or paper RAG | High | Core loop unfinished | Day-1 gate: no stretch work until one full run passes |
| Judges challenge the science | Medium | Credibility | Units in Å, certificate cited, classification table, honest-failure case |

**Demo script (4 minutes)**

1. Show the bucket tree: the 640f dataset with its manifest, and the COD silicon structure.
2. Type: "Refine silicon's lattice parameter from the 640f scan and compare it with the certified value."
3. Plan tab fills; steps turn green. Point out one retry where the Coder fixed its own error.
4. Plots tab: measured vs fitted pattern, residuals. Data tab: refined a with uncertainty. Report tab: classification and the "all numbers traced" badge.
5. Ask in chat: "Why do the residuals trend?" Accept the follow-up run; show the comparison between the two runs.
6. Upload a file with no manifest or a broken CIF; show it refused with a reason.

**Reference analysis (gold answer).** Before any agent work, one person produces a hand-checked run of the six science steps; its outputs are the target the agents must match and the worked example in `skills/xrd_powder_refinement.md`. It must:

- Read the 640f scan with gemmi, taking 2θ, intensity and wavelength from the file's own tags (record the exact tag names found).
- Load COD 9008416 with pymatgen and list expected reflections in the scan's 2θ range, using the file's wavelength.
- Fit each peak with a pseudo-Voigt plus linear background (lmfit) and record centre and uncertainty.
- Refine a and a zero-shift term by least squares over all peak centres (scipy), with uncertainties.
- Write `peaks.csv`, `metrics.json` (a\_refined, zero\_shift, wavelength, each with unit, uncertainty, method) and the fit and residual plots.
- Agree with the certified value within the success target, or have the gap explained.
