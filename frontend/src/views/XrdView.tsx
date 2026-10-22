import { useQuery } from "@tanstack/react-query";
import { Bot, BrainCircuit, ChevronRight, Columns3, FileText, LayoutDashboard, LineChart, Table2, X } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { api, type GroupRun, type GroupView } from "../api/client";
import { ClaimBadge } from "../components/ClaimBadge";
import { Legend, Node } from "../components/Flow";
import { LiveReasoning, LiveStatus } from "../components/LiveReasoning";
import { friendlyError, radiationLabel, runTitle, verdict } from "../components/labels";
import { useDetailed } from "../components/prefs";
import { Dot, Sections } from "../components/Sections";
import { Button, Empty, Status, Tag, type Tone, clock, cn, duration } from "../components/ui";
import { XrdChart, type Curve, type Overlay } from "../components/XrdChart";
import { useLiveFeed } from "../useLiveFeed";
import { DataPane, PlotsPane, ReportPane } from "./Panes";

export const ENGINE_COLOR: Record<string, string> = { agents: "#121826", gsas2: "#c2410c", maud: "#15803d" };
const f = (v: number | null | undefined, d = 6) => (v == null ? "—" : v.toFixed(d));
const live = (s: string) => ["queued", "planning", "running", "analysing", "retrying"].includes(s);

// --- right: one analysis (one run, or a group of runs on the same scan) ------------------------

export function AnalysisWorkspace({ id, tab, onClose, onAsk }: { id: string; tab?: string; onClose: () => void; onAsk: (q: string) => void }) {
  const detailed = useDetailed();
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
  const title = run.data ? runTitle({ title: run.data.plan?.title, prompt: run.data.prompt }) : d.material ?? "";
  const first = d.runs[0];
  const sections = [
    { key: "overview", label: "Overview", icon: LayoutDashboard, badge: anyLive ? <Dot tone="run" /> : undefined, body: <OverviewPane d={d} /> },
    { key: "reasoning", label: "Reasoning", icon: BrainCircuit, body: <ReasoningPane d={d} />,
      badge: failed ? <Dot tone="bad" /> : undefined },
    ...(d.runs.length > 1 ? [{ key: "compare", label: "Compare tools", icon: Columns3, body: <ComparePane d={d} /> }] : []),
    { key: "plots", label: "Plots", icon: LineChart, body: <PerRun d={d} render={(r) => <PlotsPane run={r} />} /> },
    { key: "data", label: "Values", icon: Table2, body: <PerRun d={d} render={(r) => <DataPane run={r} />} /> },
    { key: "report", label: "Report", icon: FileText, body: <PerRun d={d} render={(r) => <ReportPane run={r} />} /> },
  ];
  const header = (
      <div className="border-b border-line bg-surface">
        <div className="flex items-start gap-3 px-5 pt-3">
          <div className="min-w-0 flex-1">
            <h1 className="text-[15px] font-semibold leading-6">{title}</h1>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted">
              {anyLive ? <Status status="running" /> : failed ? <Tag tone="bad">{failed} of {d.runs.length} failed</Tag> : <Status status="done" />}
              {run.data && <span>{clock(run.data.started_at)} · took {duration(run.data.started_at, run.data.finished_at)}</span>}
              <span>{d.material} · {d.dataset}</span>
              <span>{d.runs.length > 1 ? "Tools" : "Tool"}: {d.runs.map((r) => r.label).join(", ")}</span>
              {detailed && <span className="font-mono">{d.runs.map((r) => r.id).join(", ")}</span>}
            </div>
            {first && d.prompt && d.prompt.trim() !== title && <p className="mt-1 line-clamp-1 text-[12.5px] text-ink-2" title={d.prompt}>Question: “{d.prompt}”</p>}
          </div>
          <Button size="sm" variant="secondary" onClick={() => onAsk(failed ? "Why did this analysis fail?" : "Explain this result in plain words.")}>
            <Bot size={13} /> Ask about this {failed && failed === d.runs.length ? "failure" : "result"}</Button>
          <button onClick={onClose} title="Close and go back" aria-label="Close"
            className="rounded p-1 text-muted hover:bg-subtle hover:text-ink"><X size={15} /></button>
        </div>
        <div className="mx-5 mt-3 space-y-2">{d.runs.map((r) => <Verdict key={r.id} id={r.id} label={d.runs.length > 1 ? r.label : null}
          compact={d.runs.length > 1} />)}</div>
        <div className="mt-3 grid grid-cols-4 border-t border-line">
          <Cellv label="Measured scan" value={d.measured?.file ?? "—"} small />
          <Cellv label="Wavelength" value={`${d.instrument?.wavelength_A ?? "—"} Å`} sub={`${[radiationLabel(d.instrument?.radiation), d.instrument?.radiation_source].filter(Boolean).join(", ")}${d.instrument?.ka2_present ? " · Kα1 + Kα2" : ""}`} mono />
          <Cellv label="Certified" value={cert.a_A != null ? `a ${f(cert.a_A)} Å` : "none on file"} sub={cert.c_A != null ? `c ${f(cert.c_A)} Å` : cert.a_uncertainty_A ? `± ${cert.a_uncertainty_A} Å (k = 2)` : undefined} mono />
          <div className="border-l border-line px-5 py-2.5">
            <div className="text-[11px] text-muted">Refined a</div>
            {d.runs.map((r) => <div key={r.id} className="flex items-center gap-2 font-mono text-[12.5px]">
              <span className="w-14 font-sans text-[11px] font-medium" style={{ color: ENGINE_COLOR[r.engine] }}>{r.label}</span>
              {r.metrics.a_refined?.value != null ? f(r.metrics.a_refined.value) : <Status status={r.status} />}</div>)}
          </div>
        </div>
      </div>
  );
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Sections key={id} initial={tab ?? (anyLive ? "reasoning" : undefined)} sections={sections} header={header} />
    </div>
  );
}

const BANNER: Record<Tone, string> = {
  ok: "border-ok/25 bg-ok-soft", warn: "border-warn/25 bg-warn-soft", bad: "border-bad/25 bg-bad-soft",
  run: "border-accent/25 bg-accent-soft", neutral: "border-line bg-subtle",
};

/** The plain-language answer of one tool's run, built from its own metrics; technical detail folds away. */
/** compact (several tools side by side): one line per tool, opened for the explanation and the number check. */
function Verdict({ id, label, compact = false }: { id: string; label: string | null; compact?: boolean }) {
  const run = useQuery({ queryKey: ["run", id], queryFn: () => api.run(id) });
  const [tech, setTech] = useState(false);
  const [open, setOpen] = useState(!compact);
  const feed = useLiveFeed(run.data && live(run.data.status) ? id : null);
  if (!run.data) return null;
  if (live(run.data.status)) {
    return (
      <div className={cn("rounded-lg border px-4 py-2.5", BANNER.run)}>
        {label && <p className="mb-1 text-[11.5px] font-medium text-muted">{label}</p>}
        <LiveStatus feed={feed} startedAt={run.data.started_at} />
        <p className="mt-1 text-[12px] text-ink-2">The answer appears here when the analysis finishes. Follow each step live under Reasoning.</p>
      </div>
    );
  }
  const v = verdict(run.data);
  return (
    <div className={cn("rounded-lg border px-4", open ? "py-2.5" : "py-1.5", BANNER[v.tone])}>
      <button onClick={() => setOpen((o) => !o)} disabled={!compact} aria-expanded={open}
        className="flex w-full items-start gap-1.5 text-left disabled:cursor-default">
        {compact && <ChevronRight size={14} className={cn("mt-[5px] shrink-0 text-muted transition", open && "rotate-90")} />}
        <span className={cn("min-w-0 flex-1 text-[13.5px] font-semibold leading-6 text-ink", !open && "truncate")}>
          {label && <span className="mr-1.5 text-muted">{label}:</span>}{v.headline}</span>
      </button>
      {open && <>
      {v.details.map((t) => <p key={t} className="mt-0.5 text-[12.5px] leading-5 text-ink-2">{t}</p>)}
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <ClaimBadge c={run.data.claim_check} />
        {run.data.status === "failed" && run.data.error && <button onClick={() => setTech((x) => !x)} className="text-[11.5px] text-accent hover:underline">
          {tech ? "Hide" : "Show"} technical details</button>}
      </div>
      {tech && <pre className="mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap rounded border border-line bg-surface p-2 font-mono text-[11px] text-ink-2">{run.data.error}</pre>}
      </>}
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
  const detailed = useDetailed();
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
              {detailed && <div className="text-[10.5px] text-muted">{r.id}</div>}</td>
            <td>{f(v(r, "a_refined"))}{r.metrics.a_refined?.uncertainty ? <div className="text-[10.5px] text-muted">± {f(r.metrics.a_refined.uncertainty)}</div> : null}</td>
            {hex && <td>{f(v(r, "c_refined"))}</td>}
            <td className={cn(Math.abs(v(r, "difference_from_certified") ?? 0) > 0.0005 && "text-bad")}>{f(v(r, "difference_from_certified"))}</td>
            {hex && <td>{f(v(r, "c_difference_from_certified"))}</td>}
            <td>{v(r, "Rwp") != null ? `${f(v(r, "Rwp"), 1)} %` : "—"}</td>
            <td>{v(r, "crystallite_size") != null ? `${f(v(r, "crystallite_size"), 2)} µm` : "—"}</td>
            <td>{v(r, "microstrain") != null ? f(v(r, "microstrain"), 5) : "—"}</td>
            <td className="font-sans">{r.story.classification ? <Tag tone={r.story.classification === "agreement" ? "ok" : "warn"}>
              {r.story.classification.replaceAll("_", " ")}</Tag> : <Status status={r.status} />}
              {r.error && <div className="max-w-56 text-[10.5px] text-bad">{detailed ? r.error.split("\n")[0] : friendlyError(r.error).title}</div>}</td>
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
  const detailed = useDetailed();
  return (
    <div className="h-full overflow-auto p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-3xl text-[12.5px] text-muted">How each tool reached its answer, in the order it happened: who acted, what was decided
          and why, what each stage changed, and how the result compares with the certificate. Read top to bottom.</p>
        <Legend />
      </div>
      <div className={cn("grid gap-4", d.runs.length === 2 ? "lg:grid-cols-2" : d.runs.length >= 3 ? "xl:grid-cols-3" : "")}>
        {d.runs.map((r) => (
          <section key={r.id} className="min-w-0 rounded-lg border border-line bg-surface">
            <header className="flex items-center gap-2 border-b border-line px-4 py-2.5">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: ENGINE_COLOR[r.engine] }} />
              <h2 className="text-[13px] font-semibold">{r.label}</h2>{detailed && <span className="font-mono text-[11px] text-muted">{r.id}</span>}
              <span className="ml-auto"><Status status={r.status} /></span>
            </header>
            <RunReasoning r={r} />
          </section>))}
      </div>
    </div>
  );
}

/** While a run is going (and afterwards, as long as the server still holds its events) it is told live; otherwise
 *  from its records. */
function RunReasoning({ r }: { r: GroupRun }) {
  const feed = useLiveFeed(r.id);
  const [record, setRecord] = useState(false);
  const running = live(r.status);
  if (!running && (record || !feed.items.length)) {
    return <div className="p-4">
      {feed.items.length > 0 && <button onClick={() => setRecord(false)} className="mb-3 text-[11.5px] text-accent hover:underline">Show the timeline</button>}
      <ReasoningFlow r={r} />
    </div>;
  }
  return (
    <div className="flex h-[min(72vh,680px)] flex-col">
      <div className="min-h-0 flex-1"><LiveReasoning feed={feed} /></div>
      {!running && <button onClick={() => setRecord(true)} className="border-t border-line px-4 py-2 text-left text-[11.5px] text-accent hover:underline">
        Show the full record (every decision and the result)</button>}
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
