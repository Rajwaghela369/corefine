import { useState } from "react";
import { sessionId } from "./api/client";
import { Header } from "./components/Header";
import { Sidebar, type View } from "./components/Sidebar";
import { LabView } from "./views/LabView";
import { StorageView } from "./views/StorageView";

export default function App() {
  // ?view=lab&run=<id> opens a run directly (shareable link)
  const params = new URLSearchParams(window.location.search);
  const [view, setView] = useState<View>(params.get("view") === "storage" ? "storage" : "lab");
  const [session] = useState(sessionId);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [runId, setRunId] = useState<string | null>(params.get("run"));

  const toggle = (id: string) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  return (
    <div className="flex h-full min-w-[1180px] flex-col">
      <Header />
      <div className="flex min-h-0 flex-1">
        <Sidebar view={view} onChange={setView} />
        <main className="min-h-0 min-w-0 flex-1">
          {view === "storage" ? <StorageView />
            : <LabView session={session} runId={runId} setRunId={setRunId} selected={selected} toggle={toggle} />}
        </main>
      </div>
    </div>
  );
}
