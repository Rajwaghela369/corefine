import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, CircleDashed, Loader2, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { dft, type DftTool, type DftTools } from "../api/client";
import { useDetailed } from "../components/prefs";
import { Button, Tag, cn } from "../components/ui";

/** A program as a researcher thinks of it: one name, possibly several downloads (the code plus its data). */
interface Program { id: string; label: string; about: string; parts: string[]; code?: string }

const ANALYSE: Program[] = [
  { id: "gsas2", label: "GSAS-II", parts: ["gsas2"],
    about: "Rietveld refinement from Argonne's Advanced Photon Source. Adds “GSAS-II” as a method under Analyse." },
  { id: "maud", label: "MAUD", parts: ["maud"],
    about: "Rietveld refinement with crystallite size and strain (Lutterotti). Adds “MAUD” as a method under Analyse." },
];
const SIMULATE: Program[] = [
  { id: "espresso", code: "espresso", label: "Quantum ESPRESSO", parts: [],
    about: "Plane-wave DFT with pseudopotentials. Comes with the SSSP pseudopotential library for PBE." },
  { id: "abinit", code: "abinit", label: "ABINIT", parts: [],
    about: "Plane-wave DFT. Comes with the PseudoDojo pseudopotential table for PBE." },
  { id: "gpaw", code: "gpaw", label: "GPAW", parts: [],
    about: "Real-space and plane-wave DFT in Python, with its own PAW setups." },
];
const XC_LABEL: Record<string, string> = { PBEsol: "PBEsol", LDA: "LDA" };

type State = "ready" | "installing" | "failed" | "missing";

function stateOf(parts: DftTool[]): State {
  if (parts.some((p) => p.status === "installing")) return "installing";
  if (parts.length && parts.every((p) => p.status === "installed")) return "ready";
  if (parts.some((p) => p.status === "failed")) return "failed";
  return "missing";
}

/** Every program CoRefine can run on this computer, installed from one place. Nothing needs admin rights. */
export function SoftwareView() {
  const qc = useQueryClient();
  const tools = useQuery({ queryKey: ["dft-tools"], queryFn: dft.tools,
    refetchInterval: (q) => (q.state.data?.tools.some((t) => t.status === "installing") ? 2000 : false) });
  const t = tools.data;
  const installing = (t?.tools ?? []).some((x) => x.status === "installing");
  const was = useRef(false);
  useEffect(() => {  // an install finished: the Analyse methods and Simulate codes change with it
    if (was.current && !installing) ["engines", "dft-config", "dft-targets"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    was.current = installing;
  }, [installing, qc]);

  if (!t) return <div className="p-6 text-[13px] text-muted">{tools.isError ? String(tools.error) : "Checking this computer…"}</div>;
  const simulate = SIMULATE.map((p) => ({ ...p, parts: t.code_tools[p.code!] ?? [] }));
  const addons: Program[] = SIMULATE.flatMap((p) => Object.entries(t.functional_tools[p.code!] ?? {}).map(([xc, parts]) => ({
    id: `${p.id}-${xc}`, label: `${p.label}: ${XC_LABEL[xc] ?? xc} pseudopotentials`, parts,
    about: `Needed to run ${p.label} with the ${xc} functional.` })));
  const all = [...ANALYSE, ...simulate];
  const ready = all.filter((p) => stateOf(p.parts.map((n) => byName(t, n)).filter(Boolean) as DftTool[]) === "ready").length;

  return (
    <div className="h-full overflow-auto bg-canvas">
      <div className="mx-auto max-w-4xl space-y-6 px-6 py-8">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Software on this computer</h1>
          <p className="mt-1 max-w-2xl text-[13.5px] leading-6 text-muted">
            Scientific programs run here, on your computer; the AI, your data and the results stay in the cloud services.
            Each program downloads from its official source, is checked against its published checksum, and installs into
            CoRefine's own folder. No administrator rights are needed and nothing else on the computer changes.</p>
          <p className="mt-2 text-[12.5px] text-ink-2"><b>{ready}</b> of {all.length} programs ready</p>
        </div>
        <Group title="For analysing scans" programs={ANALYSE} t={t} />
        <Group title="For simulating materials" programs={simulate} t={t} />
        <Group title="Optional add-ons" programs={addons} t={t} />
        <section>
          <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-faint">Cannot be installed by CoRefine</h2>
          <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
            {Object.entries(t.not_installable).map(([code, why]) => (
              <li key={code} className="px-4 py-2.5 text-[12.5px]">
                <span className="font-medium capitalize">{code}</span>
                {t.local[code] ? <span className="ml-2 text-ok">found on this computer</span> : null}
                <p className="mt-0.5 text-[12px] leading-5 text-muted">{why}</p>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

const byName = (t: DftTools, n: string) => t.tools.find((x) => x.name === n);

function Group({ title, programs, t }: { title: string; programs: Program[]; t: DftTools }) {
  if (!programs.length) return null;
  return (
    <section>
      <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-faint">{title}</h2>
      <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
        {programs.map((p) => <ProgramRow key={p.id} p={p} t={t} />)}
      </ul>
    </section>
  );
}

function ProgramRow({ p, t }: { p: Program; t: DftTools }) {
  const detailed = useDetailed();
  const qc = useQueryClient();
  const [showLog, setShowLog] = useState(false);
  const parts = p.parts.map((n) => byName(t, n)).filter(Boolean) as DftTool[];
  const state = stateOf(parts);
  const external = p.code && state !== "ready" ? t.local[p.code] : undefined;  // e.g. pw.x already on PATH
  const active = parts.find((x) => x.status === "installing");
  const failed = parts.find((x) => x.status === "failed");
  const install = useMutation({
    mutationFn: async () => { for (const x of parts) if (x.status !== "installed" && x.status !== "installing") await dft.installTool(x.name); },
    onSettled: () => qc.invalidateQueries({ queryKey: ["dft-tools"] }),
  });
  const logFor = (active ?? failed ?? parts[0])?.name;
  const log = useQuery({ queryKey: ["tool-log", logFor], queryFn: () => dft.toolLog(logFor!), enabled: showLog && !!logFor,
    refetchInterval: state === "installing" ? 2000 : false });

  const Icon = state === "ready" ? CheckCircle2 : state === "installing" ? Loader2 : state === "failed" ? XCircle : CircleDashed;
  return (
    <li className="px-4 py-3">
      <div className="flex items-start gap-3">
        <Icon size={18} className={cn("mt-0.5 shrink-0", state === "ready" ? "text-ok" : state === "installing" ? "animate-spin text-accent"
          : state === "failed" ? "text-bad" : "text-faint")} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13.5px] font-semibold">{p.label}</span>
            {state === "ready" && <Tag tone="ok">Ready</Tag>}
            {state === "installing" && <Tag tone="run">Installing</Tag>}
            {state === "failed" && <Tag tone="bad">Install failed</Tag>}
            {state === "missing" && !external && <Tag>Not installed</Tag>}
            {external && <Tag tone="ok" title={external}>Found on this computer</Tag>}
          </div>
          <p className="mt-0.5 text-[12.5px] leading-5 text-ink-2">{p.about}</p>
          {active && <p className="mt-1 text-[12px] text-accent">{active.message || "working"}…</p>}
          {failed && !active && <p className="mt-1 text-[12px] leading-5 text-bad">{failed.message}</p>}
          {state === "ready" && <p className="mt-1 text-[11.5px] text-muted">{parts.map((x) => x.version).filter(Boolean).join(" · ")}</p>}
          {(detailed || state === "missing") && <p className="mt-1 text-[11.5px] leading-4 text-faint">
            {parts.map((x) => `${x.label}: ${x.size}, ${x.license}`).join(" · ")}</p>}
          {detailed && <p className="mt-0.5 text-[11px] leading-4 text-faint">{parts.map((x) => x.source).join(" · ")}</p>}
          {logFor && (state !== "missing" || detailed) && <button onClick={() => setShowLog((v) => !v)}
            className="mt-1.5 flex items-center gap-0.5 text-[11.5px] text-accent hover:underline">
            <ChevronRight size={12} className={cn("transition", showLog && "rotate-90")} />{showLog ? "Hide" : "Show"} install log</button>}
          {showLog && <pre className="mt-1.5 max-h-56 overflow-auto rounded-md bg-[#0f1420] p-2.5 font-mono text-[10.5px] leading-[1.45] text-[#d6deeb]">
            {log.data?.log || "No log yet."}</pre>}
        </div>
        {state !== "ready" && state !== "installing" && <Button variant={state === "failed" ? "secondary" : "primary"} size="sm"
          className="shrink-0" disabled={install.isPending} onClick={() => install.mutate()}>
          {install.isPending ? "Starting…" : state === "failed" ? "Retry" : "Install"}</Button>}
      </div>
    </li>
  );
}
