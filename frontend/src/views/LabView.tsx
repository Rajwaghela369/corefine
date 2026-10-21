import { useQuery } from "@tanstack/react-query";
import { Database, FileClock, FileText, LayoutDashboard, LineChart, Table2, Workflow } from "lucide-react";
import { Welcome, WelcomeSection } from "../components/Welcome";
import { useState } from "react";
import { api, type RunDetail } from "../api/client";
import { Dot, Sections } from "../components/Sections";
import { Button, Empty, Status, Tag, type Tone, clock, cn, duration, fixed, num } from "../components/ui";
import { ChatPanel, ClaimBadge } from "../panels/ChatPanel";
import { RunsList } from "../panels/RunsList";
import { useRunEvents } from "../useRunEvents";
import { BridgeView } from "./BridgeView";
import { DftView } from "./DftView";
import { DataPane, InteractiveRunPlot, PlanPane, PlotsPane, ReportPane } from "./Panes";

export function LabView({ session, runId, setRunId, selected, toggle }: {
  session: string; runId: string | null; setRunId: (id: string | null) => void;
  selected: Set<string>; toggle: (id: string) => void;
}) {
  const params = new URLSearchParams(window.location.search);
  const m0 = params.get("mode");
  const [mode, setMode] = useState<"xrd" | "dft" | "bridge">(m0 === "dft" || m0 === "bridge" ? m0 : "xrd");
  const [jobId, setJobId] = useState<string | null>(params.get("job"));
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
        <span className="text-[11px] font-medium uppercase tracking-wider text-faint">Workflow</span>
        <div className="flex rounded-md border border-line-strong p-0.5">
          {([["xrd", "Experiment · XRD"], ["dft", "Theory · DFT"], ["bridge", "Theory ↔ Experiment"]] as const).map(([m, label]) => (
            <button key={m} onClick={() => setMode(m)} className={cn("rounded px-3 py-1 text-xs",
              mode === m ? "bg-ink font-medium text-white" : "text-muted hover:text-ink")}>{label}</button>
          ))}
        </div>
        <span className="text-[11px] text-muted">{mode === "xrd"
          ? "Measured pattern → agents write and run the analysis → traced report"
          : mode === "dft" ? "Material → plan → inputs for every code → checks, runs, convergence, EOS, Raman"
          : "What the measurement says next to what every code predicts"}</span>
      </div>
      <div className="min-h-0 flex-1">
        {mode === "xrd" ? <XrdLab session={session} runId={runId} setRunId={setRunId} selected={selected} toggle={toggle} />
          : mode === "dft" ? <DftView jobId={jobId} setJobId={setJobId} /> : <BridgeView />}
      </div>
    </div>
  );
}

function XrdLab({ session, runId, setRunId, selected, toggle }: {
  session: string; runId: string | null; setRunId: (id: string | null) => void;
  selected: Set<string>; toggle: (id: string) => void;
}) {
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId!), enabled: !!runId });
  useRunEvents(runId);
  return (
    <div className="grid h-full min-h-0 grid-cols-[360px_1fr]">
      <div className="min-h-0 border-r border-line">
        <ChatPanel session={session} datasets={[...selected]} onToggleDataset={toggle} selectedRun={runId}
          onRunStarted={setRunId} history={<RunsList selected={runId} onSelect={setRunId} />} />
      </div>
      <div className="flex min-h-0 flex-col">
        {!runId ? <XrdWelcome onOpen={setRunId} />
          : run.isError ? <Empty title="Could not load the run">{String(run.error)}</Empty>
          : !run.data ? <Empty title="Loading…" />
          : <Workspace run={run.data} />}
      </div>
    </div>
  );
}

const metric = (run: RunDetail, name: string) => run.metrics.find((m) => m.name === name);
const asNum = (v: unknown) => (typeof v === "number" ? v : typeof v === "string" && v !== "" && !isNaN(Number(v)) ? Number(v) : null);

const CLASS: Record<string, { label: string; tone: Tone }> = {
  agreement: { label: "Agreement", tone: "ok" },
  missing_geometric_correction: { label: "Missing geometric correction", tone: "warn" },
  metadata_issue: { label: "Metadata issue", tone: "warn" },
  weak_or_overlapping_peaks: { label: "Weak or overlapping peaks", tone: "warn" },
  unexplained: { label: "Unexplained — needs review", tone: "bad" },
};

function Summary({ run }: { run: RunDetail }) {
  const a = metric(run, "a_refined"), cert = metric(run, "a_certified"), diff = metric(run, "difference_from_certified");
  const sigma = metric(run, "difference_in_sigma"), within = metric(run, "within_target"), target = metric(run, "success_target");
  const withinTrue = String(within?.value) === "true";
  const cls = run.classification ? CLASS[run.classification] : null;
  return (
    <div className="border-b border-line bg-surface">
      <div className="flex items-center gap-3 px-5 pb-2 pt-3">
        <h1 className="font-mono text-[13px] font-semibold">{run.id}</h1>
        <Status status={run.status} />
        <span className="text-xs text-muted">{clock(run.started_at)} · {duration(run.started_at, run.finished_at)}</span>
        {run.parent_run_id && <span className="text-xs text-muted">follow-up of <span className="font-mono">{run.parent_run_id}</span></span>}
        <span className="ml-auto truncate text-xs text-muted" title={run.dataset_ids.join(", ")}>
          inputs: <span className="font-mono">{run.dataset_ids.join(", ")}</span></span>
      </div>
      <p className="truncate px-5 pb-3 text-[13px] text-ink-2" title={run.prompt}>{run.prompt}</p>
      <div className="grid grid-cols-4 border-t border-line">
        <Stat label="Refined lattice parameter" unit="Å" value={fixed(asNum(a?.value))} sub={a?.uncertainty != null ? `± ${fixed(a.uncertainty)} (1σ)` : undefined} />
        <Stat label="Certified value" unit="Å" value={fixed(asNum(cert?.value))} sub={cert?.uncertainty != null ? `± ${num(cert.uncertainty)} (k = 2)` : undefined} />
        <Stat label="Difference" unit="Å" value={diff ? fixed(asNum(diff.value)) : "—"}
          sub={sigma ? `${num(asNum(sigma.value), 3)} σ` : undefined} />
        <div className="border-l border-line px-5 py-3">
          <div className="text-[11px] text-muted">Assessment</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {within && <Tag tone={withinTrue ? "ok" : "bad"}>{withinTrue ? "Within" : "Outside"} ± {num(asNum(target?.value))} Å target</Tag>}
            {cls && <Tag tone={cls.tone}>{cls.label}</Tag>}
            <ClaimBadge c={run.claim_check} />
            {!within && !cls && <span className="text-[13px] text-faint">—</span>}
          </div>
          {run.status === "failed" && <p className="mt-1 line-clamp-2 text-[11px] text-bad" title={run.error ?? ""}>{run.error}</p>}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, unit, sub }: { label: string; value: string; unit: string; sub?: string }) {
  return (
    <div className="border-l border-line px-5 py-3 first:border-l-0">
      <div className="text-[11px] text-muted">{label}</div>
      <div className="tabular mt-0.5 font-mono text-[19px] font-medium tracking-tight">{value}{value !== "—" && <span className="ml-1 text-xs text-muted">{unit}</span>}</div>
      <div className="tabular font-mono text-[11px] text-muted">{sub ?? " "}</div>
    </div>
  );
}

function Workspace({ run }: { run: RunDetail }) {
  const [log, setLog] = useState(false);
  const all = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const measuredId = run.dataset_ids.find((id) => all.data?.find((d) => d.id === id)?.role === "measured_pattern");
  const peaksPath = run.artifacts.map((a) => a.path).filter((p) => p.startsWith("outputs/") && p.endsWith("peaks.csv")).at(-1);
  const failed = run.steps.filter((s) => s.status === "failed").length;
  const live = ["queued", "planning", "running", "analysing"].includes(run.status);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Summary run={run} />
      <Sections key={run.id} sections={[
        { key: "overview", label: "Overview", icon: LayoutDashboard, badge: live ? <Dot tone="run" /> : undefined,
          body: <XrdOverview run={run} measuredId={measuredId} peaksPath={peaksPath} /> },
        { key: "plan", label: "Plan", icon: Workflow, badge: failed ? <Dot tone="bad" /> : undefined,
          body: <PlanPane run={run} logOpen={log} onLogClose={() => setLog(false)} />,
          extra: <Button size="sm" variant="ghost" onClick={() => setLog(true)}><FileClock size={13} /> Experiment log</Button> },
        { key: "plots", label: "Plots", icon: LineChart, body: <PlotsPane run={run} /> },
        { key: "data", label: "Data", icon: Table2, body: <DataPane run={run} /> },
        { key: "report", label: "Report", icon: FileText, body: <ReportPane run={run} />,
          badge: run.claim_check ? <Dot tone={run.claim_check.passed ? "ok" : "bad"} /> : undefined },
      ]} />
    </div>
  );
}

function XrdWelcome({ onOpen }: { onOpen: (id: string) => void }) {
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  return (
    <Welcome title="Experiment: XRD refinement"
      intro="Describe the analysis in plain language and pick the measured scan. Agents plan it, write and run the analysis code in a sandbox,
        retry when code fails, and write a report in which every number is checked against the files the run produced."
      steps={[
        { icon: Database, title: "Choose data", text: "Select a measured pattern (and a reference structure) under Inputs; new data goes in Storage." },
        { icon: Workflow, title: "Start the analysis", text: "Describe the goal or use the example; the plan and each step's code and log are shown live." },
        { icon: FileText, title: "Read the result", text: "Refined values with uncertainties, the fitted scan, and a report whose numbers are all traced." },
      ]}>
      {(runs.data?.length ?? 0) > 0 && <WelcomeSection title="Recent analyses">
        <div className="grid gap-2 sm:grid-cols-2">
          {runs.data!.slice(0, 6).map((r) => (
            <button key={r.id} onClick={() => onOpen(r.id)} className="rounded-lg border border-line bg-surface px-3 py-2.5 text-left hover:border-accent">
              <div className="flex items-center gap-2"><span className="font-mono text-[12px] font-semibold">{r.id}</span>
                <span className="ml-auto"><Status status={r.status} /></span></div>
              <p className="mt-0.5 line-clamp-1 text-[12px] text-ink-2">{r.prompt}</p>
              {r.headline && <div className="mt-0.5 font-mono text-[11.5px] text-muted">a = {fixed(r.headline.a_refined)} Å</div>}
            </button>
          ))}
        </div>
      </WelcomeSection>}
    </Welcome>
  );
}

function XrdOverview({ run, measuredId, peaksPath }: { run: RunDetail; measuredId?: string; peaksPath?: string }) {
  const cls = run.classification ? CLASS[run.classification] : null;
  return (
    <div className="flex h-full flex-col overflow-auto">
      {measuredId ? <InteractiveRunPlot runId={run.id} datasetId={measuredId} peaksPath={peaksPath} />
        : <p className="p-4 text-xs text-muted">No measured pattern in this run's inputs.</p>}
      <div className="grid gap-4 p-4 md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-faint">What ran</h3>
          <ol className="space-y-1.5">
            {(run.plan?.steps ?? []).map((s) => {
              const st = run.steps.find((x) => x.idx === s.idx);
              return <li key={s.idx} className="flex items-center gap-2 text-[13px]">
                <span className="w-5 font-mono text-[11px] text-faint">{String(s.idx).padStart(2, "0")}</span>
                <span className="font-mono text-[12px]">{s.name}</span>
                <Status status={st?.status ?? "pending"} />
                {st && st.attempts > 1 && <span className="text-[11px] text-warn">recovered on attempt {st.attempts}</span>}
              </li>;
            })}
          </ol>
        </div>
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-faint">Verdict</h3>
          {cls ? <Tag tone={cls.tone}>{cls.label}</Tag> : <span className="text-[13px] text-muted">pending</span>}
          <p className="mt-2 text-[13px] leading-6 text-ink-2">
            The agents planned the analysis, wrote and ran the code in a sandbox, and the analyst's report passed the number
            check: every value in it traces to a file this run produced.</p>
        </div>
      </div>
    </div>
  );
}
