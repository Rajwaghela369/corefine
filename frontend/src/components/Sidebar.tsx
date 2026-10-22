import { Atom, Database, FlaskConical, History, Home, Package } from "lucide-react";
import { cn } from "./ui";

export type View = "home" | "data" | "analyse" | "simulate" | "history" | "software";

export const VIEWS: { id: View; label: string; title: string; icon: typeof Database; hint: string }[] = [
  { id: "home", label: "Home", title: "Home", icon: Home, hint: "Start here" },
  { id: "data", label: "Data", title: "Your data", icon: Database, hint: "Scans, structures, uploads and documentation" },
  { id: "analyse", label: "Analyse", title: "Analyse a measured scan", icon: FlaskConical, hint: "Analyse an X-ray diffraction scan (experiment)" },
  { id: "simulate", label: "Simulate", title: "Simulate a material", icon: Atom, hint: "Calculate a material's properties (DFT theory)" },
  { id: "history", label: "History", title: "All analyses", icon: History, hint: "Every analysis you have run" },
  { id: "software", label: "Software", title: "Software", icon: Package, hint: "Install the programs that run on this computer" },
];

export function Sidebar({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <nav className="flex w-[76px] shrink-0 flex-col items-center gap-1 border-r border-line bg-surface py-3" aria-label="Main">
      {VIEWS.map(({ id, label, icon: Icon, hint }) => (
        <button key={id} onClick={() => onChange(id)} title={hint} aria-current={view === id ? "page" : undefined}
          className={cn("flex w-[64px] flex-col items-center gap-1 rounded-md py-2 text-[11px] font-medium transition-colors",
            view === id ? "bg-accent-soft text-accent" : "text-muted hover:bg-subtle hover:text-ink")}>
          <Icon size={18} strokeWidth={1.75} />
          {label}
        </button>
      ))}
    </nav>
  );
}
