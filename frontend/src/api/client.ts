// Thin typed wrappers over the backend API (proxied at /api). No keys live here.

export const API = "/api";

export type Role = "measured_pattern" | "reference_structure" | "reference_value";
export interface DatasetNode { id: string; role: Role | null; valid: boolean; problem: string | null; files: string[] }
export type StepStatus = "pending" | "running" | "retrying" | "done" | "failed";
export interface Step { idx: number; name: string; status: StepStatus; attempts: number; error: string | null;
  code_key: string | null; stdout_key: string | null }
export interface Metric { name: string; value: number | string | null; unit: string | null;
  uncertainty: number | null; method: string | null; source: string }
export interface PlanStep { idx: number; name: string; goal: string; dataset_ids: string[];
  uses_previous_outputs: string[]; outputs: string[]; skill: string }
export interface ClaimCheck { passed: boolean; checked: number; untraced: { number: string; line: number; context: string }[] }
export interface Headline { a_refined: number; uncertainty: number | null; unit: string | null }
export interface RunListItem { id: string; prompt: string; status: string; dataset_ids: string[];
  parent_run_id: string | null; classification: string | null; claim_passed: boolean | null;
  started_at: string | null; finished_at: string | null; headline: Headline | null }
export interface RunDetail extends Omit<RunListItem, "claim_passed"> {
  plan: { title: string; summary: string; steps: PlanStep[] } | null; error: string | null;
  claim_check: ClaimCheck | null; steps: Step[]; metrics: Metric[];
  artifacts: { step_idx: number | null; kind: string; path: string; sha256: string }[] }
export interface ProposedRun { prompt: string; dataset_ids: string[]; parent_run_id: string | null }
export interface ChatMessage { role: "user" | "assistant"; content: string; run_id?: string | null;
  claim_check?: ClaimCheck; proposed_run?: ProposedRun | null; tools?: string[] }

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return r.json() as Promise<T>;
}

export const api = {
  datasets: () => fetch(`${API}/datasets`).then(json<DatasetNode[]>),
  manifest: (id: string) => fetch(`${API}/datasets/${id}/manifest`).then(json<Record<string, unknown>>),
  createDataset: (manifest: Record<string, unknown>, readme?: string) =>
    fetch(`${API}/datasets`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ manifest, readme }) }).then(json),
  saveManifest: (id: string, manifest: Record<string, unknown>) =>
    fetch(`${API}/datasets/${id}/manifest`, { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(manifest) }).then(json),
  upload: (id: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return fetch(`${API}/datasets/${id}/files`, { method: "POST", body: fd }).then(json<{ saved: string[] }>);
  },
  rescan: () => fetch(`${API}/datasets/rescan`, { method: "POST" }).then(json),
  runs: () => fetch(`${API}/runs`).then(json<RunListItem[]>),
  run: (id: string) => fetch(`${API}/runs/${id}`).then(json<RunDetail>),
  startRun: (body: ProposedRun & { session_id: string }) =>
    fetch(`${API}/runs`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) }).then(json<{ id: string }>),
  artifactText: (runId: string, path: string) => fetch(`${API}/runs/${runId}/artifacts/${path}`).then((r) => r.text()),
  artifactUrl: (runId: string, path: string) => `${API}/runs/${runId}/artifacts/${path}`,
  health: () => fetch(`${API}/health`).then(json<Health>),
  ping: () => fetch(`${API}/ping`).then(json<{ ok: boolean; mode: string }>),
  chatHistory: (session: string) => fetch(`${API}/chat/${session}`).then(json<ChatMessage[]>),
};

export interface Health { mode: string; all_ok: boolean; services: Record<string, { ok: boolean; detail: string }> }

export interface SseEvent { event: string; data: any }

/** POST /chat returns an SSE stream; EventSource only does GET, so parse the stream by hand. */
export async function* chatStream(session_id: string, message: string, dataset_ids: string[]): AsyncGenerator<SseEvent> {
  const r = await fetch(`${API}/chat`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id, message, dataset_ids }) });
  if (!r.ok || !r.body) throw new Error(`chat failed: ${r.status}`);
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      let event = "message", data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) yield { event, data: JSON.parse(data) };
    }
  }
}

export function sessionId(): string {
  try {
    const k = "corefine-session";
    let s = localStorage.getItem(k);
    if (!s) { s = crypto.randomUUID().slice(0, 18); localStorage.setItem(k, s); }
    return s;
  } catch {
    return "session-" + Math.random().toString(36).slice(2, 12);
  }
}

// --- All-electron DFT inputs ------------------------------------------------

export interface DftCheck { check: string; ok: boolean | null; detail: string; code?: string | null }
export interface DftJobListItem { id: string; created: string; structure: string; formula: string; functional: string;
  kmesh: number[]; codes: string[]; passed: boolean; n_checks: number; n_failed: number }
export interface DftCell { formula: string; natoms: number; spacegroup: string; volume_A3: number;
  volume_per_atom_A3: number; lattice_lengths_A: number[]; nearest_neighbour_A: number }
export interface DftJob {
  id: string; files: string[];
  provenance: { created: string; request: { structure: string; codes: string[]; functional: string; kmesh: number[]; notes: string };
    source: { source: string; url: string | null; sha256: string | null; declared_spacegroup: string | null; notes: string[] };
    cell: DftCell; code_versions: Record<string, string | null>;
    generated: Record<string, { label: string; method: string; main_file: string; files: string[];
      set_explicitly: Record<string, string>; defaults: { source: string; values: Record<string, unknown> } }> };
  checks: { passed: boolean; results: DftCheck[]; reference: Record<string, any>; codes: Record<string, any> };
  runs: Record<string, DftRun>;
  plan: DftPlan | null;
  studies: { convergence?: ConvergenceStudy; eos?: EosStudy; raman?: Record<string, RamanStudy> };
}
export interface RamanMode { frequency_cm1: number; degeneracy: number; label: string | null; acoustic: boolean; raman_active: boolean; ir_active: boolean }
export interface RamanStudy { status: string; message?: string; code: string; kmesh?: number[]; point_group?: string; modes?: RamanMode[];
  spectrum?: { x: number[]; y: number[]; fwhm_cm1: number; note: string }; notes?: string[]; n_displacements?: number }
export interface Bridge { material: string; experiment_reference: string | null; notes: string[];
  experiment: { run: string; a_A: number; uncertainty_A: number | null; temperature_C: number | null; classification: string | null }[];
  certified: { dataset: string; a_A: number; uncertainty_A: number | null; temperature_C: number | null; source: string | null }[];
  theory: { set: string; code: string; functional: string; a0_A: number; B0_GPa: number | null; kmesh: number[] | null;
    vs_experiment_percent: number | null; pressure_equivalent_GPa?: number; reference?: string }[];
  raman: { set: string; code: string; functional: string; frequency_cm1: number; label: string | null; raman_active: boolean; ir_active: boolean }[] }
export interface StudyPoint { ok: boolean; e_per_atom_eV?: number; volume_per_atom_A3?: number; error?: string; scf_iterations?: number }
export interface ConvergenceStudy { status: string; message?: string; criterion: string; tol_meV_per_atom: number;
  codes: Record<string, { kpoints: (StudyPoint & { kmesh: number[] })[]; basis: (StudyPoint & { basis_scale: number })[];
    converged_kmesh: number[] | null; converged_basis_scale: number | null }> }
export interface EosFit { V0_A3_per_atom: number; E0_eV_per_atom: number; B0_GPa: number; B0_prime: number; V0_over_source: number }
export interface EosStudy { status: string; message?: string; protocol: string; scales: number[];
  codes: Record<string, { points: (StudyPoint & { scale: number })[]; fit?: EosFit; error?: string;
    settings: { kmesh: number[]; basis_scale: number; from_convergence: boolean } }>;
  delta_meV_per_atom: Record<string, number> }
export interface XrdMeasured { dataset: string; file: string; files: string[]; x: number[]; y: number[]; n_points: number;
  range: [number, number]; wavelength_A: number | null; wavelength_source: string | null; radiation: string | null }
export interface XrdPeak { two_theta: number; intensity: number; d_A: number; hkl: string; multiplicity: number }
export interface XrdSimulated { label: string; wavelength_A: number; peaks: XrdPeak[]; note: string }
export interface DftCode { name: string; label: string; method: string; available: boolean; reason: string; functionals: string[] }
export interface DftResults { converged: boolean | null; total_energy_eV: number | null; fermi_eV: number | null;
  gap_eV: number | null; scf_iterations: number | null; warnings: string[]; raw: Record<string, unknown> }
export interface DftRun { code: string; target: string; kind: string; status: string; started?: string; finished?: string | null;
  message: string; attempts?: number; remote_job_id?: string | null; remote_dir?: string; results: DftResults | null; updated: string }
export interface DftTarget { name: string; kind: "local" | "slurm"; host: string | null; codes: string[]; confirm: boolean }
export interface DftTool { name: string; label: string; license: string; size: string; source: string; installable: boolean;
  status: string; message: string; version: string | null }
export interface DftTools { tools: DftTool[]; not_installable: Record<string, string>; code_tools: Record<string, string[]>; local: Record<string, string> }
export interface MpMaterial { id: string; formula: string; nsites: number; spacegroup: string | null; e_above_hull_eV: number | null;
  band_gap_eV: number | null; is_metal: boolean | null; ordering: string | null; stable: boolean; fits_laptop: boolean }
export interface PlanDecision { field: string; value: string; reason: string; source: "user" | "rule" | "agent" | "materials_project" }
export interface DftPlan { request: Record<string, unknown>; decisions: PlanDecision[]; warnings: string[]; blocked: string[];
  planner: "rules" | "agent"; material?: MpMaterial; goal?: string | null }
export interface DftJobBody { prompt?: string; structure?: string; codes?: string[]; functional?: string; kmesh?: number[] }

export const dft = {
  config: () => fetch(`${API}/dft/config`).then(json<{ codes: DftCode[]; prompt: boolean }>),
  jobs: () => fetch(`${API}/dft/jobs`).then(json<DftJobListItem[]>),
  job: (id: string) => fetch(`${API}/dft/jobs/${id}`).then(json<DftJob>),
  create: (body: DftJobBody) => fetch(`${API}/dft/jobs`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) }).then(json<{ id: string; passed: boolean }>),
  file: (id: string, path: string) => fetch(`${API}/dft/jobs/${id}/files/${path}`).then((r) => r.text()),
  fileUrl: (id: string, path: string) => `${API}/dft/jobs/${id}/files/${path}`,
  archiveUrl: (id: string) => `${API}/dft/jobs/${id}/archive`,
  targets: () => fetch(`${API}/dft/targets`).then(json<DftTarget[]>),
  tools: () => fetch(`${API}/dft/tools`).then(json<DftTools>),
  startStudy: (id: string, kind: "convergence" | "eos", kmesh?: number[] | null) => fetch(`${API}/dft/jobs/${id}/studies/${kind}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kmesh: kmesh ?? null }) }).then(json),
  startRaman: (id: string, code: string, kmesh?: number[] | null) => fetch(`${API}/dft/jobs/${id}/studies/raman`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code, kmesh: kmesh ?? null }) }).then(json),
  planPreview: (material: string, functional: string) =>
    fetch(`${API}/dft/plan-preview?material=${encodeURIComponent(material)}&functional=${functional}`).then(json<{ plan: DftPlan; material: MpMaterial }>),
  bridge: (material: string) => fetch(`${API}/bridge?material=${encodeURIComponent(material)}`).then(json<Bridge>),
  saveEos: (id: string, code: string) => fetch(`${API}/dft/jobs/${id}/studies/eos/${code}/save`, { method: "POST" })
    .then(json<{ dataset: string }>),
  searchMaterials: (q: string) => fetch(`${API}/dft/materials?q=${encodeURIComponent(q)}`).then(json<MpMaterial[]>),
  workflow: (body: { material: string; goal?: string; functional?: string; kmesh?: number[] | null; codes?: string[] }) =>
    fetch(`${API}/dft/workflow`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(json<{ id: string; plan: DftPlan; runs: string[]; checks_passed: boolean }>),
  installTool: (name: string) => fetch(`${API}/dft/tools/${name}/install`, { method: "POST" }).then(json),
  startRun: (id: string, code: string, target: string) => fetch(`${API}/dft/jobs/${id}/runs`, { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code, target }) }).then(json<DftRun>),
  importResults: (id: string, code: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return fetch(`${API}/dft/jobs/${id}/runs/${code}/import`, { method: "POST", body: fd }).then(json<DftRun>);
  },
  upload: (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    return fetch(`${API}/dft/upload`, { method: "POST", body: fd }).then(json<{ structure: string; name: string; cell: DftCell }>);
  },
};

export interface XrdMatch { hkl: string; two_theta_obs: number; two_theta_model: number; two_theta_fit: number;
  delta_model_deg: number; residual_deg: number; rel_intensity_obs: number; rel_intensity_model: number }
export interface XrdCompare { file: string; wavelength_A: number; n_matched: number; n_measured: number; lattice_scale: number;
  linear_strain_percent: number; volume_ratio: number; zero_shift_deg: number; rms_residual_deg: number | null; tol_deg: number;
  pressure_equivalent_GPa?: number; pressure_note?: string; bulk_modulus_source: string | null; matched: XrdMatch[];
  unmatched_measured: number[]; model_lattice_A: number[]; implied_lattice_A: number[]; model: string;
  model_meta: Record<string, unknown>; profile: { x: number[]; y: number[]; fwhm_deg: number; note: string };
  model_reflections: XrdPeak[]; measured_peaks: { two_theta: number; fwhm: number; rel_intensity: number }[] }
export interface XrdIdentify { file: string; formula: string; n_peaks: number; ranked: { candidate: string; explained_fraction: number;
  n_matched: number; n_strong: number; lattice_scale: number; rms_residual_deg: number | null; strong_model_lines_missing: string[];
  score: number; material: MpMaterial }[] }

export const xrd = {
  compare: (body: { dataset: string; file?: string; structure: string; volume_scale?: number; bulk_modulus_GPa?: number }) =>
    fetch(`${API}/xrd/compare`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(json<XrdCompare>),
  identify: (body: { dataset: string; file?: string; formula?: string }) =>
    fetch(`${API}/xrd/identify`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(json<XrdIdentify>),
  measured: (id: string, file?: string) =>
    fetch(`${API}/xrd/measured/${id}${file ? `?file=${encodeURIComponent(file)}` : ""}`).then(json<XrdMeasured>),
  simulate: (body: { structure: string; wavelength_A: number; two_theta_min?: number; two_theta_max?: number; volume_scale?: number }) =>
    fetch(`${API}/xrd/simulate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(json<XrdSimulated>),
  importMp: (mp_id: string) => fetch(`${API}/xrd/import/materials-project`, { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mp_id }) }).then(json<{ dataset: string }>),
};
