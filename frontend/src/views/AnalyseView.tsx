import { Database, FileText, Workflow } from "lucide-react";
import { useState } from "react";
import { runTitle } from "../components/labels";
import { PanelHeader, Status, clock, cn } from "../components/ui";
import { Welcome, WelcomeSection } from "../components/Welcome";
import { NewAnalysis } from "../panels/NewAnalysis";
import { RunsList, useRuns } from "../panels/RunsList";
import { useRunEvents } from "../useRunEvents";
import { AnalysisWorkspace } from "./XrdView";

export function AnalyseView({ session, runId, setRunId, selected, toggle, onAsk }: {
  session: string; runId: string | null; setRunId: (id: string | null) => void;
  selected: Set<string>; toggle: (id: string) => void; onAsk: (question: string) => void;
}) {
  useRunEvents(runId);
  const [panel, setPanel] = useState<"new" | "history">("new");
  // a ?tab= link opens that tab once; read it before the address bar is rewritten
  const [tab] = useState(() => new URLSearchParams(window.location.search).get("tab") ?? undefined);
  return (
    <div className="grid h-full min-h-0 grid-cols-[360px_1fr]">
      <div className="flex min-h-0 flex-col border-r border-line bg-surface">
        <PanelHeader title={panel === "new" ? "New analysis" : "Your analyses"} actions={
          <div className="flex rounded-md border border-line-strong p-0.5">
            {(["new", "history"] as const).map((t) => <button key={t} onClick={() => setPanel(t)}
              className={cn("rounded px-2 py-0.5 text-[11.5px]", panel === t ? "bg-ink font-medium text-white" : "text-muted hover:text-ink")}>
              {t === "new" ? "New" : "Past analyses"}</button>)}
          </div>} />
        <div className="min-h-0 flex-1 overflow-auto">
          {panel === "new"
            ? <NewAnalysis session={session} datasets={[...selected]} onToggleDataset={toggle} onStarted={setRunId} />
            : <RunsList selected={runId} onSelect={setRunId} />}
        </div>
      </div>
      <div className="flex min-h-0 flex-col">
        {!runId ? <AnalyseWelcome onOpen={setRunId} />
          : <AnalysisWorkspace key={runId} id={runId} tab={tab} onClose={() => setRunId(null)} onAsk={onAsk} />}
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
