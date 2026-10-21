import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { cn } from "./ui";

const SERVICE_LABEL: Record<string, string> = {
  neon: "Database", s3: "Object storage", qdrant: "Search index", daytona: "Sandbox", anthropic: "Language model", langfuse: "Tracing",
};

function Mark() {
  // A diamond-cubic motif: the structure the first experiment measures.
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden className="text-accent">
      <rect x="3" y="3" width="18" height="18" rx="4" fill="currentColor" />
      <path d="M7.5 7.5h9v9h-9z" fill="none" stroke="white" strokeWidth="1.4" />
      <circle cx="7.5" cy="7.5" r="1.6" fill="white" /><circle cx="16.5" cy="16.5" r="1.6" fill="white" />
      <circle cx="16.5" cy="7.5" r="1.6" fill="white" /><circle cx="7.5" cy="16.5" r="1.6" fill="white" />
      <circle cx="12" cy="12" r="1.6" fill="white" />
    </svg>
  );
}

export function Header() {
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
  const down = services.filter(([, s]) => !s.ok).length;
  const mode = ping.data?.mode ?? "…";

  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-line bg-surface px-4">
      <div className="flex items-center gap-2.5">
        <Mark />
        <span className="text-[15px] font-semibold tracking-tight">CoRefine</span>
      </div>
      <span className="h-5 w-px bg-line" />
      <nav className="flex items-center gap-1 text-[13px] text-muted">
        <span>Workspace</span><span className="text-faint">/</span>
        <span className="font-medium text-ink">Powder diffraction · Si lattice parameter</span>
      </nav>
      <div className="ml-auto flex items-center gap-3">
        <span className={cn("rounded border px-1.5 py-px font-mono text-[11px] uppercase tracking-wide",
          mode === "cloud" ? "border-accent/30 text-accent" : "border-line-strong text-muted")}>{mode}</span>
        <div className="relative" ref={ref}>
          <button onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-2 rounded-md px-2 py-1 text-xs text-ink-2 hover:bg-subtle">
            <span className={cn("size-2 rounded-full", health.isLoading ? "bg-faint" : down ? "bg-warn" : "bg-ok")} />
            {health.isLoading ? "Checking services" : down ? `${down} of ${services.length} services unavailable` : "All services operational"}
          </button>
          {open && (
            <div className="absolute right-0 top-9 z-40 w-80 rounded-lg border border-line bg-surface p-1 shadow-lg">
              {services.map(([k, s]) => (
                <div key={k} className="flex items-start gap-2.5 rounded px-2.5 py-2">
                  <span className={cn("mt-1 size-2 shrink-0 rounded-full", s.ok ? "bg-ok" : "bg-warn")} />
                  <div className="min-w-0">
                    <div className="text-xs font-medium">{SERVICE_LABEL[k] ?? k}</div>
                    <div className="truncate text-[11px] text-muted" title={s.detail}>{s.detail}</div>
                  </div>
                </div>
              ))}
              <button onClick={() => health.refetch()} className="mt-1 w-full rounded border-t border-line px-2.5 py-2 text-left text-xs text-accent hover:bg-subtle">
                Re-check
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
