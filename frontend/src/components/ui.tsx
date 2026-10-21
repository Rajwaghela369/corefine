// Small shadcn/ui-style primitives (hand-written with Tailwind; no generator run).
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { StepStatus } from "../api/client";

export function cn(...c: (string | false | null | undefined)[]) { return c.filter(Boolean).join(" "); }

export function Button({ variant = "default", className, ...p }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "outline" | "ghost" }) {
  return <button {...p} className={cn(
    "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition disabled:opacity-50",
    variant === "default" && "bg-ink text-white hover:bg-ink/90",
    variant === "outline" && "border border-line bg-white hover:bg-panel",
    variant === "ghost" && "hover:bg-panel", className)} />;
}

export function Badge({ children, tone = "neutral", className }:
  { children: ReactNode; tone?: "neutral" | "good" | "bad" | "warn" | "info"; className?: string }) {
  return <span className={cn("inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium",
    tone === "neutral" && "bg-panel text-muted border border-line",
    tone === "good" && "bg-emerald-50 text-emerald-700 border border-emerald-200",
    tone === "bad" && "bg-red-50 text-red-700 border border-red-200",
    tone === "warn" && "bg-amber-50 text-amber-800 border border-amber-200",
    tone === "info" && "bg-sky-50 text-sky-700 border border-sky-200", className)}>{children}</span>;
}

export const STATUS_TONE: Record<string, "neutral" | "good" | "bad" | "warn" | "info"> = {
  pending: "neutral", queued: "neutral", planning: "info", running: "info", analysing: "info",
  retrying: "warn", done: "good", failed: "bad",
};

export const STEP_COLOURS: Record<StepStatus, string> = {
  pending: "#e5e7eb", running: "#bae6fd", retrying: "#fde68a", done: "#bbf7d0", failed: "#fecaca",
};

export function Section({ title, right, children, className }:
  { title: string; right?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={cn("flex min-h-0 flex-col", className)}>
    <header className="flex items-center justify-between border-b border-line px-3 py-2">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h2>{right}
    </header>
    <div className="min-h-0 flex-1 overflow-auto">{children}</div>
  </section>;
}

export function fmt(v: number | string | null | undefined, digits = 6): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (Number.isInteger(v)) return String(v);
  return Math.abs(v) < 1e-3 && v !== 0 ? v.toExponential(2) : v.toFixed(digits).replace(/0+$/, "").replace(/\.$/, "");
}
