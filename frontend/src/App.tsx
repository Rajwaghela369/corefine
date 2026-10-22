import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, sessionId } from "./api/client";
import { Header } from "./components/Header";
import { DetailProvider } from "./components/prefs";
import { Sidebar, VIEWS, type View } from "./components/Sidebar";
import { Assistant } from "./panels/Assistant";
import { AnalyseView } from "./views/AnalyseView";
import { BridgeView } from "./views/BridgeView";
import { DftView } from "./views/DftView";
import { HistoryView, HomeView } from "./views/HomeView";
import { StorageView } from "./views/StorageView";

// Links from before the task-based layout (?view=lab&mode=dft …) still open the right page
function viewFromUrl(p: URLSearchParams): View {
  const v = p.get("view"), mode = p.get("mode");
  if (v === "storage") return "data";
  if (v === "lab") return mode === "dft" ? "simulate" : mode === "bridge" ? "compare" : "analyse";
  return VIEWS.some((x) => x.id === v) ? (v as View) : p.get("run") ? "analyse" : "home";
}

const ASSISTANT_KEY = "corefine-assistant-open";
const loadOpen = () => { try { return localStorage.getItem(ASSISTANT_KEY) === "1"; } catch { return false; } };

export default function App() {
  const params = new URLSearchParams(window.location.search);
  const [view, setView] = useState<View>(viewFromUrl(params));
  const [session] = useState(sessionId);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [runId, setRunId] = useState<string | null>(params.get("run"));
  const [jobId, setJobId] = useState<string | null>(params.get("job"));
  const [material, setMaterial] = useState<string | null>(params.get("material"));
  const [assistantOpen, setAssistantOpen] = useState(loadOpen);
  const [pending, setPending] = useState<string | null>(null);
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });

  // keep the address bar equal to what is on screen, so a copied link reopens the same thing
  useEffect(() => {
    const q = new URLSearchParams({ view });
    if (view === "analyse" && runId) q.set("run", runId);
    if (view === "simulate" && jobId) q.set("job", jobId);
    if ((view === "compare" || view === "simulate") && material) q.set("material", material);
    window.history.replaceState(null, "", `?${q.toString()}`);
  }, [view, runId, jobId, material]);
  useEffect(() => { try { localStorage.setItem(ASSISTANT_KEY, assistantOpen ? "1" : "0"); } catch { /* private window */ } }, [assistantOpen]);

  const toggle = (id: string) => setSelected((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });
  const go = (v: View) => {
    if (v === view && v === "analyse") setRunId(null);  // the same page again = back to its start
    if (v === view && v === "simulate") setJobId(null);
    setView(v);
  };
  const openRun = (id: string | null) => { setRunId(id); setView("analyse"); };
  const ask = (question: string) => { setAssistantOpen(true); setPending(question); };
  const goFromCompare = (to: "analyse" | "simulate", m?: string) => {
    setMaterial(m ?? null);
    if (to === "analyse" && m) {
      setSelected(new Set((datasets.data ?? []).filter((d) => d.valid && d.role === "measured_pattern" && d.material === m).map((d) => d.id)));
      setRunId(null);
    }
    if (to === "simulate") setJobId(null);
    setView(to);
  };
  const title = VIEWS.find((v) => v.id === view)!.title;

  return (
    <DetailProvider>
      <div className="flex h-full min-w-[1180px] flex-col">
        <Header title={title} assistantOpen={assistantOpen} onToggleAssistant={() => setAssistantOpen((o) => !o)} />
        <div className="flex min-h-0 flex-1">
          <Sidebar view={view} onChange={go} />
          <main className="min-h-0 min-w-0 flex-1">
            {view === "home" ? <HomeView onGo={go} onOpenRun={openRun} onAsk={() => setAssistantOpen(true)} />
              : view === "data" ? <StorageView />
              : view === "analyse" ? <AnalyseView session={session} runId={runId} setRunId={setRunId} selected={selected} toggle={toggle} onAsk={ask} />
              : view === "simulate" ? <DftView jobId={jobId} setJobId={setJobId} />
              : view === "compare" ? <BridgeView key={material ?? ""} onGo={goFromCompare} />
              : <HistoryView onOpenRun={openRun} />}
          </main>
          <Assistant session={session} open={assistantOpen} onClose={() => setAssistantOpen(false)}
            runId={view === "analyse" ? runId : null} datasets={[...selected]}
            pending={pending} onPendingTaken={() => setPending(null)} onRunStarted={openRun} />
        </div>
      </div>
    </DetailProvider>
  );
}
