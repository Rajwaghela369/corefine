import type { LucideIcon } from "lucide-react";
import { type ReactNode, useState } from "react";
import { cn } from "./ui";

/** fill: the body is exactly one screen tall and scrolls itself (a live timeline that follows the newest step);
 *  otherwise it is as tall as its content and the page scrolls. */
export interface Section { key: string; label: string; icon: LucideIcon; body: ReactNode; badge?: ReactNode; extra?: ReactNode; fill?: boolean }

const NAV_H = "2.75rem";

/** One focused section at a time. The whole workspace is one scroll area: the summary on top scrolls away, the tab
 *  bar stays at the top, and each section gets the full height below it (no box inside a box). */
export function Sections({ sections, initial, header }: { sections: Section[]; initial?: string; header?: ReactNode }) {
  const [active, setActive] = useState(initial && sections.some((s) => s.key === initial) ? initial : sections[0]?.key);
  const cur = sections.find((s) => s.key === active) ?? sections[0];
  return (
    <div className="@container min-h-0 flex-1 overflow-auto bg-canvas [scrollbar-gutter:stable]">
      {header}
      <nav className="sticky top-0 z-20 flex shrink-0 items-center gap-0.5 overflow-x-auto border-b border-line bg-surface px-3"
        style={{ height: NAV_H }}>
        {sections.map((s) => {
          const Icon = s.icon;
          return (
            <button key={s.key} onClick={() => setActive(s.key)} title={s.label}
              className={cn("-mb-px flex h-full shrink-0 items-center gap-1.5 border-b-2 px-3 text-[13px] transition-colors",
                s.key === cur?.key ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink")}>
              <Icon size={14} strokeWidth={1.8} /><span className="hidden @[560px]:inline">{s.label}</span>{s.badge}
            </button>
          );
        })}
        {cur?.extra && <div className="ml-auto flex items-center gap-1 py-1">{cur.extra}</div>}
      </nav>
      <div className="mx-auto max-w-6xl p-4" style={cur?.fill ? { height: `calc(100% - ${NAV_H})` } : { minHeight: `calc(100% - ${NAV_H})` }}>
        <div className={cn("rounded-lg border border-line bg-surface shadow-[0_1px_2px_rgba(16,24,40,.04)]",
          cur?.fill && "h-full overflow-hidden")}>{cur?.body}</div>
      </div>
    </div>
  );
}

export function Dot({ tone }: { tone: "run" | "ok" | "bad" | "warn" }) {
  const c = { run: "bg-run animate-pulse", ok: "bg-ok", bad: "bg-bad", warn: "bg-warn" }[tone];
  return <span className={cn("ml-0.5 size-1.5 rounded-full", c)} />;
}
