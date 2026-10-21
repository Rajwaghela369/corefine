import type { LucideIcon } from "lucide-react";
import { type ReactNode, useState } from "react";
import { cn } from "./ui";

export interface Section { key: string; label: string; icon: LucideIcon; body: ReactNode; badge?: ReactNode; extra?: ReactNode }

/** One focused section at a time: a tab bar and a single full-height panel (instead of many panes at once). */
export function Sections({ sections, initial }: { sections: Section[]; initial?: string }) {
  const [active, setActive] = useState(initial && sections.some((s) => s.key === initial) ? initial : sections[0]?.key);
  const cur = sections.find((s) => s.key === active) ?? sections[0];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <nav className="flex shrink-0 items-center gap-0.5 overflow-x-auto border-b border-line bg-surface px-3">
        {sections.map((s) => {
          const Icon = s.icon;
          return (
            <button key={s.key} onClick={() => setActive(s.key)}
              className={cn("-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-[13px] transition-colors",
                s.key === cur?.key ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink")}>
              <Icon size={14} strokeWidth={1.8} />{s.label}{s.badge}
            </button>
          );
        })}
        {cur?.extra && <div className="ml-auto flex items-center gap-1 py-1">{cur.extra}</div>}
      </nav>
      <div className="min-h-0 flex-1 overflow-auto bg-canvas">
        <div className="mx-auto h-full max-w-6xl p-4">
          <div className="h-full min-h-[420px] overflow-hidden rounded-lg border border-line bg-surface shadow-[0_1px_2px_rgba(16,24,40,.04)]">{cur?.body}</div>
        </div>
      </div>
    </div>
  );
}

export function Dot({ tone }: { tone: "run" | "ok" | "bad" | "warn" }) {
  const c = { run: "bg-run animate-pulse", ok: "bg-ok", bad: "bg-bad", warn: "bg-warn" }[tone];
  return <span className={cn("ml-0.5 size-1.5 rounded-full", c)} />;
}
