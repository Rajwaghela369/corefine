import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { cn } from "./ui";

/** Open while there is nothing to read on the right; folded to a thin bar while a result is open, so the result gets
 *  the width. The person can open or fold it at any time; opening a different result folds it again. */
export function useSidePanel(showing: string | null): [boolean, (v: boolean) => void] {
  const [collapsed, setCollapsed] = useState(!!showing);
  useEffect(() => { setCollapsed(!!showing); }, [showing]);
  return [collapsed, setCollapsed];
}

export function SidePanel({ title, collapsed, onCollapse, actions, children }: {
  title: string; collapsed: boolean; onCollapse: (v: boolean) => void; actions?: ReactNode; children: ReactNode;
}) {
  if (collapsed) {
    return (
      <div className="flex w-11 shrink-0 flex-col items-center border-r border-line bg-surface py-2">
        <button onClick={() => onCollapse(false)} title={`Show ${title.toLowerCase()}`} aria-label={`Show ${title.toLowerCase()}`}
          className="rounded p-1.5 text-muted hover:bg-subtle hover:text-ink"><PanelLeftOpen size={16} /></button>
        <button onClick={() => onCollapse(false)} className="mt-3 text-[11.5px] font-medium text-muted [writing-mode:vertical-rl] hover:text-ink">
          {title}</button>
      </div>
    );
  }
  return (
    <div className="flex w-[360px] shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b border-line px-3">
        <button onClick={() => onCollapse(true)} title="Fold this panel" aria-label="Fold this panel"
          className="rounded p-1 text-muted hover:bg-subtle hover:text-ink"><PanelLeftClose size={15} /></button>
        <h2 className="min-w-0 flex-1 truncate text-[13px] font-semibold">{title}</h2>
        {actions}
      </div>
      <div className={cn("min-h-0 flex-1 overflow-auto")}>{children}</div>
    </div>
  );
}

/** The New / list switch used in the side panels. */
export function PanelSwitch<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: [T, string][] }) {
  return (
    <div className="flex rounded-md border border-line-strong p-0.5">
      {options.map(([v, label]) => <button key={v} onClick={() => onChange(v)}
        className={cn("rounded px-2 py-0.5 text-[11.5px]", value === v ? "bg-ink font-medium text-white" : "text-muted hover:text-ink")}>
        {label}</button>)}
    </div>
  );
}
