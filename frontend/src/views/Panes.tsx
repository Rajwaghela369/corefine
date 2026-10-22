import { useQuery } from "@tanstack/react-query";
import { Download, ExternalLink } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, xrd, type Metric, type RunDetail } from "../api/client";
import { ClaimBadge } from "../components/ClaimBadge";
import { formatUncertainty, formatValue, friendlyError, isKeyMetric, metricHelp, metricLabel, unitLabel } from "../components/labels";
import { useDetailed } from "../components/prefs";
import { type Overlay, XrdChart } from "../components/XrdChart";
import { Button, Empty, cn, num } from "../components/ui";

const latest = (run: RunDetail, ext: string) => {
  // per-step copies live in outputs/step_NN/; show the latest copy of each file name
  const byName = new Map<string, string>();
  run.artifacts.filter((a) => a.path.startsWith("outputs/") && a.path.endsWith(ext))
    .forEach((a) => byName.set(a.path.split("/").pop()!, a.path));
  return [...byName.values()];
};

const pretty = (name: string) => name.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());

// --- Plots -----------------------------------------------------------------

export function PlotsPane({ run }: { run: RunDetail }) {
  const detailed = useDetailed();
  const pngs = latest(run, ".png");
  const [i, setI] = useState(0);
  const all = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const measuredId = run.dataset_ids.find((id) => all.data?.find((d) => d.id === id)?.role === "measured_pattern");
  const peaksPath = latest(run, ".csv").find((p) => p.endsWith("peaks.csv"));
  if (!pngs.length && !measuredId) return <Empty title="No plots yet">Plots appear when a step saves a figure.</Empty>;
  const path = pngs[Math.min(i, pngs.length - 1)];
  const art = run.artifacts.find((a) => a.path === path);
  return (
    <div className="flex h-full flex-col overflow-auto">
      {measuredId && <InteractiveRunPlot runId={run.id} datasetId={measuredId} peaksPath={peaksPath} />}
      {path && <>
        <p className="px-4 pt-3 text-[12px] text-muted">The figure the analysis drew itself: the fit (top) and the leftover differences (bottom).</p>
        <div className="flex items-center justify-center bg-surface p-2">
          <img src={api.artifactUrl(run.id, path)} alt="Figure produced by the analysis" className="max-h-[420px] max-w-full object-contain" />
        </div>
        <div className="flex items-center gap-2 border-t border-line px-3 py-1.5">
          {pngs.length > 1 && pngs.map((p, k) => <button key={p} onClick={() => setI(k)}
            className={cn("rounded px-1.5 py-0.5 font-mono text-[11px]", k === i ? "bg-accent-soft text-accent" : "text-muted hover:text-ink")}>{p.split("/").pop()}</button>)}
          {detailed && <span className="font-mono text-[10.5px] text-faint">{path} · sha256 {art?.sha256.slice(0, 10)}</span>}
          <a href={api.artifactUrl(run.id, path)} target="_blank" rel="noreferrer" className="ml-auto text-muted hover:text-accent" title="Open full size"><ExternalLink size={13} /></a>
        </div>
      </>}
    </div>
  );
}

/** The measured scan with the run's fitted peak centres (from its peaks.csv) as labelled ticks; zoomable. */
export function InteractiveRunPlot({ runId, datasetId, peaksPath }: { runId: string; datasetId: string; peaksPath?: string }) {
  const detailed = useDetailed();
  const m = useQuery({ queryKey: ["xrd-measured", datasetId, undefined], queryFn: () => xrd.measured(datasetId) });
  const csv = useQuery({ queryKey: ["file", runId, peaksPath], queryFn: () => api.artifactText(runId, peaksPath!), enabled: !!peaksPath });
  const [log, setLog] = useState(true);
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
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 pb-1 text-[11.5px] text-ink-2">
        <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[#1f4fd1]" /> Measured X-ray scan</span>
        {overlays.length > 0 && <span className="inline-flex items-center gap-1.5"><span className="h-3 w-0.5 bg-[#c2410c]" /> Peak positions found by this analysis (labels are Miller indices)</span>}
        <label className="ml-auto inline-flex items-center gap-1 text-muted"><input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} /> log scale</label>
      </div>
      <XrdChart x={m.data.x} y={m.data.y} overlays={overlays} log={log} height={260} />
      <p className="px-1 pb-1 text-[10.5px] text-faint">Drag across the plot to zoom in, double-click to zoom out.
        {detailed && <> Source: {datasetId}/{m.data.file}.</>}</p>
    </div>
  );
}

// --- Data ------------------------------------------------------------------

export function DataPane({ run }: { run: RunDetail }) {
  const detailed = useDetailed();
  const csvs = latest(run, ".csv");
  const [view, setView] = useState<"metrics" | string>("metrics");
  if (!run.metrics.length && !csvs.length) return <Empty title="No values yet">Values appear as each step finishes.</Empty>;
  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-1 border-b border-line px-2">
        {["metrics", ...csvs].map((v) => <button key={v} onClick={() => setView(v)}
          className={cn("-mb-px border-b-2 px-2 py-1.5 text-[11.5px]", view === v ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink")}>
          {v === "metrics" ? "Values" : `Table: ${v.split("/").pop()}`}</button>)}
        {view !== "metrics" && <a href={api.artifactUrl(run.id, view)} download className="ml-auto self-center p-1 text-muted hover:text-accent" title="Download"><Download size={13} /></a>}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {view === "metrics" ? <MetricsTable run={run} detailed={detailed} /> : <Csv runId={run.id} path={view} />}
      </div>
    </div>
  );
}

function groupOf(run: RunDetail, m: Metric): string {
  const s = m.source.match(/step_(\d+)/);
  if (s) {
    const step = run.plan?.steps.find((x) => x.idx === Number(s[1]));
    return step ? `Step ${step.idx}: ${pretty(step.name)}` : `Step ${Number(s[1])}`;
  }
  return m.source.includes("comparison") ? "Comparison with the certificate" : "Other";
}

function MetricsTable({ run, detailed }: { run: RunDetail; detailed: boolean }) {
  const [all, setAll] = useState(detailed);
  const showAll = detailed || all;
  // the same quantity is often reported by several steps; keep its first appearance unless every row was asked for
  const seen = new Set<string>();
  const rows = run.metrics.filter((m) => {
    if (detailed) return true;
    const k = `${m.name}=${m.value}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return showAll || isKeyMetric(m.name);
  });
  const groups = new Map<string, Metric[]>();
  rows.forEach((m) => { const g = groupOf(run, m); groups.set(g, [...(groups.get(g) ?? []), m]); });
  const hidden = run.metrics.length - rows.length;
  return (
    <div>
      {!detailed && <div className="flex items-center gap-2 border-b border-line px-4 py-2 text-[12px] text-muted">
        {all ? "Showing every value the analysis recorded." : "Showing the key values."}
        <Button size="sm" variant="ghost" onClick={() => setAll((v) => !v)}>{all ? "Key values only" : `Show all (${hidden} more)`}</Button>
      </div>}
      <table className="tabular w-full text-[12.5px]">
        <thead className="sticky top-0 bg-subtle text-left text-[11px] text-muted">
          <tr><th className="px-4 py-1.5 font-medium">Quantity</th><th className="px-2 text-right font-medium">Value</th>
            <th className="px-2 text-right font-medium">Uncertainty</th><th className="px-2 font-medium">Unit</th>
            {detailed && <th className="px-2 font-medium">Name · source file</th>}</tr>
        </thead>
        {[...groups.entries()].map(([g, ms]) => (
          <tbody key={g} className="divide-y divide-line">
            <tr className="bg-surface"><td colSpan={detailed ? 5 : 4} className="px-4 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wider text-faint">{g}</td></tr>
            {ms.map((m, i) => (
              <tr key={i} title={[metricHelp(m.name), m.method && `Method: ${m.method}`].filter(Boolean).join("\n")} className="hover:bg-subtle/60">
                <td className="px-4 py-1.5">{metricLabel(m.name)}</td>
                <td className="px-2 text-right font-mono text-[12px]">{detailed ? num(m.value, 10) : formatValue(m.value, m.uncertainty)}</td>
                <td className="px-2 text-right font-mono text-[12px] text-muted">{m.uncertainty ? `± ${detailed ? num(m.uncertainty, 4) : formatUncertainty(m.uncertainty)}` : ""}</td>
                <td className="px-2 text-ink-2">{unitLabel(m.unit)}</td>
                {detailed && <td className="px-2 font-mono text-[10.5px] text-faint">{m.name} · {m.source.replace(/^outputs\//, "")}</td>}
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
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

// --- Report ----------------------------------------------------------------

const TAG = /\s*\[([a-z][a-z0-9_]*)\](?!\()/gi;

export function ReportPane({ run }: { run: RunDetail }) {
  const detailed = useDetailed();
  const has = run.artifacts.some((a) => a.path === "report.md");
  const q = useQuery({ queryKey: ["file", run.id, "report.md", run.status], queryFn: () => api.artifactText(run.id, "report.md"), enabled: has });
  const names = useMemo(() => new Set(run.metrics.map((m) => m.name)), [run.metrics]);
  // the analyst cites the metric behind each number as [name]; show those as small chips, or hide them in the simple view
  const text = (q.data ?? "").replace(TAG, (all, name: string) => (names.has(name) ? (detailed ? ` [${name}](#metric:${name})` : "") : all));
  if (!has) return run.status === "failed"
    ? <Empty title="No report">{friendlyError(run.error).title}</Empty>
    : <Empty title="Report pending">The report is written after the last step finishes.</Empty>;
  return (
    <div className="h-full overflow-auto px-5 py-4">
      <div className="mb-3 flex items-center gap-2"><ClaimBadge c={run.claim_check} />
        {detailed && <span className="text-[11px] text-muted">Grey chips name the recorded value each number comes from.</span>}</div>
      <article className="doc"><Markdown remarkPlugins={[remarkGfm]} components={{
        a: ({ href, children }) => href?.startsWith("#metric:")
          ? <MetricChip run={run} name={href.slice(8)} />
          : <a href={href} target="_blank" rel="noreferrer" className="text-accent hover:underline">{children as ReactNode}</a>,
      }}>{text}</Markdown></article>
    </div>
  );
}

function MetricChip({ run, name }: { run: RunDetail; name: string }) {
  const m = run.metrics.find((x) => x.name === name);
  return <span title={m ? `${metricLabel(name)} = ${num(m.value, 10)} ${unitLabel(m.unit)}\nfrom ${m.source}` : name}
    className="ml-0.5 rounded bg-subtle px-1 align-[1px] font-mono text-[10px] text-faint">{name}</span>;
}
