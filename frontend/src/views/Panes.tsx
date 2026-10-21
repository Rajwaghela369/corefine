import { useQuery } from "@tanstack/react-query";
import { Background, Handle, type Node, type NodeProps, Position, ReactFlow } from "@xyflow/react";
import { Download, ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import { type Overlay, XrdChart } from "../components/XrdChart";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, xrd, type RunDetail, type Step } from "../api/client";
import { Dialog, Empty, Status, Tag, cn, num } from "../components/ui";
import { ClaimBadge } from "../panels/ChatPanel";

const latest = (run: RunDetail, ext: string) => {
  // per-step copies live in outputs/step_NN/; show the latest copy of each file name
  const byName = new Map<string, string>();
  run.artifacts.filter((a) => a.path.startsWith("outputs/") && a.path.endsWith(ext))
    .forEach((a) => byName.set(a.path.split("/").pop()!, a.path));
  return [...byName.values()];
};

// --- Plan ----------------------------------------------------------------

type StepData = { idx: number; name: string; goal: string; status: Step["status"]; attempts: number };
const STRIPE: Record<string, string> = { pending: "#cfd4dc", running: "#1f4fd1", retrying: "#a35b00", done: "#17803d", failed: "#b42318" };

function StepNode({ data }: NodeProps<Node<StepData>>) {
  return (
    <div className="w-[248px] cursor-pointer overflow-hidden rounded-md border border-line bg-surface shadow-[0_1px_2px_rgba(16,24,40,.06)] hover:border-line-strong">
      <Handle type="target" position={Position.Top} />
      <div className="flex">
        <div className="w-1 shrink-0" style={{ background: STRIPE[data.status] }} />
        <div className="min-w-0 flex-1 px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate font-mono text-[11.5px] font-medium"><span className="text-faint">{String(data.idx).padStart(2, "0")}</span> {data.name}</span>
            <Status status={data.status} />
          </div>
          <p className="mt-0.5 line-clamp-1 text-[11px] text-muted" title={data.goal}>{data.goal}</p>
          {data.attempts > 1 && <p className="mt-0.5 text-[10.5px] text-warn">Recovered on attempt {data.attempts}</p>}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
const nodeTypes = { step: StepNode };

export function PlanPane({ run, logOpen, onLogClose }: { run: RunDetail; logOpen: boolean; onLogClose: () => void }) {
  const [sel, setSel] = useState<number | null>(null);
  const steps = run.plan?.steps ?? [];
  const status = new Map(run.steps.map((s) => [s.idx, s]));
  const { nodes, edges } = useMemo(() => ({
    nodes: steps.map((s, i): Node<StepData> => {
      const st = status.get(s.idx);
      return { id: String(s.idx), type: "step", position: { x: 0, y: i * 92 }, draggable: false,
        data: { idx: s.idx, name: s.name, goal: s.goal, status: st?.status ?? "pending", attempts: st?.attempts ?? 0 } };
    }),
    edges: steps.slice(1).map((s, i) => ({ id: `e${i}`, source: String(steps[i].idx), target: String(s.idx) })),
  }), [run]);

  if (!run.plan) return run.status === "failed"
    ? <Empty title="The run failed before a plan was made">{run.error}</Empty>
    : <Empty title="Planning…">The planner is reading the request and the selected manifests.</Empty>;
  const step = steps.find((s) => s.idx === sel);
  const st = sel != null ? status.get(sel) : undefined;
  return (
    <div className="flex h-full flex-col">
      <p className="border-b border-line px-3 py-2 text-xs text-ink-2"><span className="font-medium text-ink">{run.plan.title}.</span> {run.plan.summary}</p>
      <div className="min-h-0 flex-1">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ maxZoom: 1, padding: 0.25 }}
          nodesConnectable={false} onNodeClick={(_, n) => setSel(Number(n.id))} proOptions={{ hideAttribution: true }}>
          <Background gap={18} size={1} color="#e2e5ea" />
        </ReactFlow>
      </div>
      <Dialog title={step ? `Step ${step.idx} · ${step.name}` : ""} open={!!step} onClose={() => setSel(null)} wide>
        {step && <StepDetail runId={run.id} goal={step.goal} outputs={step.outputs} skill={step.skill} st={st} />}
      </Dialog>
      <Dialog title="Experiment log" open={logOpen} onClose={onLogClose} wide>
        <FileText runId={run.id} path="experiment_log.md" markdown />
      </Dialog>
    </div>
  );
}

function StepDetail({ runId, goal, outputs, skill, st }: { runId: string; goal: string; outputs: string[]; skill: string; st?: Step }) {
  const files = [
    st?.code_key && { label: "Code", path: st.code_key },
    st?.stdout_key && { label: "stdout", path: st.stdout_key },
    st?.stdout_key && { label: "stderr", path: st.stdout_key.replace(/\.stdout$/, ".stderr") },
  ].filter(Boolean) as { label: string; path: string }[];
  const [tab, setTab] = useState(0);
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">{st && <Status status={st.status} />}
        {st && st.attempts > 1 && <Tag tone="warn">{st.attempts} attempts</Tag>}<span className="text-xs text-muted">skill: {skill}</span></div>
      <p className="text-[13px] text-ink-2">{goal}</p>
      <p className="text-xs text-muted">Declared outputs: <span className="font-mono">{outputs.join(", ")}</span></p>
      {st?.error && <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-md border border-bad/20 bg-bad-soft p-2.5 font-mono text-[11px] text-bad">{st.error}</pre>}
      {files.length > 0 && <>
        <div className="flex gap-1 border-b border-line">
          {files.map((f, i) => <button key={f.label} onClick={() => setTab(i)}
            className={cn("-mb-px border-b-2 px-2.5 py-1.5 text-xs", tab === i ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink")}>{f.label}</button>)}
          <span className="ml-auto self-center font-mono text-[10.5px] text-faint">{files[tab]?.path}</span>
        </div>
        <FileText runId={runId} path={files[tab].path} />
      </>}
    </div>
  );
}

function FileText({ runId, path, markdown }: { runId: string; path: string; markdown?: boolean }) {
  const q = useQuery({ queryKey: ["file", runId, path], queryFn: () => api.artifactText(runId, path) });
  if (markdown) return <div className="doc max-h-[60vh] overflow-auto"><Markdown remarkPlugins={[remarkGfm]}>{q.data ?? ""}</Markdown></div>;
  return <pre className="max-h-[55vh] overflow-auto rounded-md border border-line bg-subtle p-3 font-mono text-[11px] leading-4">{q.data || "(empty)"}</pre>;
}

// --- Plots ---------------------------------------------------------------

export function PlotsPane({ run }: { run: RunDetail }) {
  const pngs = latest(run, ".png");
  const [i, setI] = useState(0);
  const all = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const measuredId = run.dataset_ids.find((id) => all.data?.find((d) => d.id === id)?.role === "measured_pattern");
  const peaksPath = latest(run, ".csv").find((p) => p.endsWith("peaks.csv"));
  if (!pngs.length && !measuredId) return <Empty title="No plots yet">Plots appear when a step writes a PNG to its outputs.</Empty>;
  const path = pngs[Math.min(i, pngs.length - 1)];
  const art = run.artifacts.find((a) => a.path === path);
  return (
    <div className="flex h-full flex-col overflow-auto">
      {measuredId && <InteractiveRunPlot runId={run.id} datasetId={measuredId} peaksPath={peaksPath} />}
      {path && <>
        <div className="flex items-center justify-center bg-surface p-2">
          <img src={api.artifactUrl(run.id, path)} alt={path} className="max-h-[420px] max-w-full object-contain" />
        </div>
        <div className="flex items-center gap-2 border-t border-line px-3 py-1.5">
          {pngs.length > 1 && pngs.map((p, k) => <button key={p} onClick={() => setI(k)}
            className={cn("rounded px-1.5 py-0.5 font-mono text-[11px]", k === i ? "bg-accent-soft text-accent" : "text-muted hover:text-ink")}>{p.split("/").pop()}</button>)}
          <span className="font-mono text-[10.5px] text-faint">{path} (the step's own figure) · sha256 {art?.sha256.slice(0, 10)}</span>
          <a href={api.artifactUrl(run.id, path)} target="_blank" rel="noreferrer" className="ml-auto text-muted hover:text-accent" title="Open full size"><ExternalLink size={13} /></a>
        </div>
      </>}
    </div>
  );
}

/** The measured scan with the run's fitted peak centres (from its peaks.csv) as labelled sticks; zoomable. */
function InteractiveRunPlot({ runId, datasetId, peaksPath }: { runId: string; datasetId: string; peaksPath?: string }) {
  const m = useQuery({ queryKey: ["xrd-measured", datasetId, undefined], queryFn: () => xrd.measured(datasetId) });
  const csv = useQuery({ queryKey: ["file", runId, peaksPath], queryFn: () => api.artifactText(runId, peaksPath!), enabled: !!peaksPath });
  const overlays: Overlay[] = useMemo(() => {
    if (!csv.data) return [];
    const [head, ...rows] = csv.data.trim().split("\n").map((l) => l.split(","));
    const col = (n: string) => head.indexOf(n);
    const tt = col("two_theta_fit") >= 0 ? col("two_theta_fit") : col("two_theta_obs");
    if (tt < 0) return [];
    const peaks = rows.map((r) => ({ two_theta: Number(r[tt]), intensity: 60, d_A: 0, multiplicity: 1,
      hkl: col("h") >= 0 ? `${r[col("h")]} ${r[col("k")]} ${r[col("l")]}` : "" }));
    return [{ label: "fitted peaks (this run)", color: "#c2410c", peaks }];
  }, [csv.data]);
  if (!m.data) return <p className="p-3 text-xs text-muted">Loading the measured scan…</p>;
  return (
    <div className="border-b border-line px-2 pt-2">
      <XrdChart x={m.data.x} y={m.data.y} overlays={overlays} log height={260} />
      <p className="px-1 pb-1 text-[10.5px] text-faint">{datasetId}/{m.data.file} with this run's fitted peak positions. Drag to zoom, double-click to reset;
        the XRD inspector in Storage compares any model structure.</p>
    </div>
  );
}

// --- Data ----------------------------------------------------------------

export function DataPane({ run }: { run: RunDetail }) {
  const csvs = latest(run, ".csv");
  const [view, setView] = useState<"metrics" | string>("metrics");
  if (!run.metrics.length && !csvs.length) return <Empty title="No data yet">Metrics appear as each step's metrics.json is accepted.</Empty>;
  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-1 border-b border-line px-2">
        {["metrics", ...csvs].map((v) => <button key={v} onClick={() => setView(v)}
          className={cn("-mb-px border-b-2 px-2 py-1.5 text-[11.5px]", view === v ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink")}>
          {v === "metrics" ? `Metrics (${run.metrics.length})` : v.split("/").pop()}</button>)}
        {view !== "metrics" && <a href={api.artifactUrl(run.id, view)} download className="ml-auto self-center p-1 text-muted hover:text-accent" title="Download"><Download size={13} /></a>}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {view === "metrics" ? <MetricsTable run={run} /> : <Csv runId={run.id} path={view} />}
      </div>
    </div>
  );
}

function MetricsTable({ run }: { run: RunDetail }) {
  return (
    <table className="tabular w-full text-[12px]">
      <thead className="sticky top-0 bg-subtle text-left text-[11px] text-muted">
        <tr><th className="px-3 py-1.5 font-medium">Quantity</th><th className="px-2 font-medium">Value</th>
          <th className="px-2 font-medium">± 1σ</th><th className="px-2 font-medium">Unit</th><th className="px-2 font-medium">Source file</th></tr>
      </thead>
      <tbody className="divide-y divide-line">
        {run.metrics.map((m, i) => (
          <tr key={i} title={m.method ?? ""} className="hover:bg-subtle/60">
            <td className="px-3 py-1.5 font-mono text-[11.5px]">{m.name}</td>
            <td className="px-2 text-right font-mono text-[11.5px]">{num(m.value, 10)}</td>
            <td className="px-2 text-right font-mono text-[11.5px] text-muted">{num(m.uncertainty, 4)}</td>
            <td className="px-2 text-ink-2">{m.unit === "angstrom" ? "Å" : m.unit === "degree" ? "°" : m.unit ?? ""}</td>
            <td className="px-2 font-mono text-[10.5px] text-faint">{m.source.replace(/^outputs\//, "")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Csv({ runId, path }: { runId: string; path: string }) {
  const q = useQuery({ queryKey: ["file", runId, path], queryFn: () => api.artifactText(runId, path) });
  const rows = (q.data ?? "").trim().split("\n").filter(Boolean).map((l) => l.split(","));
  const [head, ...body] = rows;
  return (
    <table className="tabular w-full text-[11px]">
      <thead className="sticky top-0 bg-subtle text-left text-muted">
        <tr>{head?.map((h) => <th key={h} className="whitespace-nowrap px-2.5 py-1.5 font-medium">{h}</th>)}</tr>
      </thead>
      <tbody className="divide-y divide-line">
        {body.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="whitespace-nowrap px-2.5 py-1 text-right font-mono">{num(c, 7)}</td>)}</tr>)}
      </tbody>
    </table>
  );
}

// --- Report --------------------------------------------------------------

export function ReportPane({ run }: { run: RunDetail }) {
  const has = run.artifacts.some((a) => a.path === "report.md");
  const q = useQuery({ queryKey: ["file", run.id, "report.md", run.status], queryFn: () => api.artifactText(run.id, "report.md"), enabled: has });
  if (!has) return run.status === "failed"
    ? <Empty title="No report">The run failed: {run.error?.split("\n")[0]}</Empty>
    : <Empty title="Report pending">The analyst writes the report after the last step completes.</Empty>;
  return (
    <div className="h-full overflow-auto px-5 py-4">
      <div className="mb-3 flex items-center gap-2"><ClaimBadge c={run.claim_check} /></div>
      <article className="doc"><Markdown remarkPlugins={[remarkGfm]}>{q.data ?? ""}</Markdown></article>
    </div>
  );
}
