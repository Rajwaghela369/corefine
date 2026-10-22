import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, CornerDownLeft } from "lucide-react";
import { type ReactNode, useState } from "react";
import { api, type DatasetNode, type Engine } from "../api/client";
import { instrumentLine } from "../components/labels";
import { useGo } from "../components/nav";
import { Picker, type PickerOption } from "../components/Picker";
import { useDetailed } from "../components/prefs";
import { Button, cn } from "../components/ui";

const AUTO = "__auto";

const EXAMPLE = "Refine silicon's lattice parameter from the 640f scan and compare it with the certified value.";

/** Start an analysis in three steps: data, question, method. The method stays out of the way unless asked for. */
export function NewAnalysis({ session, datasets, onToggleDataset, onStarted }: {
  session: string; datasets: string[]; onToggleDataset: (id: string) => void; onStarted: (id: string) => void }) {
  const detailed = useDetailed();
  const go = useGo();
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
  const references = valid.filter((d) => d.role === "reference_structure");
  const scan = measured.find((d) => datasets.includes(d.id)) ?? null;
  const reference = references.find((d) => datasets.includes(d.id)) ?? null;
  const hasMeasured = !!scan;
  // one scan and at most one reference: picking replaces whatever of that kind was chosen before
  const choose = (pool: DatasetNode[], id: string | null) => {
    pool.filter((d) => datasets.includes(d.id) && d.id !== id).forEach((d) => onToggleDataset(d.id));
    if (id && !datasets.includes(id)) onToggleDataset(id);
  };
  const autoRef = scan ? references.find((r) => r.material === scan.material) : undefined;
  const needsText = engines.includes("agents");
  const missing = !hasMeasured ? "Choose a measured scan in step 1."
    : !engines.length ? "Choose at least one method in step 3."
    : needsText && !text.trim() ? "Describe what you want to find out in step 2."
    : engines.some((e) => e !== "agents") && !reference && !autoRef
      ? "GSAS-II and MAUD refine a crystal model, and there is none for this scan yet. Pick a reference structure in step 1, or use the agents method."
    : null;
  const engineName = (e: string) => engineList.data?.find((x) => x.name === e)?.label ?? e;
  const prompt = text.trim() || `Refine the lattice parameters with ${engines.map(engineName).join(" and ")}`;

  async function start() {
    if (missing) return;
    setBusy(true); setError(null);
    try {
      // "Automatic" reference: the structure for the scan's material, sent along so every method uses the same one
      const ids = !reference && autoRef ? [...datasets, autoRef.id] : datasets;
      const { id } = await api.startRun({ prompt, dataset_ids: ids, parent_run_id: null, engines, session_id: session });
      setText("");
      qc.invalidateQueries({ queryKey: ["runs"] });
      onStarted(id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }

  const methodOpen = detailed || showMethod || engines.length !== 1 || engines[0] !== "agents";
  return (
    <div className="space-y-4 p-4">
      <StepBlock n={1} title="Your data" hint="The measured scan to analyse, and the structure to compare it with.">
        <div className="space-y-2">
          <Picker label="Measured scan" placeholder="Choose a measured scan" searchable={measured.length > 6}
            options={measured.map(scanOption)} value={scan ? [scan.id] : []}
            onChange={([id]) => choose(measured, id)}
            empty="No measured scans yet. Add one under Data." />
          {references.length > 0 && <div>
            <div className="mb-1 text-[11px] font-medium text-muted">Reference structure</div>
            <Picker label="Reference structure" value={[reference?.id ?? AUTO]}
              onChange={([id]) => choose(references, id === AUTO ? null : id)}
              options={[{ value: AUTO, label: "Automatic",
                sub: !scan ? "Uses the reference structure for the scan's material"
                  : autoRef ? `Uses ${autoRef.material} (${detailed ? autoRef.id : "same material as the scan"})`
                  : `No ${scan.material} structure in your data; the AI method can work without one` },
                ...[...references].sort((a, b) => Number(b.material === scan?.material) - Number(a.material === scan?.material))
                  .map((d) => ({ value: d.id, label: d.material ?? d.id, group: "Choose one",
                    sub: [detailed || !d.material ? d.id : null, d.material === scan?.material ? "same material as the scan" : null]
                      .filter(Boolean).join(" · ") || undefined }))]} />
          </div>}
          {measured.length === 0 && <p className="text-[11.5px] text-muted">No measured scans yet. Add one under Data.</p>}
        </div>
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
          <Picker label="Method" multiple value={engines} onChange={(v) => setEngines(v as Engine[])}
            options={(engineList.data ?? []).map((e): PickerOption => ({ value: e.name, label: e.label, sub: e.about,
              disabled: !e.available,
              extra: !e.available && e.tool ? <button className="mt-0.5 shrink-0 whitespace-nowrap text-[11.5px] text-accent hover:underline"
                onClick={(ev) => { ev.stopPropagation(); go("software"); }}>
                {e.install?.status === "installing" ? "Installing…" : "Set up →"}</button> : undefined }))} />
          {engines.length > 1 && <p className="text-[11px] text-muted">Each method runs separately and the results are shown side by side.</p>}
          {(engineList.data ?? []).some((e) => !e.available) && <p className="text-[11px] text-muted">
            Greyed-out methods need a program installed on this computer.{" "}
            <button className="text-accent hover:underline" onClick={() => go("software")}>Open Software</button></p>}
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

function scanOption(d: DatasetNode): PickerOption {
  const files = d.files.filter((f) => f.startsWith("raw/")).length;
  // two scans of one material differ only by name, so the dataset name always shows
  return { value: d.id, label: d.material ? `${d.material} · ${d.id}` : d.id,
    sub: [instrumentLine(d.instrument), `${files} file${files === 1 ? "" : "s"}`].filter(Boolean).join(" · ") };
}
