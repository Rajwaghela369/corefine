import { useQuery } from "@tanstack/react-query";
import { FileClock, Maximize2, Minimize2 } from "lucide-react";
import { type ReactNode, useState } from "react";
import { api, type RunDetail } from "../api/client";
import { Button, Empty, Status, Tag, type Tone, clock, cn, duration, fixed, num } from "../components/ui";
import { ChatPanel, ClaimBadge } from "../panels/ChatPanel";
import { RunsList } from "../panels/RunsList";
import { useRunEvents } from "../useRunEvents";
import { DataPane, PlanPane, PlotsPane, ReportPane } from "./Panes";

type Quadrant = "plan" | "plots" | "data" | "report";

export function LabView({ session, runId, setRunId, selected, toggle }: {
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
        {!runId ? <Empty title="No analysis selected">Start an analysis on the left, or pick one from the history.</Empty>
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
  const [max, setMax] = useState<Quadrant | null>(null);
  const [log, setLog] = useState(false);
  const panes: Record<Quadrant, { title: string; body: ReactNode; extra?: ReactNode }> = {
    plan: { title: "Plan", body: <PlanPane run={run} logOpen={log} onLogClose={() => setLog(false)} />,
      extra: <Button size="sm" variant="ghost" onClick={() => setLog(true)} title="Experiment log"><FileClock size={13} /> Log</Button> },
    plots: { title: "Plots", body: <PlotsPane run={run} /> },
    data: { title: "Data", body: <DataPane run={run} /> },
    report: { title: "Report", body: <ReportPane run={run} /> },
  };
  const order: Quadrant[] = ["plan", "plots", "data", "report"];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Summary run={run} />
      <div className={cn("grid min-h-0 flex-1 gap-3 p-3", max ? "grid-cols-1 grid-rows-1" : "grid-cols-2 grid-rows-2")}>
        {order.filter((q) => !max || q === max).map((q) => (
          <section key={q} className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-[0_1px_2px_rgba(16,24,40,.04)]">
            <header className="flex h-9 shrink-0 items-center gap-2 border-b border-line pl-3 pr-1.5">
              <h2 className="text-xs font-semibold">{panes[q].title}</h2>
              <div className="ml-auto flex items-center">{panes[q].extra}
                <Button size="sm" variant="ghost" onClick={() => setMax(max ? null : q)} title={max ? "Restore" : "Maximise"} aria-label={max ? "Restore" : "Maximise"}>
                  {max ? <Minimize2 size={13} /> : <Maximize2 size={13} />}</Button>
              </div>
            </header>
            <div className="min-h-0 flex-1 overflow-auto">{panes[q].body}</div>
          </section>
        ))}
      </div>
    </div>
  );
}
