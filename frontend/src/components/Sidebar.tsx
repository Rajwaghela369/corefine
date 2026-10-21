import { Database, FlaskConical } from "lucide-react";
import { cn } from "./ui";

export type View = "storage" | "lab";

const ITEMS: { id: View; label: string; icon: typeof Database; hint: string }[] = [
  { id: "storage", label: "Storage", icon: Database, hint: "Datasets, uploads and manifests" },
  { id: "lab", label: "Lab", icon: FlaskConical, hint: "Run and review analyses" },
];

export function Sidebar({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <nav className="flex w-[72px] shrink-0 flex-col items-center gap-1 border-r border-line bg-surface py-3" aria-label="Main">
      {ITEMS.map(({ id, label, icon: Icon, hint }) => (
        <button key={id} onClick={() => onChange(id)} title={hint} aria-current={view === id ? "page" : undefined}
          className={cn("flex w-[60px] flex-col items-center gap-1 rounded-md py-2 text-[11px] font-medium transition-colors",
            view === id ? "bg-accent-soft text-accent" : "text-muted hover:bg-subtle hover:text-ink")}>
          <Icon size={18} strokeWidth={1.75} />
          {label}
        </button>
      ))}
    </nav>
  );
}
