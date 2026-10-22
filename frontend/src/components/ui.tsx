// Small design-system primitives (Tailwind, shadcn/ui-style API; hand-written).
import { X } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useEffect } from "react";

export function cn(...c: (string | false | null | undefined)[]) { return c.filter(Boolean).join(" "); }

type Variant = "primary" | "secondary" | "ghost";
export function Button({ variant = "secondary", size = "md", className, ...p }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return <button {...p} className={cn(
    "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors",
    "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-45",
    size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3 text-[13px]",
    variant === "primary" && "bg-accent text-white shadow-sm hover:bg-[#1a43b3]",
    variant === "secondary" && "border border-line-strong bg-surface text-ink shadow-[0_1px_0_rgba(16,24,40,.04)] hover:bg-subtle",
    variant === "ghost" && "text-ink-2 hover:bg-subtle", className)} />;
}

export type Tone = "neutral" | "ok" | "warn" | "bad" | "run";
const TONE_TEXT: Record<Tone, string> = { neutral: "text-muted", ok: "text-ok", warn: "text-warn", bad: "text-bad", run: "text-run" };
const TONE_DOT: Record<Tone, string> = { neutral: "bg-faint", ok: "bg-ok", warn: "bg-warn", bad: "bg-bad", run: "bg-run" };
const TONE_SOFT: Record<Tone, string> = { neutral: "bg-subtle", ok: "bg-ok-soft", warn: "bg-warn-soft", bad: "bg-bad-soft", run: "bg-accent-soft" };

export const STATUS_TONE: Record<string, Tone> = {
  pending: "neutral", queued: "neutral", planning: "run", running: "run", analysing: "run",
  retrying: "warn", done: "ok", failed: "bad",
};
export const STATUS_LABEL: Record<string, string> = {
  pending: "Pending", queued: "Queued", planning: "Planning", running: "Running", analysing: "Analysing",
  retrying: "Retrying", done: "Completed", failed: "Failed",
};

export function Status({ status, className }: { status: string; className?: string }) {
  const tone = STATUS_TONE[status] ?? "neutral";
  const live = ["planning", "running", "analysing", "retrying"].includes(status);
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", TONE_TEXT[tone], className)}>
      <span className="relative flex size-1.5">
        {live && <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-60", TONE_DOT[tone])} />}
        <span className={cn("relative inline-flex size-1.5 rounded-full", TONE_DOT[tone])} />
      </span>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function Tag({ children, tone = "neutral", className, title }:
  { children: ReactNode; tone?: Tone; className?: string; title?: string }) {
  return <span title={title} className={cn("inline-flex items-center gap-1 rounded px-1.5 py-px text-[11px] font-medium",
    TONE_SOFT[tone], TONE_TEXT[tone], tone === "neutral" && "text-ink-2", className)}>{children}</span>;
}

export function PanelHeader({ title, meta, actions }: { title: string; meta?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex h-11 shrink-0 items-center justify-between border-b border-line px-4">
      <div className="flex items-baseline gap-2">
        <h2 className="text-[13px] font-semibold">{title}</h2>
        {meta && <span className="text-xs text-muted">{meta}</span>}
      </div>
      {actions && <div className="flex items-center gap-1">{actions}</div>}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-8 py-12 text-center">
      <p className="text-[13px] font-medium text-ink-2">{title}</p>
      {children && <div className="mt-1 max-w-sm text-xs leading-5 text-muted">{children}</div>}
    </div>
  );
}

export function Dialog({ title, open, onClose, children, wide }:
  { title: string; open: boolean; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-ink/25 pt-[6vh]" onMouseDown={onClose}>
      <div className={cn(wide ? "w-[900px]" : "w-[560px]", "flex max-h-[88vh] max-w-[92vw] flex-col rounded-lg border border-line bg-surface shadow-xl")}
        onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex shrink-0 items-center justify-between border-b border-line px-5 py-3">
          <h3 className="text-sm font-semibold">{title}</h3>
          <button onClick={onClose} className="rounded p-1 text-muted hover:bg-subtle" aria-label="Close"><X size={16} /></button>
        </div>
        <div className="min-h-0 overflow-auto p-5">{children}</div>
      </div>
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-ink-2">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls = "h-8 w-full rounded-md border border-line-strong bg-surface px-2.5 text-[13px] outline-none " +
  "placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/15";

/** Numbers as scientists read them: up to 7 significant digits, no float noise. */
export function num(v: unknown, sig = 7): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") {
    const n = Number(v);
    return Number.isFinite(n) && v.trim() !== "" ? num(n, sig) : v.replace(/^"|"$/g, "");
  }
  if (typeof v !== "number" || !Number.isFinite(v)) return String(v);
  if (Number.isInteger(v)) return String(v);
  if (Math.abs(v) < 1e-6) return v.toExponential(2);
  return String(Number(v.toPrecision(sig)));
}

export function fixed(v: number | null | undefined, d = 6): string {
  return v === null || v === undefined ? "—" : v.toFixed(d);
}

// the database stores UTC without a zone suffix; read it as UTC, not local time
const utc = (t: string) => Date.parse(t.endsWith("Z") || t.includes("+") ? t : t + "Z");

export function duration(a?: string | null, b?: string | null): string {
  if (!a) return "—";
  const s = Math.max(0, ((b ? utc(b) : Date.now()) - utc(a)) / 1000);
  return s < 60 ? `${s.toFixed(0)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

export function clock(t?: string | null): string {
  if (!t) return "—";
  const d = new Date(t.endsWith("Z") || t.includes("+") ? t : t + "Z");
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
