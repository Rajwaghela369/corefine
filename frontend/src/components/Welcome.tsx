import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export interface Step { icon: LucideIcon; title: string; text: string }

/** Start page for an empty workspace: what this area does, in steps, plus whatever can be opened right away. */
export function Welcome({ title, intro, steps, children }: { title: string; intro: string; steps: Step[]; children?: ReactNode }) {
  return (
    <div className="h-full overflow-auto bg-canvas">
      <div className="mx-auto max-w-4xl space-y-5 px-6 py-8">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 max-w-2xl text-[13.5px] leading-6 text-muted">{intro}</p>
        </div>
        <ol className="grid gap-3 md:grid-cols-3">
          {steps.map((s, i) => {
            const Icon = s.icon;
            return (
              <li key={s.title} className="rounded-lg border border-line bg-surface p-4">
                <div className="mb-2 flex items-center gap-2">
                  <span className="flex size-6 items-center justify-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent">{i + 1}</span>
                  <Icon size={16} className="text-ink-2" strokeWidth={1.8} />
                  <span className="text-[13px] font-semibold">{s.title}</span>
                </div>
                <p className="text-[12.5px] leading-5 text-ink-2">{s.text}</p>
              </li>
            );
          })}
        </ol>
        {children}
      </div>
    </div>
  );
}

export function WelcomeSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-faint">{title}</h2>
      {children}
    </section>
  );
}
