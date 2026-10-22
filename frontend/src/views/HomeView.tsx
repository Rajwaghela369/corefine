import { useQuery } from "@tanstack/react-query";
import { Atom, Bot, Database, FlaskConical, GitCompareArrows, type LucideIcon } from "lucide-react";
import { api } from "../api/client";
import { runTitle } from "../components/labels";
import { Status, clock } from "../components/ui";
import { RunsList, useRuns } from "../panels/RunsList";
import type { View } from "../components/Sidebar";

const TASKS: { view: View; icon: LucideIcon; title: string; text: string }[] = [
  { view: "analyse", icon: FlaskConical, title: "Analyse a measured scan",
    text: "Get a lattice parameter from an X-ray diffraction scan, checked against a certified value." },
  { view: "simulate", icon: Atom, title: "Simulate a material",
    text: "Calculate a material's electronic structure (DFT) with several programs and compare what they predict." },
  { view: "compare", icon: GitCompareArrows, title: "Compare theory and experiment",
    text: "See side by side how the measurement and the simulations reached their answers for one material." },
  { view: "data", icon: Database, title: "Manage your data",
    text: "Look at scans and structures, add new files, and check that each dataset is well documented." },
];

export function HomeView({ onGo, onOpenRun, onAsk }: { onGo: (v: View) => void; onOpenRun: (id: string) => void; onAsk: () => void }) {
  const runs = useRuns();
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const recent = (runs.data ?? []).filter((r) => !r.archived).slice(0, 5);
  const nData = (datasets.data ?? []).filter((d) => d.valid).length;
  return (
    <div className="h-full overflow-auto bg-canvas">
      <div className="mx-auto max-w-5xl space-y-6 px-6 py-8">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">What would you like to do?</h1>
          <p className="mt-1 max-w-2xl text-[13.5px] leading-6 text-muted">
            CoRefine turns materials measurements and simulations into checked, explained results. AI agents do the
            analysis work; plain code checks every number they report against your data.</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {TASKS.map(({ view, icon: Icon, title, text }) => (
            <button key={view} onClick={() => onGo(view)}
              className="group flex gap-3 rounded-lg border border-line bg-surface p-4 text-left transition-colors hover:border-accent">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent"><Icon size={18} /></span>
              <span>
                <span className="block text-[14px] font-semibold group-hover:text-accent">{title}</span>
                <span className="mt-0.5 block text-[12.5px] leading-5 text-ink-2">{text}</span>
              </span>
            </button>
          ))}
        </div>
        <button onClick={onAsk} className="flex w-full items-center gap-3 rounded-lg border border-dashed border-line-strong bg-surface px-4 py-3 text-left hover:border-accent">
          <Bot size={18} className="text-accent" />
          <span className="text-[13px]"><span className="font-semibold">Not sure where to start?</span>
            <span className="text-ink-2"> Ask the assistant about your {nData || ""} datasets or past results.</span></span>
        </button>
        {recent.length > 0 && <section>
          <div className="mb-2 flex items-baseline justify-between">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-faint">Recent analyses</h2>
            <button onClick={() => onGo("history")} className="text-[12px] text-accent hover:underline">See all</button>
          </div>
          <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
            {recent.map((r) => (
              <li key={r.id}>
                <button onClick={() => onOpenRun(r.id)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-subtle">
                  <span className="min-w-0 flex-1 truncate text-[13px]">{runTitle(r)}</span>
                  {r.headline && <span className="tabular shrink-0 font-mono text-[12px] text-ink-2">a = {r.headline.a_refined.toFixed(6)} Å</span>}
                  <span className="w-28 shrink-0 text-right text-[11.5px] text-muted">{clock(r.started_at)}</span>
                  <span className="w-24 shrink-0 text-right"><Status status={r.status} /></span>
                </button>
              </li>
            ))}
          </ul>
        </section>}
      </div>
    </div>
  );
}

export function HistoryView({ onOpenRun }: { onOpenRun: (id: string) => void }) {
  return (
    <div className="h-full overflow-auto bg-canvas">
      <div className="mx-auto max-w-4xl px-6 py-6">
        <h1 className="text-lg font-semibold tracking-tight">All analyses</h1>
        <p className="mb-4 mt-0.5 text-[13px] text-muted">Every analysis, newest first. Archive the ones you no longer need; nothing is deleted.</p>
        <div className="overflow-hidden rounded-lg border border-line bg-surface">
          <RunsList selected={null} onSelect={onOpenRun} searchable />
        </div>
      </div>
    </div>
  );
}
