import { Bot, Code2, Cpu, Database, Scale } from "lucide-react";
import type { ReactNode } from "react";
import { Status, cn } from "./ui";

/** Vertical step flow: each node says who acted (data, a language model, plain code, a scientific program, or the
 *  result), what happened and how it ended. Used for the reasoning trail of experiment and theory pipelines. */
export type Actor = "input" | "llm" | "code" | "program" | "result";
export const ACTOR: Record<Actor, { icon: typeof Bot; ring: string; label: string }> = {
  input: { icon: Database, ring: "border-line-strong text-muted", label: "data" },
  llm: { icon: Bot, ring: "border-accent text-accent", label: "language model" },
  code: { icon: Code2, ring: "border-ink-2 text-ink-2", label: "code" },
  program: { icon: Cpu, ring: "border-[#c2410c] text-[#c2410c]", label: "scientific program" },
  result: { icon: Scale, ring: "border-ok text-ok", label: "result" },
};
export function Legend() {
  return (
    <div className="flex flex-wrap gap-3 text-[11.5px] text-muted">
      {(Object.keys(ACTOR) as Actor[]).map((a) => { const A = ACTOR[a]; return (
        <span key={a} className="inline-flex items-center gap-1.5"><span className={cn("flex size-5 items-center justify-center rounded-full border-2 bg-surface", A.ring)}>
          <A.icon size={11} /></span>{A.label}</span>); })}
    </div>
  );
}

export function Node({ actor, who, title, status, children, last }: { actor: Actor; who: string; title: ReactNode; status?: string;
  children?: ReactNode; last?: boolean }) {
  const A = ACTOR[actor];
  return (
    <div className="relative flex gap-3 pb-4">
      {!last && <span className="absolute left-[13px] top-7 bottom-0 w-px bg-line-strong" />}
      <span className={cn("z-10 flex size-7 shrink-0 items-center justify-center rounded-full border-2 bg-surface", A.ring)}><A.icon size={13} /></span>
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-medium">{title}</span>
          <span className="text-[11px] text-faint">{who}</span>
          {status && <span className="ml-auto"><Status status={status} /></span>}
        </div>
        {children && <div className="mt-1 space-y-1 text-[12.5px] leading-5 text-ink-2">{children}</div>}
      </div>
    </div>
  );
}
