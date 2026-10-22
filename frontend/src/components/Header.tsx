import { useQuery } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { DetailToggle, useDetailed } from "./prefs";
import { Button, cn } from "./ui";

const SERVICE: Record<string, { label: string; down: string }> = {
  neon: { label: "Database", down: "Saved analyses can't be loaded right now." },
  s3: { label: "File storage", down: "Data files can't be read right now." },
  qdrant: { label: "Search", down: "The assistant can't search earlier reports right now." },
  daytona: { label: "Analysis computer", down: "New analyses can't start right now." },
  anthropic: { label: "AI model", down: "The AI agents and the assistant are unavailable." },
};

function Mark() {
  return <img src="/logo-mark.png" alt="" aria-hidden className="h-6 w-auto" draggable={false} />;
}

export function Header({ title, assistantOpen, onToggleAssistant }: { title: string; assistantOpen: boolean; onToggleAssistant: () => void }) {
  const detailed = useDetailed();
  const ping = useQuery({ queryKey: ["ping"], queryFn: api.ping });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 60_000 });
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const services = Object.entries(health.data?.services ?? {});
  const down = services.filter(([, s]) => !s.ok);
  const mode = ping.data?.mode ?? "…";
  const status = health.isLoading ? "Checking…"
    : !down.length ? (detailed ? "All services operational" : "Ready")
    : down.length === 1 ? (SERVICE[down[0][0]]?.down ?? `${down[0][0]} unavailable`)
    : `${down.length} services unavailable`;

  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-line bg-surface px-4">
      <a href="/" title="CoRefine home" className="flex items-center gap-2.5 rounded hover:opacity-80">
        <Mark />
        <span className="text-[15px] font-semibold tracking-tight">CoRefine</span>
      </a>
      <span className="h-5 w-px bg-line" />
      <h1 className="text-[13.5px] font-medium text-ink">{title}</h1>
      <div className="ml-auto flex items-center gap-3">
        <DetailToggle />
        {detailed && <span className={cn("rounded border px-1.5 py-px font-mono text-[11px] uppercase tracking-wide",
          mode === "cloud" ? "border-accent/30 text-accent" : "border-line-strong text-muted")} title="Where the app's services run">{mode}</span>}
        <div className="relative" ref={ref}>
          <button onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-2 rounded-md px-2 py-1 text-xs text-ink-2 hover:bg-subtle">
            <span className={cn("size-2 rounded-full", health.isLoading ? "bg-faint" : down.length ? "bg-warn" : "bg-ok")} />
            {status}
          </button>
          {open && (
            <div className="absolute right-0 top-9 z-40 w-80 rounded-lg border border-line bg-surface p-1 shadow-lg">
              {services.map(([k, s]) => (
                <div key={k} className="flex items-start gap-2.5 rounded px-2.5 py-2">
                  <span className={cn("mt-1 size-2 shrink-0 rounded-full", s.ok ? "bg-ok" : "bg-warn")} />
                  <div className="min-w-0">
                    <div className="text-xs font-medium">{SERVICE[k]?.label ?? k}</div>
                    <div className={cn("text-[11px] text-muted", detailed ? "break-words" : "truncate")} title={s.detail}>
                      {s.ok ? (detailed ? s.detail : "Working") : (detailed ? s.detail : SERVICE[k]?.down ?? s.detail)}</div>
                  </div>
                </div>
              ))}
              <button onClick={() => health.refetch()} className="mt-1 w-full rounded border-t border-line px-2.5 py-2 text-left text-xs text-accent hover:bg-subtle">
                Check again
              </button>
            </div>
          )}
        </div>
        <Button size="sm" variant={assistantOpen ? "secondary" : "primary"} onClick={onToggleAssistant} aria-pressed={assistantOpen}>
          <Bot size={14} /> {assistantOpen ? "Hide assistant" : "Ask the assistant"}</Button>
      </div>
    </header>
  );
}
