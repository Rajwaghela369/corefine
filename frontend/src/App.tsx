import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, sessionId } from "./api/client";
import { cn } from "./components/ui";
import { ChatPanel } from "./panels/ChatPanel";
import { DataPanel } from "./panels/DataPanel";
import { RunsList } from "./panels/RunsList";
import { PlanTab } from "./tabs/PlanTab";
import { DataTab, PlotsTab, ReportTab } from "./tabs/ResultTabs";
import { useRunEvents } from "./useRunEvents";

const TABS = ["Plan", "Plots", "Data", "Report"] as const;
type Tab = (typeof TABS)[number];

export default function App() {
  const [session] = useState(sessionId);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // ?run=<id>&tab=Report opens a run directly (shareable link)
  const params = new URLSearchParams(window.location.search);
  const [runId, setRunId] = useState<string | null>(params.get("run"));
  const [tab, setTab] = useState<Tab>((TABS as readonly string[]).includes(params.get("tab") ?? "") ? params.get("tab") as Tab : "Plan");
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.run(runId!), enabled: !!runId });
  useRunEvents(runId);

  const toggle = (id: string) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-line px-4 py-2">
        <span className="font-semibold">CoRefine</span>
        <span className="text-xs text-muted">raw data → refined result, every number traced to a file</span>
      </header>
      <main className="grid min-h-0 flex-1 grid-cols-[minmax(240px,1fr)_minmax(340px,1.4fr)_minmax(420px,2fr)]">
        <div className="min-h-0 border-r border-line"><DataPanel selected={selected} onToggle={toggle} /></div>
        <div className="min-h-0 border-r border-line">
          <ChatPanel session={session} datasets={[...selected]} selectedRun={runId}
            onRunStarted={(id) => { setRunId(id); setTab("Plan"); }} />
        </div>
        <div className="flex min-h-0 flex-col">
          <RunsList selected={runId} onSelect={setRunId} />
          <nav className="flex gap-1 border-b border-line px-2">
            {TABS.map((t) => (
              <button key={t} onClick={() => setTab(t)} className={cn("px-3 py-2 text-sm",
                tab === t ? "border-b-2 border-ink font-medium" : "text-muted hover:text-ink")}>{t}</button>
            ))}
          </nav>
          <div className="min-h-0 flex-1 overflow-auto">
            {!runId && <p className="p-4 text-sm text-muted">Select a run, or start one from the conversation.</p>}
            {run.isError && <p className="p-4 text-sm text-red-700">{String(run.error)}</p>}
            {run.data && tab === "Plan" && <PlanTab run={run.data} />}
            {run.data && tab === "Plots" && <PlotsTab run={run.data} />}
            {run.data && tab === "Data" && <DataTab run={run.data} />}
            {run.data && tab === "Report" && <ReportTab run={run.data} />}
          </div>
        </div>
      </main>
    </div>
  );
}
