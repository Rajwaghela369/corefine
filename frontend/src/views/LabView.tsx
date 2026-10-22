import { useEffect, useState } from "react";
import { cn } from "../components/ui";
import { BridgeView } from "./BridgeView";
import { DftView } from "./DftView";
import { XrdView } from "./XrdView";

export function LabView({ session, runId, setRunId }: {
  session: string; runId: string | null; setRunId: (id: string | null) => void;
  selected?: Set<string>; toggle?: (id: string) => void;
}) {
  const params = new URLSearchParams(window.location.search);
  const m0 = params.get("mode");
  const [mode, setMode] = useState<"xrd" | "dft" | "bridge">(m0 === "dft" || m0 === "bridge" ? m0 : "xrd");
  const [jobId, setJobId] = useState<string | null>(params.get("job"));
  // keep the address bar equal to what is on screen, so an old link never reopens something you did not choose
  useEffect(() => {
    const q = new URLSearchParams({ view: "lab", mode });
    if (mode === "xrd" && runId) q.set("run", runId);
    if (mode === "dft" && jobId) q.set("job", jobId);
    window.history.replaceState(null, "", `?${q.toString()}`);
  }, [mode, runId, jobId]);
  const pickMode = (m: "xrd" | "dft" | "bridge") => {
    if (m === mode) { if (m === "xrd") setRunId(null); if (m === "dft") setJobId(null); }  // same tab again = back to its start page
    setMode(m);
  };
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
        <span className="text-[11px] font-medium uppercase tracking-wider text-faint">Workflow</span>
        <div className="flex rounded-md border border-line-strong p-0.5">
          {([["xrd", "Experiment · XRD"], ["dft", "Theory · DFT"], ["bridge", "Theory ↔ Experiment"]] as const).map(([m, label]) => (
            <button key={m} onClick={() => pickMode(m)} className={cn("rounded px-3 py-1 text-xs",
              mode === m ? "bg-ink font-medium text-white" : "text-muted hover:text-ink")}>{label}</button>
          ))}
        </div>
        <span className="text-[11px] text-muted">{mode === "xrd"
          ? "Measured scan → agents, GSAS-II or MAUD → reasoning, results, comparison"
          : mode === "dft" ? "Material → plan → inputs for every code → checks, runs, band gaps, convergence"
          : "What the measurement says next to what every code predicts"}</span>
      </div>
      <div className="min-h-0 flex-1">
        {mode === "xrd" ? <XrdView session={session} runId={runId} setRunId={setRunId} />
          : mode === "dft" ? <DftView jobId={jobId} setJobId={setJobId} /> : <BridgeView />}
      </div>
    </div>
  );
}
