import { useQuery } from "@tanstack/react-query";
import { Bot, Columns3, Database, FileClock, FileText, LayoutDashboard, LineChart, ListChecks, Table2, Workflow, X } from "lucide-react";
import { useState } from "react";
import { api, type RunDetail } from "../api/client";
import { ClaimBadge } from "../components/ClaimBadge";
import { CLASS, formatUncertainty, formatValue, metricLabel, runTitle, verdict } from "../components/labels";
import { useDetailed } from "../components/prefs";
import { Dot, Sections } from "../components/Sections";
import { Button, Empty, PanelHeader, Status, Tag, type Tone, clock, cn, duration, num } from "../components/ui";
import { Welcome, WelcomeSection } from "../components/Welcome";
import { NewAnalysis } from "../panels/NewAnalysis";
import { RunsList, useRuns } from "../panels/RunsList";
import { useRunEvents } from "../useRunEvents";
import { EngineCompare } from "./EngineCompare";
import { DataPane, InteractiveRunPlot, PlotsPane, ReportPane, StepsPane } from "./Panes";

export const ENGINE_LABEL: Record<string, string> = { agents: "AI agents", gsas2: "GSAS-II", maud: "MAUD" };

export function AnalyseView({ session, runId, setRunId, selected, toggle, onAsk }: {
  session: string; runId: string | null; setRunId: (id: string | null) => void;
  selected: Set<string>; toggle: (id: string) => void; onAsk: (question: string) => void;
}) {
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId!), enabled: !!runId });
  useRunEvents(runId);
  const [tab, setTab] = useState<"new" | "history">("new");
  return (
    <div className="grid h-full min-h-0 grid-cols-[360px_1fr]">
      <div className="flex min-h-0 flex-col border-r border-line bg-surface">
        <PanelHeader title={tab === "new" ? "New analysis" : "Your analyses"} actions={
          <div className="flex rounded-md border border-line-strong p-0.5">
            {(["new", "history"] as const).map((t) => <button key={t} onClick={() => setTab(t)}
              className={cn("rounded px-2 py-0.5 text-[11.5px]", tab === t ? "bg-ink font-medium text-white" : "text-muted hover:text-ink")}>
              {t === "new" ? "New" : "Past analyses"}</button>)}
          </div>} />
        <div className="min-h-0 flex-1 overflow-auto">
          {tab === "new"
            ? <NewAnalysis session={session} datasets={[...selected]} onToggleDataset={toggle} onStarted={setRunId} />
            : <RunsList selected={runId} onSelect={setRunId} />}
        </div>
      </div>
      <div className="flex min-h-0 flex-col">
        {!runId ? <AnalyseWelcome onOpen={setRunId} />
          : run.isError ? <Empty title="Could not load this analysis">{String(run.error)}</Empty>
          : !run.data ? <Empty title="Loading…" />
          : <Workspace run={run.data} onClose={() => setRunId(null)} onAsk={onAsk} />}
      </div>
    </div>
  );
}

const metric = (run: RunDetail, name: string) => run.metrics.find((m) => m.name === name);
const asNum = (v: unknown) => (typeof v === "number" ? v : typeof v === "string" && v !== "" && !isNaN(Number(v)) ? Number(v) : null);
const BANNER: Record<Tone, string> = {
  ok: "border-ok/25 bg-ok-soft", warn: "border-warn/25 bg-warn-soft", bad: "border-bad/25 bg-bad-soft",
  run: "border-accent/25 bg-accent-soft", neutral: "border-line bg-subtle",
};

function Summary({ run, onClose, onAsk }: { run: RunDetail; onClose: () => void; onAsk: (q: string) => void }) {
  const detailed = useDetailed();
  const [tech, setTech] = useState(false);
  const v = verdict(run);
  const a = metric(run, "a_refined"), cert = metric(run, "a_certified"), diff = metric(run, "difference_from_certified");
  const sigma = metric(run, "difference_in_sigma"), within = metric(run, "within_target");
  const cls = run.classification ? CLASS[run.classification] : null;
  const title = runTitle({ title: run.plan?.title, prompt: run.prompt });
  return (
    <div className="@container border-b border-line bg-surface">
      <div className="flex items-start gap-3 px-5 pt-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-[15px] font-semibold leading-6">{title}</h1>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted">
            <Status status={run.status} />
            <span>{clock(run.started_at)} · took {duration(run.started_at, run.finished_at)}</span>
            <span>Method: {ENGINE_LABEL[run.engine ?? "agents"]}</span>
            <span title={run.dataset_ids.join(", ")}>Data: {run.dataset_ids.join(", ")}</span>
            {detailed && <span className="font-mono">{run.id}</span>}
            {run.parent_run_id && <span>follow-up of {detailed ? <span className="font-mono">{run.parent_run_id}</span> : "an earlier analysis"}</span>}
          </div>
          {run.prompt.trim() !== title && <p className="mt-1 line-clamp-1 text-[12.5px] text-ink-2" title={run.prompt}>Question: “{run.prompt}”</p>}
        </div>
        <Button size="sm" variant="secondary" onClick={() => onAsk(run.status === "failed" ? "Why did this analysis fail?" : "Explain this result in plain words.")}>
          <Bot size={13} /> Ask about this {run.status === "failed" ? "failure" : "result"}</Button>
        <button onClick={onClose} title="Close and go back" aria-label="Close" className="rounded p-1 text-muted hover:bg-subtle hover:text-ink"><X size={15} /></button>
      </div>

      <div className={cn("mx-5 mt-3 rounded-lg border px-4 py-3", BANNER[v.tone])}>
        <p className="text-[14px] font-semibold leading-6 text-ink">{v.headline}</p>
        {v.details.map((d) => <p key={d} className="mt-1 text-[12.5px] leading-5 text-ink-2">{d}</p>)}
        {run.status === "failed" && run.error && <div className="mt-2">
          <button onClick={() => setTech((t) => !t)} className="text-[11.5px] text-accent hover:underline">{tech ? "Hide" : "Show"} technical details</button>
          {tech && <pre className="mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap rounded border border-line bg-surface p-2 font-mono text-[11px] text-ink-2">{run.error}</pre>}
        </div>}
      </div>

      {a && <div className="mt-3 grid grid-cols-2 border-t border-line @4xl:grid-cols-4">
        <Stat label={metricLabel("a_refined")} value={formatValue(a.value, a.uncertainty)} unit="Å"
          sub={a.uncertainty ? `± ${formatUncertainty(a.uncertainty)} Å from the fit` : undefined} />
        <Stat label="Certified value" value={asNum(cert?.value)?.toFixed(6) ?? "—"} unit="Å"
          sub={cert?.uncertainty != null ? `± ${num(cert.uncertainty)} Å (certificate, 95 %)` : undefined} />
        <Stat label="Difference" value={asNum(diff?.value)?.toFixed(6) ?? "—"} unit="Å"
          sub={sigma ? (detailed ? `${num(asNum(sigma.value), 3)} σ (fit uncertainty only)`
            : `${Math.abs(asNum(sigma.value) ?? 0).toFixed(1)}× the fit uncertainty`) : undefined} />
        <div className="border-l border-t border-line px-5 py-3 @4xl:border-t-0">
          <div className="text-[11px] text-muted">Checks</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {within && <Tag tone={String(within.value) === "true" ? "ok" : "bad"}>{String(within.value) === "true" ? "Within target" : "Outside target"}</Tag>}
            {cls && <Tag tone={cls.tone}>{cls.label}</Tag>}
            <ClaimBadge c={run.claim_check} />
          </div>
        </div>
      </div>}
      {!a && <div className="h-3" />}
    </div>
  );
}

function Stat({ label, value, unit, sub }: { label: string; value: string; unit: string; sub?: string }) {
  return (
    <div className="border-l border-line px-5 py-3 first:border-l-0 [&:nth-child(3)]:border-l-0 [&:nth-child(3)]:border-t @4xl:[&:nth-child(3)]:border-l @4xl:[&:nth-child(3)]:border-t-0">
      <div className="text-[11px] text-muted">{label}</div>
      <div className="tabular mt-0.5 font-mono text-[19px] font-medium tracking-tight">{value}{value !== "—" && <span className="ml-1 text-xs text-muted">{unit}</span>}</div>
      <div className="tabular text-[11px] text-muted">{sub ?? " "}</div>
    </div>
  );
}

function Workspace({ run, onClose, onAsk }: { run: RunDetail; onClose: () => void; onAsk: (q: string) => void }) {
  const detailed = useDetailed();
  const [log, setLog] = useState(false);
  const all = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const measuredId = run.dataset_ids.find((id) => all.data?.find((d) => d.id === id)?.role === "measured_pattern");
  const peaksPath = run.artifacts.map((a) => a.path).filter((p) => p.startsWith("outputs/") && p.endsWith("peaks.csv")).at(-1);
  const failed = run.steps.some((s) => s.status === "failed");
  const live = ["queued", "planning", "running", "analysing"].includes(run.status);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Summary run={run} onClose={onClose} onAsk={onAsk} />
      <Sections key={run.id} sections={[
        ...(run.group_id ? [{ key: "compare", label: "Compare methods", icon: Columns3, body: <EngineCompare groupId={run.group_id} /> }] : []),
        { key: "overview", label: "Overview", icon: LayoutDashboard, badge: live ? <Dot tone="run" /> : undefined,
          body: <Overview run={run} measuredId={measuredId} peaksPath={peaksPath} /> },
        { key: "steps", label: "Steps", icon: ListChecks, badge: failed ? <Dot tone="bad" /> : undefined,
          body: <StepsPane run={run} logOpen={log} onLogClose={() => setLog(false)} />,
          extra: detailed ? <Button size="sm" variant="ghost" onClick={() => setLog(true)}><FileClock size={13} /> Experiment log</Button> : undefined },
        { key: "plots", label: "Plots", icon: LineChart, body: <PlotsPane run={run} /> },
        { key: "data", label: "Values", icon: Table2, body: <DataPane run={run} /> },
        { key: "report", label: "Report", icon: FileText, body: <ReportPane run={run} />,
          badge: run.claim_check ? <Dot tone={run.claim_check.passed ? "ok" : "bad"} /> : undefined },
      ]} />
    </div>
  );
}

function Overview({ run, measuredId, peaksPath }: { run: RunDetail; measuredId?: string; peaksPath?: string }) {
  const steps = run.plan?.steps ?? [];
  return (
    <div className="flex h-full flex-col overflow-auto">
      {measuredId ? <InteractiveRunPlot runId={run.id} datasetId={measuredId} peaksPath={peaksPath} />
        : <p className="p-4 text-xs text-muted">No measured scan in this analysis.</p>}
      <div className="p-4">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-faint">What was done</h3>
        {steps.length ? <ol className="space-y-1.5">
          {steps.map((s) => {
            const st = run.steps.find((x) => x.idx === s.idx);
            return <li key={s.idx} className="flex items-start gap-2 text-[13px]">
              <span className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full bg-subtle text-[11px] font-medium text-muted">{s.idx}</span>
              <span className="min-w-0 flex-1 leading-5 text-ink-2">{s.goal}</span>
              <span className="shrink-0"><Status status={st?.status ?? "pending"} /></span>
            </li>;
          })}
        </ol> : <p className="text-[13px] text-muted">{run.status === "failed" ? "Nothing ran: the analysis stopped before a plan was made." : "Planning…"}</p>}
        <p className="mt-3 text-[12px] text-muted">The Steps tab shows who did each step and any problems that were fixed along the way.</p>
      </div>
    </div>
  );
}

function AnalyseWelcome({ onOpen }: { onOpen: (id: string) => void }) {
  const runs = useRuns();
  const recent = (runs.data ?? []).filter((r) => !r.archived).slice(0, 6);
  return (
    <Welcome title="Analyse a measured X-ray scan"
      intro="Choose a scan and say what you want to find out. AI agents plan the analysis, write and run the code in a secure sandbox,
        fix their own mistakes, and write a report in which every number is checked against the data."
      steps={[
        { icon: Database, title: "Choose your data", text: "Pick a measured scan on the left. New data goes in Data." },
        { icon: Workflow, title: "Ask your question", text: "Describe the goal in plain words, or use the example. Progress shows live." },
        { icon: FileText, title: "Read the answer", text: "A plain-language verdict first, then the plot, values and full report." },
      ]}>
      {recent.length > 0 && <WelcomeSection title="Recent analyses">
        <div className="grid gap-2 sm:grid-cols-2">
          {recent.map((r) => (
            <button key={r.id} onClick={() => onOpen(r.id)} className="rounded-lg border border-line bg-surface px-3 py-2.5 text-left hover:border-accent">
              <div className="flex items-start gap-2"><span className="line-clamp-1 text-[12.5px] font-medium">{runTitle(r)}</span>
                <span className="ml-auto shrink-0"><Status status={r.status} /></span></div>
              <div className="mt-0.5 text-[11.5px] text-muted">{clock(r.started_at)}{r.headline && <> · a = <span className="font-mono">{r.headline.a_refined.toFixed(6)} Å</span></>}</div>
            </button>
          ))}
        </div>
      </WelcomeSection>}
    </Welcome>
  );
}
