import { useQuery } from "@tanstack/react-query";
import { Bot, ChevronDown, Code2, Cpu, Database, FlaskConical, Atom, ShieldCheck, FileText, Scale } from "lucide-react";
import { type ReactNode, useState } from "react";
import { api, dft, type ExperimentStory, type TheoryStory } from "../api/client";
import { Button, Empty, Status, Tag, cn, inputCls } from "../components/ui";

/** Reduced formula, so the cell formula Si2 and the dataset material Si are one material. */
function reduced(formula: string): string {
  const parts = [...formula.matchAll(/([A-Z][a-z]?)(\d*)/g)].map((m) => [m[1], Number(m[2] || 1)] as const);
  const gcd = (a: number, b: number): number => (b ? gcd(b, a % b) : a);
  const g = parts.reduce((acc, [, n]) => gcd(acc, n), 0) || 1;
  return parts.map(([el, n]) => el + (n / g === 1 ? "" : String(n / g))).join("");
}

export type Actor = "input" | "llm" | "code" | "program" | "result";
export const ACTOR: Record<Actor, { icon: typeof Bot; ring: string; label: string }> = {
  input: { icon: Database, ring: "border-line-strong text-muted", label: "data" },
  llm: { icon: Bot, ring: "border-accent text-accent", label: "language model" },
  code: { icon: Code2, ring: "border-ink-2 text-ink-2", label: "code" },
  program: { icon: Cpu, ring: "border-[#c2410c] text-[#c2410c]", label: "scientific program" },
  result: { icon: Scale, ring: "border-ok text-ok", label: "result" },
};
const ENGINE: Record<string, string> = { agents: "Agents", gsas2: "GSAS-II", maud: "MAUD" };
const f = (v: number | null | undefined, d = 6) => (v == null ? "—" : v.toFixed(d));

/** One material, both directions: what the experiment pipeline and the theory pipeline each did, step by step, who did
 *  it (language model, code or a scientific program), why, and what came out. Everything is read from run and set files. */
export function BridgeView({ onGo }: { onGo: (to: "analyse" | "simulate", material?: string) => void }) {
  const ds = useQuery({ queryKey: ["datasets"], queryFn: api.datasets });
  const jobs = useQuery({ queryKey: ["dft-jobs"], queryFn: dft.jobs });
  const materials = [...new Set([...(ds.data ?? []).filter((n) => n.valid && n.role === "measured_pattern" && n.material).map((n) => reduced(n.material as string)),
    ...(jobs.data ?? []).map((j) => reduced(j.formula))])].sort();
  const [material, setMaterial] = useState<string | null>(new URLSearchParams(window.location.search).get("material"));
  const [q, setQ] = useState("");
  const current = material ?? materials[0] ?? null;
  const s = useQuery({ queryKey: ["story", current], queryFn: () => dft.story(current!), enabled: !!current, refetchInterval: 5000 });
  const d = s.data;
  return (
    <div className="h-full overflow-auto bg-canvas">
      <div className="mx-auto max-w-7xl space-y-4 p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Theory ↔ Experiment</h1>
            <p className="mt-0.5 max-w-3xl text-[13px] leading-5 text-muted">
              How each side reached its answer for one material: the steps, who took them (a language model, plain code or a
              scientific program), the reasons recorded at the time, retries and fixes, and the result. Read top to bottom.</p>
          </div>
          <form className="flex flex-wrap items-center gap-1.5" onSubmit={(e) => { e.preventDefault(); if (q.trim()) setMaterial(q.trim()); }}>
            {materials.map((m) => <Button key={m} type="button" size="sm" variant={m === current ? "primary" : "ghost"} onClick={() => setMaterial(m)}>{m}</Button>)}
            <input className={cn(inputCls, "w-24 font-mono")} value={q} placeholder="formula" onChange={(e) => setQ(e.target.value)} />
          </form>
        </div>
        <Legend />
        {!current ? <Empty title="No material yet">Add a measured scan in Storage or generate a DFT set; it appears here.</Empty> : (
          <>
            <div className="grid gap-4 lg:grid-cols-2">
              <Column icon={FlaskConical} title="Experiment" sub="measured scan → refined lattice parameter"
                empty={`No analysis of a measured ${current} scan yet.`}
                cta={<Button size="sm" variant="primary" onClick={() => onGo("analyse", current)}>Analyse a {current} scan</Button>}
                initial={(d?.experiment ?? []).findIndex((e) => e.status === "done")}
                items={d?.experiment ?? []} label={(e) => `${e.run} · ${ENGINE[e.engine]}`} render={(e) => <ExperimentFlow e={e} />} />
              <Column icon={Atom} title="Theory" sub="crystal structure → DFT in every code → band gap"
                empty={`No simulation of ${current} yet.`}
                cta={<Button size="sm" variant="primary" onClick={() => onGo("simulate", current)}>Set up a {current} simulation</Button>}
                items={d?.theory ?? []} label={(t) => `${t.request.functional} · k ${t.request.kmesh.join("×")} · ${t.set.slice(4, 17)}`}
                render={(t) => <TheoryFlow t={t} />} />
            </div>
            {d && <Meet experiment={d.experiment} theory={d.theory} material={current} />}
          </>
        )}
      </div>
    </div>
  );
}

export function Legend() {
  return (
    <div className="flex flex-wrap gap-3 text-[11.5px] text-muted">
      {(Object.keys(ACTOR) as Actor[]).map((a) => { const A = ACTOR[a]; return (
        <span key={a} className="inline-flex items-center gap-1.5"><span className={cn("flex size-5 items-center justify-center rounded-full border-2 bg-surface", A.ring)}>
          <A.icon size={11} /></span>{A.label}</span>); })}
    </div>
  );
}

function Column<T>({ icon: Icon, title, sub, items, label, render, empty, cta, initial = 0 }: { icon: typeof Atom; title: string; sub: string; items: T[];
  label: (t: T) => string; render: (t: T) => ReactNode; empty: string; cta?: ReactNode; initial?: number }) {
  const [picked, setI] = useState<number | null>(null);
  const i = picked ?? Math.max(0, initial);
  const item = items[Math.min(i, items.length - 1)];
  return (
    <section className="rounded-lg border border-line bg-surface">
      <header className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <Icon size={15} className="text-ink-2" /><h2 className="text-[13px] font-semibold">{title}</h2>
        <span className="text-[11.5px] text-muted">{sub}</span>
      </header>
      {items.length > 1 && <div className="flex flex-wrap gap-1 border-b border-line px-3 py-1.5">
        {items.map((t, k) => <button key={k} onClick={() => setI(k)} className={cn("rounded px-2 py-0.5 font-mono text-[11px]",
          k === i ? "bg-ink text-white" : "text-muted hover:bg-subtle")}>{label(t)}</button>)}</div>}
      <div className="p-4">{item ? render(item) : <div className="space-y-2.5"><p className="text-[12.5px] text-muted">{empty}</p>{cta}</div>}</div>
    </section>
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

function ExperimentFlow({ e }: { e: ExperimentStory }) {
  const [open, setOpen] = useState(false);
  const agents = e.engine === "agents";
  const r = e.result;
  const measured = e.datasets.filter((x) => !x.startsWith("cod-") && !x.startsWith("mp-"));
  return (
    <div>
      <p className="mb-3 text-[12.5px] text-muted">“{e.prompt}”</p>
      <Node actor="input" who="Storage" title="Measured scan and reference structure">
        <div className="font-mono text-[11.5px]">{e.datasets.join(" · ")}</div>
        <div className="text-[11.5px] text-muted">The certified value is hidden from whoever writes the analysis; answer blocks are stripped from {measured.join(", ") || "the scan"}.</div>
      </Node>
      <Node actor={agents ? "llm" : "code"} who={agents ? "Planner · Claude" : "fixed recipe · code"} title={e.plan_title ?? "Plan"}>
        {e.plan_summary && <div>{e.plan_summary}</div>}
      </Node>
      {e.steps.map((s) => (
        <Node key={s.idx} actor={agents ? "llm" : s.name.startsWith("refine") ? "program" : "code"}
          who={agents ? "Coder · Claude → sandbox" : s.name.startsWith("refine") ? ENGINE[e.engine] : "code"}
          title={`${s.idx}. ${s.name.replaceAll("_", " ")}`} status={s.status}>
          {s.goal && <div>{s.goal}</div>}
          {s.attempts > 1 && <Tag tone="warn">{s.attempts} attempts: the code failed and was rewritten</Tag>}
          {s.error && <div className="line-clamp-2 font-mono text-[11px] text-bad">{s.error.split("\n")[0]}</div>}
        </Node>
      ))}
      <Node actor="code" who="checker · code" title="Compared with the certificate">
        {r.a_refined ? <div className="font-mono text-[12px]">a = {f(r.a_refined.value)} Å{r.a_certified && <> · certified {f(r.a_certified.value)} Å · Δ {f(r.difference_from_certified?.value)} Å</>}
          {r.c_refined && <><br />c = {f(r.c_refined.value)} Å{r.c_certified && <> · certified {f(r.c_certified.value)} · Δ {f(r.c_difference_from_certified?.value)} Å</>}</>}
          {r.Rwp && <><br />Rwp {f(r.Rwp.value, 1)} %</>}</div> : <div className="text-muted">No refined value{e.error ? `: ${e.error.split("\n")[0]}` : ""}.</div>}
        {e.classification && <Tag tone={e.classification === "agreement" ? "ok" : "warn"}>{e.classification.replaceAll("_", " ")}</Tag>}
      </Node>
      <Node actor={e.log.some((l) => l.agent === "analyst") ? "llm" : "code"} last
        who={e.log.some((l) => l.agent === "analyst") ? "Analyst · Claude" : "report · code"} title="Report">
        {e.claim ? <Tag tone={e.claim.passed ? "ok" : "bad"}><ShieldCheck size={11} /> {e.claim.checked} numbers traced to files{e.claim.passed ? "" : " · some untraced"}</Tag>
          : <span className="text-muted">{e.status === "done" ? "—" : "not written yet"}</span>}
      </Node>
      {e.log.length > 0 && <div className="mt-1 rounded-md border border-line">
        <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[12px] font-medium">
          <FileText size={13} /> What each agent noted ({e.log.length} entries)<ChevronDown size={13} className={cn("ml-auto transition", open && "rotate-180")} /></button>
        {open && <ol className="max-h-72 space-y-1 overflow-auto border-t border-line px-3 py-2 text-[11.5px]">
          {e.log.map((l, k) => <li key={k}><span className="font-mono text-faint">{l.time}</span> <span className="font-medium">{l.agent}</span> — {l.note}</li>)}</ol>}
      </div>}
    </div>
  );
}

const SOURCE: Record<string, string> = { user: "you asked", rule: "CoRefine rule", materials_project: "from Materials Project", llm: "Claude review" };

function TheoryFlow({ t }: { t: TheoryStory }) {
  const runs = Object.entries(t.runs);
  const gaps = runs.filter(([, r]) => r.gap_eV != null);
  return (
    <div>
      {t.goal && <p className="mb-3 text-[12.5px] text-muted">Goal: “{t.goal}”</p>}
      <Node actor="input" who="structure source" title={`${t.cell.formula} · ${t.cell.spacegroup}`}>
        <div className="font-mono text-[11.5px]">{t.request.structure} · {t.cell.natoms} atoms in the primitive cell
          {t.lattice.a_A && ` · a = ${f(t.lattice.a_A, 4)} Å`}{t.lattice.c_A && `, c = ${f(t.lattice.c_A, 4)} Å`}</div>
      </Node>
      <Node actor={t.planner && t.planner !== "rules" ? "llm" : "code"} who={t.planner && t.planner !== "rules" ? "planner · rules + Claude review" : "planner · rules"}
        title="Settings, each with its reason">
        {t.decisions.length ? <ul className="space-y-0.5">{t.decisions.map((x) => (
          <li key={x.field}><span className="text-muted">{x.field}</span> <span className="font-mono">{x.value}</span>
            <span className="text-[11px] text-faint"> — {x.reason} ({SOURCE[x.source] ?? x.source})</span></li>))}</ul>
          : <div>Set made from explicit settings: {t.request.functional}, k {t.request.kmesh.join("×")}.</div>}
        {t.warnings.map((w) => <div key={w} className="text-warn">{w}</div>)}
      </Node>
      <Node actor="code" who="code adapters · read-back checks" title={`Inputs for ${Object.keys(t.codes).length} codes, each read back`}
        status={t.checks.passed ? "done" : "failed"}>
        <div>{t.checks.n_passed} checks passed{t.checks.n_not_run ? `, ${t.checks.n_not_run} could not run here` : ""}: same crystal, same k-mesh, the requested functional in every code.</div>
        {t.checks.failed.map((x) => <div key={x.check} className="text-bad">{x.check}: {x.detail}</div>)}
      </Node>
      <Node actor="program" who="DFT codes, one after another" title="Self-consistent calculations">
        {runs.length ? <table className="tabular w-full text-[12px]"><tbody className="divide-y divide-line">
          {runs.map(([c, r]) => <tr key={c}><td className="py-1 font-medium">{r.label}</td>
            <td><Status status={r.status === "completed" ? "done" : r.status} /></td>
            <td className="text-muted">{r.iterations ? `${r.iterations} iterations` : ""}</td>
            <td className="font-mono">{r.gap_eV != null ? `gap ${r.gap_eV.toFixed(3)} eV` : ""}</td></tr>)}
        </tbody></table> : <div className="text-muted">Not run yet (Runs tab of the set).</div>}
        {runs.filter(([, r]) => r.healed).map(([c, r]) => <div key={c} className="text-[11.5px] text-warn">{r.label}: {r.healed!.error} → {r.healed!.change} ({r.healed!.why})</div>)}
        {Object.keys(t.codes).filter((c) => !t.runs[c]).length > 0 && <div className="text-[11.5px] text-muted">
          Inputs only (no program here): {Object.keys(t.codes).filter((c) => !t.runs[c]).map((c) => t.codes[c]).join(", ")}</div>}
      </Node>
      <Node actor="result" who="from the codes' own output" title="Band gap" last>
        {gaps.length ? <div className="font-mono text-[12px]">{gaps.map(([, r]) => `${r.label} ${r.gap_eV!.toFixed(2)}`).join(" · ")} eV</div>
          : <div className="text-muted">No gap yet.</div>}
        {t.reference?.band_gap_eV != null && <div className="text-[11.5px] text-muted">Materials Project (PBE): {t.reference.band_gap_eV} eV.
          {" "}Gaps on a k-mesh are an upper bound on the true minimum gap; LDA and PBE underestimate measured gaps.</div>}
      </Node>
    </div>
  );
}

function Meet({ experiment, theory, material }: { experiment: ExperimentStory[]; theory: TheoryStory[]; material: string }) {
  const exp = experiment.find((e) => e.result.a_refined?.value != null);
  const th = theory.find((t) => t.lattice.a_A != null);
  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <h2 className="text-[13px] font-semibold">Where the two meet</h2>
      {exp && th ? (
        <div className="mt-2 text-[13px] leading-6">
          The calculation assumed a = <span className="font-mono">{f(th.lattice.a_A, 4)} Å</span> ({th.request.structure}); the measurement
          ({ENGINE[exp.engine]}, {exp.run}) gives <span className="font-mono">{f(exp.result.a_refined!.value, 5)} Å</span>, a difference of{" "}
          <span className="font-mono">{(100 * (th.lattice.a_A! / exp.result.a_refined!.value! - 1)).toFixed(2)} %</span>.
          <p className="text-[12px] text-muted">{th.request.structure.startsWith("mp:")
            ? "Materials Project structures are relaxed with PBE, which makes crystals slightly too large, so a small positive difference is expected."
            : "This structure comes from a measurement (COD), so the difference is between two experiments, at their own temperatures."}</p>
        </div>
      ) : <p className="mt-1 text-[12.5px] text-muted">
        {!exp && !th ? `Nothing for ${material} on either side yet.`
          : !exp ? `There is no refined measurement of ${material} yet, so the theory side stands alone. Add a measured scan in Storage to compare.`
          : `There is no DFT set for ${material} yet; generate one under Theory · DFT to compare.`}</p>}
    </section>
  );
}
