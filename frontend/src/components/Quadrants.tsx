import { Maximize2, Minimize2 } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Button, cn } from "./ui";

export interface Pane { key: string; title: string; body: ReactNode; extra?: ReactNode }

/** Four panes in a 2×2 grid (top-left, top-right, bottom-left, bottom-right); any pane can be maximised. */
export function Quadrants({ panes }: { panes: Pane[] }) {
  const [max, setMax] = useState<string | null>(null);
  return (
    <div className={cn("grid min-h-0 flex-1 gap-3 p-3", max ? "grid-cols-1 grid-rows-1"
      : panes.length <= 4 ? "grid-cols-2 grid-rows-2" : "auto-rows-[minmax(320px,1fr)] grid-cols-2 overflow-auto")}>
      {panes.filter((p) => !max || p.key === max).map((p) => (
        <section key={p.key} className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-[0_1px_2px_rgba(16,24,40,.04)]">
          <header className="flex h-9 shrink-0 items-center gap-2 border-b border-line pl-3 pr-1.5">
            <h2 className="text-xs font-semibold">{p.title}</h2>
            <div className="ml-auto flex items-center">{p.extra}
              <Button size="sm" variant="ghost" onClick={() => setMax(max ? null : p.key)} title={max ? "Restore" : "Maximise"}
                aria-label={max ? "Restore" : "Maximise"}>{max ? <Minimize2 size={13} /> : <Maximize2 size={13} />}</Button>
            </div>
          </header>
          <div className="min-h-0 flex-1 overflow-auto">{p.body}</div>
        </section>
      ))}
    </div>
  );
}
