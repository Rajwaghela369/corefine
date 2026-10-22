import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrainCircuit, Columns3, FileText, LayoutDashboard, LineChart, Table2, X } from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { api, chatStream, dft, type ClaimCheck, type Engine, type GroupRun, type GroupView } from "../api/client";
import { Legend, Node } from "../components/Flow";
import { Dot, Sections } from "../components/Sections";
import { Button, Empty, PanelHeader, Status, Tag, clock, cn, inputCls } from "../components/ui";
import { Welcome, WelcomeSection } from "../components/Welcome";
import { XrdChart, type Curve, type Overlay } from "../components/XrdChart";
import { ClaimBadge } from "../panels/ChatPanel";
import { DataPane, PlotsPane, ReportPane } from "./Panes";

export const ENGINE_COLOR: Record<string, string> = { agents: "#121826", gsas2: "#c2410c", maud: "#15803d" };
const ENGINE_LABEL: Record<string, string> = { agents: "Agents", gsas2: "GSAS-II", maud: "MAUD" };
const METHOD: Record<string, string> = { agents: "Claude writes and runs the fitting code", gsas2: "Rietveld refinement (APS)",
  maud: "Rietveld + microstructure (Lutterotti)" };
const f = (v: number | null | undefined, d = 6) => (v == null ? "—" : v.toFixed(d));
const live = (s: string) => ["queued", "planning", "running", "analysing", "retrying"].includes(s);

/** Experiment · XRD, laid out like Theory · DFT: the form and the list of analyses on the left, the selected analysis
 *  with its header, summary cells and tabs on the right. */
export function XrdView({ session, runId, setRunId }: { session: string; runId: string | null; setRunId: (id: string | null) => void }) {
  // a ?tab= link opens that tab once; read it before the address bar is rewritten
  const [tab] = useState(() => new URLSearchParams(window.location.search).get("tab") ?? undefined);
  return (
    <div className="grid h-full min-h-0 grid-cols-[360px_1fr]">
      <div className="min-h-0 border-r border-line"><XrdForm session={session} selected={runId} onSelect={setRunId} /></div>
      <div className="flex min-h-0 flex-col">
        {runId ? <AnalysisWorkspace key={runId} id={runId} tab={tab} onClose={() => setRunId(null)} /> : <XrdWelcome onOpen={setRunId} />}
      </div>
    </div>
  );
}

// --- left: form and analyses -------------------------------------------------------------

function XrdForm({ session, selected, onSelect }: { session: string; selected: string | null; onSelect: (id: string) => void }) {
  const qc = useQueryClient();
  const ds = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const measured = (ds.data ?? []).filter((d) => d.valid && d.role === "measured_pattern");
  const refs = (ds.data ?? []).filter((d) => d.valid && d.role === "reference_structure");
  const [scan, setScan] = useState("");
  const [ref, setRef] = useState("");
  const scanId = scan || measured[0]?.id || "";
  const material = measured.find((d) => d.id === scanId)?.material;
  const matching = refs.filter((r) => r.material === material);
  const refId = ref && refs.some((r) => r.id === ref) ? ref : matching[0]?.id ?? "";
  useEffect(() => { setRef(""); }, [scanId]);
  const manifest = useQuery({ queryKey: ["manifest", scanId], queryFn: () => api.manifest(scanId), enabled: !!scanId });
  const inst = (manifest.data?.instrument ?? {}) as Record<string, unknown>;
  const engines = useQuery({ queryKey: ["engines"], queryFn: api.engines,
    refetchInterval: (q) => (q.state.data?.some((e) => e.install?.status === "installing") ? 3000 : false) });
  const [picked, setPicked] = useState<Engine[] | null>(null);
  const available = (engines.data ?? []).filter((e) => e.available).map((e) => e.name);
  const tools = (picked ?? available.filter((e) => e !== "agents")).filter((e) => available.includes(e));
  const [goal, setGoal] = useState("");
  const [error, setError] = useState<string | null>(null);
  const toggle = (e: Engine) => setPicked((p) => { const cur = p ?? tools; return cur.includes(e) ? cur.filter((x) => x !== e) : [...cur, e]; });
  const start = useMutation({
    mutationFn: () => api.startRun({ dataset_ids: [scanId, refId].filter(Boolean), engines: tools, parent_run_id: null, session_id: session,
      prompt: goal.trim() || `Refine the lattice parameters of ${material ?? "the sample"} from ${scanId} and compare them with the certified values` }),
    onSuccess: (r) => { setError(null); qc.invalidateQueries({ queryKey: ["runs"] }); onSelect(r.id); },
    onError: (e) => setError(e instanceof Error ? e.message : String(e)),
  });
  const install = useMutation({ mutationFn: (tool: string) => dft.installTool(tool),
    onSettled: () => qc.invalidateQueries({ queryKey: ["engines"] }), onError: (e) => setError(String(e)) });

  return (
    <div className="flex h-full flex-col bg-surface">
      <PanelHeader title="New XRD analysis" meta="powder diffraction" />
      <div className="space-y-4 overflow-auto border-b border-line p-4">
        <div>
          <div className="mb-1.5 text-xs font-medium text-ink-2">Measured scan</div>
          {measured.length ? <select className={inputCls} value={scanId} onChange={(e) => setScan(e.target.value)}>
            {measured.map((d) => <option key={d.id} value={d.id}>{d.id}{d.material ? ` · ${d.material}` : ""}</option>)}</select>
            : <p className="text-[11px] text-muted">No measured patterns in Storage yet.</p>}
          {scanId && manifest.data && <p className="mt-1 text-[10.5px] leading-4 text-muted">
            {String(inst.radiation ?? "")} · λ = {String(inst.wavelength_A ?? "?")} Å {inst.ka2_present ? "· Kα1 + Kα2" : ""}
            {manifest.data.reference_values ? " · certified value on file (hidden from the analysis)" : ""}</p>}
        </div>
        <div>
          <div className="mb-1.5 text-xs font-medium text-ink-2">Reference structure</div>
          {refs.length ? <select className={inputCls} value={refId} onChange={(e) => setRef(e.target.value)}>
            {!refId && <option value="">none for {material}</option>}
            {refs.map((d) => <option key={d.id} value={d.id}>{d.id}{d.material ? ` · ${d.material}` : ""}{d.material === material ? "" : " (other material)"}</option>)}</select>
            : <p className="text-[11px] text-muted">No reference structures in Storage yet.</p>}
          <p className="mt-1 text-[10.5px] text-muted">Space group, atom positions and the starting cell; the refinement starts from it.</p>
        </div>
        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <span className="text-xs font-medium text-ink-2">Analysis tools</span>
            <span className="text-[11px] text-muted">{available.length} of {engines.data?.length ?? 3} available here</span>
          </div>
          {(engines.data ?? []).filter((e) => !e.available && e.tool).map((e) => (
            <div key={e.name} className="mb-1.5 rounded-md border border-line bg-subtle/60 p-2 text-[11px] leading-4">
              <div className="flex items-center justify-between gap-2">
                <span><span className="font-medium text-ink-2">{e.label}</span> <span className="text-muted">not installed</span></span>
                <Button size="sm" variant="secondary" disabled={e.install?.status === "installing" || install.isPending}
                  onClick={() => install.mutate(e.tool!)}>{e.install?.status === "installing" ? "Installing…" : "Install"}</Button>
              </div>
              <div className="text-muted">{e.install?.license}, {e.install?.size}</div>
              {e.install?.status === "installing" && <div className="text-accent">{e.install.message}</div>}
              {e.install?.status === "failed" && <div className="text-bad">Install failed: {e.install.message}</div>}
            </div>))}
          <div className="grid grid-cols-3 gap-2">
            {(engines.data ?? []).map((e) => (
              <button key={e.name} onClick={() => toggle(e.name)} disabled={!e.available} title={e.available ? e.about : e.reason}
                className={cn("rounded-md border px-2 py-1.5 text-left text-xs disabled:opacity-40",
                  tools.includes(e.name) ? "border-accent bg-accent-soft text-accent" : "border-line-strong text-ink-2")}>
                <div className="font-medium">{e.label}</div>
                <div className="text-[10px] leading-3 text-muted">{METHOD[e.name]}</div>
              </button>))}
          </div>
          <p className="mt-1.5 text-[11px] leading-4 text-muted">Pick more than one to compare them on the same scan. Every tool records
            each decision and step, shown under Reasoning.</p>
        </div>
        {tools.includes("agents") && <textarea className={cn(inputCls, "h-14 py-1.5")} value={goal} onChange={(e) => setGoal(e.target.value)}
          placeholder="Instructions for the agents (optional), e.g. fit Kα1/Kα2 doublets and refine a with a zero shift" />}
        <Button variant="primary" className="w-full" disabled={!scanId || !refId || !tools.length || start.isPending} onClick={() => start.mutate()}>
          {start.isPending ? "Starting…" : !refId ? "Pick a reference structure" : !tools.length ? "Pick at least one tool"
            : `Analyse ${scanId} with ${tools.map((t) => ENGINE_LABEL[t]).join(" + ")}`}</Button>
        <Assistant session={session} datasets={[scanId, refId].filter(Boolean)} />
        {error && <div className="rounded-md border border-bad/20 bg-bad-soft p-2.5 text-xs text-bad"><b>Refused.</b> {error}</div>}
      </div>
      <div className="flex h-9 shrink-0 items-center border-b border-line px-4 text-xs font-medium">Analyses</div>
      <div className="min-h-0 flex-1 overflow-auto"><AnalysisList selected={selected} onSelect={onSelect} /></div>
    </div>
  );
}

function Assistant({ session, datasets }: { session: string; datasets: string[] }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<{ text: string; claim?: ClaimCheck; tools: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function ask() {
    setBusy(true); setError(null); setAnswer({ text: "", tools: [] });
    try {
      for await (const ev of chatStream(session, q.trim(), datasets)) {
        if (ev.event === "tool_call") setAnswer((a) => ({ ...(a ?? { text: "" }), tools: [...(a?.tools ?? []), ev.data.name] }));
        if (ev.event === "answer") setAnswer((a) => ({ text: ev.data.content, claim: ev.data.claim_check, tools: a?.tools ?? [] }));
        if (ev.event === "error") throw new Error(ev.data.message);
      }
    } catch (e) { setAnswer(null); setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  return (
    <details className="rounded-md border border-line">
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-ink-2">Or ask the assistant</summary>
      <div className="space-y-2 border-t border-line p-3">
        <textarea className={cn(inputCls, "h-14 py-1.5")} value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Is this dataset documented well enough to reuse? Which tool fits the scan better?" />
        <Button size="sm" variant="secondary" disabled={!q.trim() || busy} onClick={ask}>{busy ? "Answering…" : "Ask"}</Button>
        {answer && <div className="space-y-1 text-[12px] leading-5 text-ink-2">
          {answer.tools.length > 0 && <div className="text-[10.5px] text-faint">looked at: {[...new Set(answer.tools)].join(", ")}</div>}
          <div className="whitespace-pre-wrap">{answer.text}</div>{answer.claim && <ClaimBadge c={answer.claim} />}</div>}
        {error && <p className="text-[11px] text-bad">{error}</p>}
      </div>
    </details>
  );
}

interface Item { key: string; runs: { id: string; engine: string; status: string; a?: number }[]; dataset: string; prompt: string; started: string | null }

function AnalysisList({ selected, onSelect }: { selected: string | null; onSelect: (id: string) => void }) {
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs,
    refetchInterval: (q) => (q.state.data?.some((r) => live(r.status)) ? 3000 : false) });
  const items = useMemo(() => {
    const m = new Map<string, Item>();
    for (const r of runs.data ?? []) {
      const key = r.group_id ?? r.id;
      const it = m.get(key) ?? { key, runs: [], dataset: r.dataset_ids[0], prompt: r.prompt, started: r.started_at };
      it.runs.push({ id: r.id, engine: r.engine ?? "agents", status: r.status, a: r.headline?.a_refined });
      m.set(key, it);
    }
    return [...m.values()];
  }, [runs.data]);
  if (runs.data && !items.length) return <Empty title="No analyses yet">Start one above; it will be listed here.</Empty>;
  return (
    <ul className="divide-y divide-line">
      {items.map((it) => {
        const ids = it.runs.map((r) => r.id);
        const sel = !!selected && ids.includes(selected);
        return (
          <li key={it.key}>
            <button onClick={() => onSelect(ids[ids.length - 1])} className={cn("w-full px-4 py-2.5 text-left hover:bg-subtle", sel && "bg-accent-soft hover:bg-accent-soft")}>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[12px] font-semibold">{it.dataset}</span>
                <span className="ml-auto flex gap-1">{it.runs.slice().reverse().map((r) => (
                  <span key={r.id} className="rounded px-1 text-[10.5px] font-medium text-white" style={{ background: ENGINE_COLOR[r.engine] }}
                    title={`${r.id} · ${r.status}`}>{ENGINE_LABEL[r.engine]}{r.status === "failed" ? " ✕" : live(r.status) ? " …" : ""}</span>))}</span>
              </div>
              <div className="mt-0.5 flex gap-3 font-mono text-[11px] text-muted">
                {it.runs.slice().reverse().filter((r) => r.a).map((r) => <span key={r.id}>a = {r.a!.toFixed(5)}</span>)}
                <span className="ml-auto font-sans">{clock(it.started)}</span></div>
            </button>
          </li>);
      })}
    </ul>
  );
}

function XrdWelcome({ onOpen }: { onOpen: (id: string) => void }) {
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  return (
    <Welcome title="Experiment: XRD analysis"
      intro="Pick a measured powder scan and the tools to analyse it with: agents that write the fitting code, GSAS-II, MAUD, or several at once
        to compare. Every analysis records its reasoning: each decision before fitting, each refinement stage and what it changed,
        the comparison with the certified value, and a report whose numbers are traced to files."
      steps={[
        { icon: Table2, title: "Choose the scan", text: "A measured pattern and a reference structure from Storage; its wavelength and Kα2 facts come from its manifest." },
        { icon: Columns3, title: "Choose the tools", text: "Agents, GSAS-II, MAUD. With more than one, the results are compared on one plot and one table." },
        { icon: BrainCircuit, title: "Follow the reasoning", text: "Each step, who took it and why, with retries and warnings, then the result against the certificate." },
      ]}>
      {(runs.data?.length ?? 0) > 0 && <WelcomeSection title="Recent analyses">
        <div className="grid gap-2 sm:grid-cols-2">
          {runs.data!.slice(0, 6).map((r) => (
            <button key={r.id} onClick={() => onOpen(r.id)} className="rounded-lg border border-line bg-surface px-3 py-2.5 text-left hover:border-accent">
              <div className="flex items-center gap-2"><span className="font-mono text-[12px] font-semibold">{r.dataset_ids[0]}</span>
                <Tag>{ENGINE_LABEL[r.engine ?? "agents"]}</Tag><span className="ml-auto"><Status status={r.status} /></span></div>
              {r.headline && <div className="mt-0.5 font-mono text-[11.5px] text-muted">a = {r.headline.a_refined.toFixed(6)} Å</div>}
            </button>))}
        </div>
      </WelcomeSection>}
    </Welcome>
  );
}

// --- right: one analysis (one run, or a group of runs on the same scan) ------------------------

function AnalysisWorkspace({ id, tab, onClose }: { id: string; tab?: string; onClose: () => void }) {
  const run = useQuery({ queryKey: ["run", id], queryFn: () => api.run(id) });
  const key = run.data ? run.data.group_id ?? run.data.id : null;
  const g = useQuery({ queryKey: ["group", key], queryFn: () => api.group(key!), enabled: !!key,
    refetchInterval: (q) => (q.state.data?.runs.some((r) => live(r.status)) ? 2500 : false) });
  if (run.isError) return <Empty title="Could not load this analysis">{String(run.error)}</Empty>;
  if (!g.data) return <Empty title="Loading…" />;
  const d = g.data;
  const anyLive = d.runs.some((r) => live(r.status));
  const failed = d.runs.filter((r) => r.status === "failed").length;
  const cert = d.certified ?? {};
  const sections = [
    { key: "overview", label: "Overview", icon: LayoutDashboard, badge: anyLive ? <Dot tone="run" /> : undefined, body: <OverviewPane d={d} /> },
    { key: "reasoning", label: "Reasoning", icon: BrainCircuit, body: <ReasoningPane d={d} />,
      badge: failed ? <Dot tone="bad" /> : undefined },
    ...(d.runs.length > 1 ? [{ key: "compare", label: "Compare tools", icon: Columns3, body: <ComparePane d={d} /> }] : []),
    { key: "plots", label: "Plots", icon: LineChart, body: <PerRun d={d} render={(r) => <PlotsPane run={r} />} /> },
    { key: "data", label: "Data", icon: Table2, body: <PerRun d={d} render={(r) => <DataPane run={r} />} /> },
    { key: "report", label: "Report", icon: FileText, body: <PerRun d={d} render={(r) => <ReportPane run={r} />} /> },
  ];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-line bg-surface">
        <div className="flex items-center gap-3 px-5 pb-2 pt-3">
          <h1 className="text-[15px] font-semibold">{d.material} <span className="font-normal text-muted">· {d.dataset} · {d.runs.map((r) => r.label).join(" + ")}</span></h1>
          {anyLive ? <Tag tone="run">running</Tag> : failed ? <Tag tone="bad">{failed} of {d.runs.length} failed</Tag>
            : <Tag tone="ok">{d.runs.length === 1 ? "done" : `${d.runs.length} tools done`}</Tag>}
          <button onClick={onClose} title="Close and go back to the start page" aria-label="Close"
            className="ml-auto rounded p-1 text-muted hover:bg-subtle hover:text-ink"><X size={15} /></button>
        </div>
        <div className="grid grid-cols-4 border-t border-line">
          <Cellv label="Measured scan" value={d.measured?.file ?? "—"} small />
          <Cellv label="Wavelength" value={`${d.instrument?.wavelength_A ?? "—"} Å`} sub={`${d.instrument?.radiation ?? ""}${d.instrument?.ka2_present ? " · Kα1 + Kα2" : ""}`} mono />
          <Cellv label="Certified" value={cert.a_A != null ? `a ${f(cert.a_A)} Å` : "none on file"} sub={cert.c_A != null ? `c ${f(cert.c_A)} Å` : cert.a_uncertainty_A ? `± ${cert.a_uncertainty_A} Å (k = 2)` : undefined} mono />
          <div className="border-l border-line px-5 py-2.5">
            <div className="text-[11px] text-muted">Refined a</div>
            {d.runs.map((r) => <div key={r.id} className="flex items-center gap-2 font-mono text-[12.5px]">
              <span className="w-14 font-sans text-[11px] font-medium" style={{ color: ENGINE_COLOR[r.engine] }}>{r.label}</span>
              {r.metrics.a_refined?.value != null ? f(r.metrics.a_refined.value) : <Status status={r.status} />}</div>)}
          </div>
        </div>
      </div>
      <Sections key={id} initial={tab} sections={sections} />
    </div>
  );
}

function Cellv({ label, value, sub, mono, small }: { label: string; value: string; sub?: string; mono?: boolean; small?: boolean }) {
  return (
    <div className="min-w-0 border-l border-line px-5 py-2.5 first:border-l-0">
      <div className="text-[11px] text-muted">{label}</div>
      <div className={cn("mt-0.5 truncate font-medium", small ? "font-mono text-[12px]" : "text-[15px]", mono && "tabular font-mono")} title={value}>{value}</div>
      {sub && <div className="truncate text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

function OverlayChart({ d, height = 340 }: { d: GroupView; height?: number }) {
  const [log, setLog] = useState(true);
  const curves: Curve[] = useMemo(() => d.runs.filter((r) => r.curve)
    .map((r) => ({ label: `${r.label} calculated`, color: ENGINE_COLOR[r.engine], x: r.curve!.x, y: r.curve!.calculated })), [d]);
  const overlays: Overlay[] = useMemo(() => d.runs.filter((r) => r.reflections?.length)
    .map((r) => ({ label: r.label, color: ENGINE_COLOR[r.engine], peaks: r.reflections!.map((p) => ({ ...p, d_A: 0, multiplicity: 0 })) })), [d]);
  if (!d.measured) return null;
  return (
    <div>
      <div className="flex items-center gap-3 px-4 py-2 text-[11.5px]">
        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[#1f4fd1]" />measured</span>
        {d.runs.map((r) => <span key={r.id} className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: ENGINE_COLOR[r.engine] }} />{r.label}{r.curve ? " (dashed: calculated)" : ""}</span>)}
        <label className="ml-auto inline-flex items-center gap-1 text-muted"><input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} /> log</label>
      </div>
      <div className="px-2"><XrdChart x={d.measured.x} y={d.measured.y} log={log} overlays={overlays} curves={curves} height={height} /></div>
      <p className="px-4 pb-2 text-[11px] text-muted">Ticks: reflection positions from each tool's refined cell (computed by CoRefine from that cell).
        Dashed: a tool's own calculated pattern, where it exports one (GSAS-II). Drag to zoom into a peak; double-click to reset.</p>
    </div>
  );
}

function ResultsTable({ d }: { d: GroupView }) {
  const cert = d.certified ?? {};
  const hex = d.runs.some((r) => r.metrics.c_refined?.value != null);
  const v = (r: GroupRun, k: string) => r.metrics[k]?.value ?? null;
  return (
    <table className="w-full text-[12px]">
      <thead><tr className="border-b border-line text-left text-[11px] text-muted">
        <th className="py-1.5 font-medium">Tool</th><th className="font-medium">a (Å)</th>{hex && <th className="font-medium">c (Å)</th>}
        <th className="font-medium">a − certified</th>{hex && <th className="font-medium">c − certified</th>}
        <th className="font-medium">Rwp</th><th className="font-medium">size</th><th className="font-medium">microstrain</th><th className="font-medium">verdict</th>
      </tr></thead>
      <tbody className="font-mono">
        {cert.a_A != null && <tr className="border-b border-line text-muted"><td className="py-1.5 font-sans">Certified</td>
          <td>{f(cert.a_A)} ± {cert.a_uncertainty_A}</td>{hex && <td>{f(cert.c_A)}</td>}<td colSpan={hex ? 6 : 5} className="font-sans text-[11px]">{cert.source}</td></tr>}
        {d.runs.map((r) => (
          <tr key={r.id} className="border-b border-line align-top">
            <td className="py-1.5 font-sans"><span className="font-medium" style={{ color: ENGINE_COLOR[r.engine] }}>{r.label}</span>
              <div className="text-[10.5px] text-muted">{r.id}</div></td>
            <td>{f(v(r, "a_refined"))}{r.metrics.a_refined?.uncertainty ? <div className="text-[10.5px] text-muted">± {f(r.metrics.a_refined.uncertainty)}</div> : null}</td>
            {hex && <td>{f(v(r, "c_refined"))}</td>}
            <td className={cn(Math.abs(v(r, "difference_from_certified") ?? 0) > 0.0005 && "text-bad")}>{f(v(r, "difference_from_certified"))}</td>
            {hex && <td>{f(v(r, "c_difference_from_certified"))}</td>}
            <td>{v(r, "Rwp") != null ? `${f(v(r, "Rwp"), 1)} %` : "—"}</td>
            <td>{v(r, "crystallite_size") != null ? `${f(v(r, "crystallite_size"), 2)} µm` : "—"}</td>
            <td>{v(r, "microstrain") != null ? f(v(r, "microstrain"), 5) : "—"}</td>
            <td className="font-sans">{r.story.classification ? <Tag tone={r.story.classification === "agreement" ? "ok" : "warn"}>
              {r.story.classification.replaceAll("_", " ")}</Tag> : <Status status={r.status} />}
              {r.error && <div className="max-w-56 text-[10.5px] text-bad">{r.error.split("\n")[0]}</div>}</td>
          </tr>))}
      </tbody>
    </table>
  );
}

function OverviewPane({ d }: { d: GroupView }) {
  return (
    <div className="h-full overflow-auto">
      <OverlayChart d={d} />
      <div className="px-4 pb-4"><ResultsTable d={d} />
        <p className="mt-2 text-[11px] text-muted">“{d.prompt}” · reference structure {d.reference}. Red difference: outside the ±0.0005 Å target.
          Rwp measures how well the whole calculated pattern matches the scan (lower is closer).</p></div>
    </div>
  );
}

// --- reasoning: each run's steps as a flow, notes assigned to the step they belong to ------------------

function phaseOf(agent: string, seenEngine: boolean): "plan" | "before" | "steps" | "after" | "report" {
  if (agent === "planner" || agent === "orchestrator" && !seenEngine) return "plan";
  if (agent === "reasoning" || agent === "inputs") return seenEngine ? "after" : "before";
  if (agent === "rules") return "after";
  if (["analyst", "claim_checker", "orchestrator", "retrieval"].includes(agent)) return "report";
  return "steps";
}

function ReasoningFlow({ r }: { r: GroupRun }) {
  const s = r.story;
  const agents = r.engine === "agents";
  const notes: Record<string, { time: string; agent: string; note: string }[]> = { plan: [], before: [], steps: [], after: [], report: [] };
  let seen = false;
  for (const l of s.log) {
    if (l.agent === r.engine) seen = true;
    notes[phaseOf(l.agent, seen)].push(l);
  }
  const list = (xs: { time: string; agent: string; note: string }[]) => xs.length > 0 && (
    <ol className="space-y-1">{xs.map((l, k) => <li key={k} className="flex gap-2"><span className="shrink-0 font-mono text-[10.5px] leading-5 text-faint">{l.time}</span>
      <span>{l.note}</span></li>)}</ol>);
  const res = s.result;
  return (
    <div>
      <Node actor="input" who="Storage" title="Measured scan and reference structure">
        <div className="font-mono text-[11.5px]">{s.datasets.join(" · ")}</div>
      </Node>
      <Node actor={agents ? "llm" : "code"} who={agents ? "Planner · Claude" : "fixed recipe · code"} title={s.plan_title ?? "Plan"}>
        {s.plan_summary && <div>{s.plan_summary}</div>}{list(notes.plan)}
      </Node>
      {notes.before.length > 0 && <Node actor="code" who="decisions before fitting · code" title="What the data says, and what follows from it">{list(notes.before)}</Node>}
      {s.steps.map((st) => {
        const refine = st.name.startsWith("refine");
        const mine = agents ? notes.steps.filter((l) => l.note.includes(`step ${st.idx}`)) : refine ? notes.steps : [];
        return (
          <Node key={st.idx} actor={agents ? "llm" : refine ? "program" : "code"} status={st.status}
            who={agents ? "Coder · Claude → sandbox" : refine ? r.label : "code"} title={`${st.idx}. ${st.name.replaceAll("_", " ")}`}>
            {st.goal && <div className="text-muted">{st.goal}</div>}
            {st.attempts > 1 && <Tag tone="warn">{st.attempts} attempts: the code failed and was rewritten</Tag>}
            {list(mine)}
            {st.error && <div className="line-clamp-3 font-mono text-[11px] text-bad">{st.error}</div>}
          </Node>);
      })}
      <Node actor="result" who="checker · code" title="Result against the certificate">
        {res.a_refined ? <div className="font-mono text-[12px]">a = {f(res.a_refined.value)} Å{res.difference_from_certified && <> · Δ {f(res.difference_from_certified.value)} Å</>}
          {res.c_refined && <><br />c = {f(res.c_refined.value)} Å{res.c_difference_from_certified && <> · Δ {f(res.c_difference_from_certified.value)} Å</>}</>}</div>
          : <div className="text-muted">{s.error ? s.error.split("\n")[0] : "pending"}</div>}
        {list(notes.after)}
        {(s.warnings ?? []).map((w) => <div key={w} className="text-warn">{w}</div>)}
      </Node>
      <Node actor={notes.report.some((l) => l.agent === "analyst") ? "llm" : "code"} last
        who={notes.report.some((l) => l.agent === "analyst") ? "Analyst · Claude" : "report · code"} title="Report and number check">
        {s.claim ? <Tag tone={s.claim.passed ? "ok" : "bad"}>{s.claim.checked} numbers traced to files{s.claim.passed ? "" : " · some untraced"}</Tag>
          : <span className="text-muted">{live(s.status) ? "not written yet" : "—"}</span>}
        {list(notes.report)}
      </Node>
    </div>
  );
}

function ReasoningPane({ d }: { d: GroupView }) {
  return (
    <div className="h-full overflow-auto p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-3xl text-[12.5px] text-muted">How each tool reached its answer, in the order it happened: who acted, what was decided
          and why, what each stage changed, and how the result compares with the certificate. Read top to bottom.</p>
        <Legend />
      </div>
      <div className={cn("grid gap-4", d.runs.length === 2 ? "lg:grid-cols-2" : d.runs.length >= 3 ? "xl:grid-cols-3" : "")}>
        {d.runs.map((r) => (
          <section key={r.id} className="rounded-lg border border-line bg-surface">
            <header className="flex items-center gap-2 border-b border-line px-4 py-2.5">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: ENGINE_COLOR[r.engine] }} />
              <h2 className="text-[13px] font-semibold">{r.label}</h2><span className="font-mono text-[11px] text-muted">{r.id}</span>
              <span className="ml-auto"><Status status={r.status} /></span>
            </header>
            <div className="p-4"><ReasoningFlow r={r} /></div>
          </section>))}
      </div>
    </div>
  );
}

// --- compare: the same numbers drawn so the tools can be told apart at a glance -------------------------

function ComparePane({ d }: { d: GroupView }) {
  return (
    <div className="h-full overflow-auto">
      <div className="grid gap-4 p-4 xl:grid-cols-2">
        <Card title="Lattice parameter against the certificate" sub="dot: refined value; bar: its 1σ; shaded: certified ± k = 2; dashed: ±0.0005 Å target">
          <Deviation d={d} param="a" />{d.runs.some((r) => r.metrics.c_refined?.value != null) && <Deviation d={d} param="c" />}
        </Card>
        <Card title="How the fit improved, stage by stage" sub="Rwp after each refinement stage (lower is a closer fit of the whole pattern)">
          <Stages d={d} />
        </Card>
      </div>
      <Card title="Both fits on the scan" sub="zoom into a peak to see where each tool puts it" className="mx-4 mb-4"><OverlayChart d={d} height={300} /></Card>
      <div className="px-4 pb-4"><ResultsTable d={d} /></div>
    </div>
  );
}

function Card({ title, sub, children, className }: { title: string; sub: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-lg border border-line bg-surface", className)}>
      <header className="border-b border-line px-4 py-2"><h3 className="text-[12.5px] font-semibold">{title}</h3><p className="text-[11px] text-muted">{sub}</p></header>
      <div className="p-3">{children}</div>
    </section>
  );
}

function Deviation({ d, param }: { d: GroupView; param: "a" | "c" }) {
  const cert = param === "a" ? d.certified?.a_A : d.certified?.c_A;
  const cu = param === "a" ? d.certified?.a_uncertainty_A : d.certified?.c_uncertainty_A;
  const rows = d.runs.map((r) => ({ r, v: r.metrics[`${param}_refined`]?.value ?? null, u: r.metrics[`${param}_refined`]?.uncertainty ?? 0 }))
    .filter((x) => x.v != null) as { r: GroupRun; v: number; u: number }[];
  if (!rows.length) return <p className="text-[12px] text-muted">No refined {param} yet.</p>;
  const ref = cert ?? rows[0].v;
  const devs = rows.map((x) => x.v - ref);
  const span = Math.max(0.0007, ...devs.map((v, i) => Math.abs(v) + rows[i].u), cu ?? 0) * 1.15;
  const W = 520, L = 90, R = 20, X = (v: number) => L + ((v + span) / (2 * span)) * (W - L - R);
  const H = 30 + rows.length * 30;
  return (
    <svg viewBox={`0 0 ${W} ${H + 24}`} className="w-full" role="img" aria-label={`${param} against the certificate`}>
      <text x={8} y={14} fontSize={11} fill="var(--color-ink-2, #3a4252)">{param} − {cert != null ? "certified" : "first tool"} (Å)</text>
      {cu != null && <rect x={X(-cu)} y={20} width={X(cu) - X(-cu)} height={H - 20} fill="#1f4fd1" opacity={0.1} />}
      {[-0.0005, 0.0005].map((t) => <line key={t} x1={X(t)} x2={X(t)} y1={20} y2={H} stroke="#9aa3b2" strokeDasharray="4 3" />)}
      <line x1={X(0)} x2={X(0)} y1={20} y2={H} stroke="#3a4252" />
      {rows.map((x, i) => { const y = 38 + i * 30, dv = x.v - ref; return (
        <g key={x.r.id}>
          <text x={8} y={y + 4} fontSize={11.5} fontWeight={600} fill={ENGINE_COLOR[x.r.engine]}>{x.r.label}</text>
          {x.u > 0 && <line x1={X(dv - x.u)} x2={X(dv + x.u)} y1={y} y2={y} stroke={ENGINE_COLOR[x.r.engine]} strokeWidth={2} />}
          <circle cx={X(dv)} cy={y} r={5} fill={ENGINE_COLOR[x.r.engine]}><title>{`${x.r.label}: ${x.v.toFixed(6)} Å (${dv >= 0 ? "+" : ""}${dv.toFixed(6)})`}</title></circle>
          <text x={Math.min(X(dv) + 8, W - 70)} y={y - 7} fontSize={10.5} fill="#5b6475" fontFamily="monospace">{dv >= 0 ? "+" : ""}{dv.toFixed(5)}</text>
        </g>); })}
      {[-span, -span / 2, 0, span / 2, span].map((t) => <text key={t} x={X(t)} y={H + 16} fontSize={10} textAnchor="middle" fill="#7a8394" fontFamily="monospace">{t >= 0 ? "+" : ""}{t.toFixed(4)}</text>)}
    </svg>
  );
}

function Stages({ d }: { d: GroupView }) {
  const runs = d.runs.filter((r) => r.story.stages?.length);
  if (!runs.length) return <p className="text-[12px] text-muted">The agents' runs have no refinement stages; GSAS-II and MAUD do.</p>;
  const n = Math.max(...runs.map((r) => r.story.stages!.length));
  const top = Math.max(...runs.flatMap((r) => r.story.stages!.map((s) => s.Rwp_percent))) * 1.1;
  const W = 560, H = 200, L = 95, Rm = 70, B = 40, X = (i: number) => L + (i / Math.max(1, n - 1)) * (W - L - Rm), Y = (v: number) => 18 + (1 - v / top) * (H - B - 18);
  return (
    <svg viewBox={`0 0 ${W} ${H + 30}`} className="w-full" role="img" aria-label="Rwp by refinement stage">
      {[0, top / 2, top].map((t) => <g key={t}><line x1={L - 40} x2={W - Rm + 40} y1={Y(t)} y2={Y(t)} stroke="#eef0f3" />
        <text x={L - 46} y={Y(t) + 3} fontSize={10} textAnchor="end" fill="#7a8394">{t.toFixed(0)}%</text></g>)}
      {runs.map((r) => (
        <g key={r.id}>
          <polyline fill="none" stroke={ENGINE_COLOR[r.engine]} strokeWidth={2} points={r.story.stages!.map((s, i) => `${X(i)},${Y(s.Rwp_percent)}`).join(" ")} />
          {r.story.stages!.map((s, i) => <g key={i}><circle cx={X(i)} cy={Y(s.Rwp_percent)} r={4} fill={ENGINE_COLOR[r.engine]}><title>{`${r.label} · ${s.stage}: ${s.Rwp_percent.toFixed(1)} %`}</title></circle>
            <text x={X(i)} y={Y(s.Rwp_percent) - 8} fontSize={10} textAnchor="middle" fill={ENGINE_COLOR[r.engine]}>{s.Rwp_percent.toFixed(1)}</text></g>)}
        </g>))}
      {Array.from({ length: n }, (_, i) => (
        <text key={i} x={X(i)} y={H - B + 18} fontSize={10} textAnchor="middle" fill="#5b6475">
          {runs.map((r) => r.story.stages![i]?.stage).filter(Boolean).filter((v, j, a) => a.indexOf(v) === j).map((stage, j) => (
            <tspan key={j} x={X(i)} dy={j ? 12 : 0}>{stage}</tspan>))}</text>))}
    </svg>
  );
}

// --- per-run files: the existing plot, data and report panes, with a tool switcher --------------------

function PerRun({ d, render }: { d: GroupView; render: (r: Awaited<ReturnType<typeof api.run>>) => ReactNode }) {
  const [sel, setSel] = useState(d.runs[0]?.id);
  const run = useQuery({ queryKey: ["run", sel], queryFn: () => api.run(sel!), enabled: !!sel });
  return (
    <div className="flex h-full flex-col">
      {d.runs.length > 1 && <div className="flex gap-1 border-b border-line bg-subtle/60 px-3 py-1.5">
        {d.runs.map((r) => <button key={r.id} onClick={() => setSel(r.id)} className={cn("rounded px-2 py-0.5 text-[11.5px]",
          sel === r.id ? "font-medium text-white" : "text-muted hover:bg-subtle")} style={sel === r.id ? { background: ENGINE_COLOR[r.engine] } : undefined}>{r.label}</button>)}
      </div>}
      <div className="min-h-0 flex-1">{run.data ? render(run.data) : <Empty title="Loading…" />}</div>
    </div>
  );
}
