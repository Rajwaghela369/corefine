import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, CornerDownLeft } from "lucide-react";
import { type ReactNode, useState } from "react";
import { api, dft, type DatasetNode, type Engine } from "../api/client";
import { ROLE_LABEL } from "../components/labels";
import { useDetailed } from "../components/prefs";
import { Button, cn } from "../components/ui";

const EXAMPLE = "Refine silicon's lattice parameter from the 640f scan and compare it with the certified value.";

/** Start an analysis in three steps: data, question, method. The method stays out of the way unless asked for. */
export function NewAnalysis({ session, datasets, onToggleDataset, onStarted }: {
  session: string; datasets: string[]; onToggleDataset: (id: string) => void; onStarted: (id: string) => void }) {
  const detailed = useDetailed();
  const qc = useQueryClient();
  const all = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const engineList = useQuery({ queryKey: ["engines"], queryFn: api.engines,
    refetchInterval: (q) => (q.state.data?.some((e) => e.install?.status === "installing") ? 3000 : false) });
  const [text, setText] = useState("");
  const [engines, setEngines] = useState<Engine[]>(["agents"]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showMethod, setShowMethod] = useState(false);

  const valid = (all.data ?? []).filter((d) => d.valid);
  const measured = valid.filter((d) => d.role === "measured_pattern");
  const references = valid.filter((d) => d.role !== "measured_pattern");
  const hasMeasured = datasets.some((id) => measured.some((d) => d.id === id));
  const needsText = engines.includes("agents");
  const missing = !hasMeasured ? "Choose a measured scan in step 1."
    : !engines.length ? "Choose at least one method in step 3."
    : needsText && !text.trim() ? "Describe what you want to find out in step 2." : null;
  const engineName = (e: string) => engineList.data?.find((x) => x.name === e)?.label ?? e;
  const prompt = text.trim() || `Refine the lattice parameters with ${engines.map(engineName).join(" and ")}`;
  const installing = (engineList.data ?? []).some((e) => e.install?.status === "installing");

  async function start() {
    if (missing) return;
    setBusy(true); setError(null);
    try {
      const { id } = await api.startRun({ prompt, dataset_ids: datasets, parent_run_id: null, engines, session_id: session });
      setText("");
      qc.invalidateQueries({ queryKey: ["runs"] });
      onStarted(id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }

  async function install(tool: string) {
    setError(null);
    try { await dft.installTool(tool); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    qc.invalidateQueries({ queryKey: ["engines"] });
  }

  const methodOpen = detailed || showMethod || engines.length !== 1 || engines[0] !== "agents";
  return (
    <div className="space-y-4 p-4">
      <StepBlock n={1} title="Your data" hint="The measured scan to analyse, plus a reference structure if you have one.">
        <DatasetGroup label="Measured scans" items={measured} selected={datasets} onToggle={onToggleDataset} />
        {references.length > 0 && <DatasetGroup label="Reference structures (optional)" items={references} selected={datasets} onToggle={onToggleDataset} />}
        {measured.length === 0 && <p className="text-[11.5px] text-muted">No measured scans yet. Add one under Data.</p>}
      </StepBlock>

      <StepBlock n={2} title="What do you want to find out?" hint="Plain language is fine.">
        <div className="rounded-md border border-line-strong focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/15">
          <textarea className="block h-20 w-full resize-none rounded-t-md bg-transparent p-2.5 text-[13px] leading-5 outline-none placeholder:text-faint"
            value={text} placeholder={`e.g. “${EXAMPLE}”`} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); start(); } }} />
          <div className="border-t border-line px-2.5 py-1.5">
            <button className="text-[11.5px] text-accent hover:underline" onClick={() => setText(EXAMPLE)}>Use the example question</button>
          </div>
        </div>
      </StepBlock>

      <StepBlock n={3} title="Method" hint={methodOpen ? undefined : `AI agents write and run the analysis (${engineName("agents")}).`}
        action={!detailed && <button onClick={() => setShowMethod((v) => !v)} className="flex items-center gap-0.5 text-[11.5px] text-accent hover:underline">
          {methodOpen ? "Hide" : "Change"}<ChevronDown size={12} className={cn("transition", methodOpen && "rotate-180")} /></button>}>
        {methodOpen && <div className="space-y-1.5">
          {(engineList.data ?? []).map((e) => {
            const on = engines.includes(e.name);
            return (
              <div key={e.name} className={cn("rounded-md border px-2.5 py-2", on ? "border-accent bg-accent-soft/60" : "border-line")}>
                <label className={cn("flex items-start gap-2", e.available ? "cursor-pointer" : "opacity-60")}>
                  <input type="checkbox" className="mt-0.5 accent-[#1f4fd1]" checked={on} disabled={!e.available}
                    onChange={() => setEngines((s) => (on ? s.filter((x) => x !== e.name) : [...s, e.name]))} />
                  <span className="min-w-0">
                    <span className="block text-[12.5px] font-medium">{e.label}</span>
                    <span className="block text-[11.5px] leading-4 text-muted">{e.about}</span>
                  </span>
                </label>
                {!e.available && e.tool && <div className="mt-1.5 flex items-center gap-2 pl-6 text-[11px] text-muted">
                  <span>Not installed ({e.install?.size})</span>
                  {e.install?.status === "installing" ? <span className="text-accent">{e.install.message}</span>
                    : <button className="text-accent hover:underline disabled:opacity-50" disabled={installing} onClick={() => install(e.tool!)}>Install</button>}
                  {e.install?.status === "failed" && <span className="text-bad" title={e.install.message}>install failed</span>}
                </div>}
              </div>
            );
          })}
          {engines.length > 1 && <p className="text-[11px] text-muted">Each method runs separately and the results are shown side by side.</p>}
        </div>}
      </StepBlock>

      <div>
        <Button variant="primary" className="h-9 w-full" disabled={!!missing || busy} onClick={start}>
          {busy ? "Starting…" : "Start analysis"} {!busy && <CornerDownLeft size={12} className="opacity-70" />}
        </Button>
        <p className={cn("mt-1.5 text-[11.5px]", missing ? "text-warn" : "text-muted")}>
          {missing ?? "Takes a few minutes. You can follow every step live, and every number in the report is checked against the data."}</p>
        {error && <p className="mt-2 rounded-md border border-bad/20 bg-bad-soft px-2.5 py-2 text-xs text-bad">{error}</p>}
      </div>
    </div>
  );
}

function StepBlock({ n, title, hint, action, children }: { n: number; title: string; hint?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <div className="mb-1.5 flex items-center gap-2">
        <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent">{n}</span>
        <h3 className="text-[13px] font-semibold">{title}</h3>
        {action && <span className="ml-auto">{action}</span>}
      </div>
      {hint && <p className="mb-2 pl-7 text-[11.5px] leading-4 text-muted">{hint}</p>}
      <div className="pl-7">{children}</div>
    </section>
  );
}

function DatasetGroup({ label, items, selected, onToggle }: { label: string; items: DatasetNode[]; selected: string[]; onToggle: (id: string) => void }) {
  const detailed = useDetailed();
  if (!items.length) return null;
  return (
    <div className="mb-2">
      <div className="mb-1 text-[11px] font-medium text-muted">{label}</div>
      <ul className="space-y-1">
        {items.map((d) => {
          const on = selected.includes(d.id);
          return (
            <li key={d.id}>
              <button onClick={() => onToggle(d.id)} aria-pressed={on}
                className={cn("flex w-full items-center gap-2 rounded-md border px-2.5 py-1.5 text-left",
                  on ? "border-accent bg-accent-soft/60" : "border-line hover:border-line-strong")}>
                <span className={cn("flex size-4 shrink-0 items-center justify-center rounded border",
                  on ? "border-accent bg-accent text-white" : "border-line-strong")}>{on && <Check size={11} strokeWidth={3} />}</span>
                <span className="min-w-0">
                  <span className="block truncate text-[12.5px] font-medium">{d.material ?? d.id}
                    <span className="ml-1.5 font-normal text-muted">{ROLE_LABEL[d.role ?? ""]?.toLowerCase()}</span></span>
                  <span className={cn("block truncate text-[11px] text-faint", detailed && "font-mono")}>{d.id}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
