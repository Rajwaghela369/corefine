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
