import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Atom, FlaskConical, Scale } from "lucide-react";
import { useState } from "react";
import { dft } from "../api/client";
import { Button, Empty, Tag, inputCls, cn } from "../components/ui";

const COLORS: Record<string, string> = { espresso: "#1f4fd1", questaal: "#c2410c", exciting: "#15803d", vasp: "#7c3aed",
  gpaw: "#0e7490", abinit: "#b45309", wien2k: "#121826" };
const LABEL: Record<string, string> = { espresso: "Quantum ESPRESSO", questaal: "Questaal", exciting: "exciting", vasp: "VASP",
  gpaw: "GPAW", abinit: "ABINIT", wien2k: "WIEN2k (reference)" };

/** One material, both worlds: what the XRD refinement measured and what each DFT code predicts. */
export function BridgeView() {
  const [q, setQ] = useState("Si");
  const [material, setMaterial] = useState("Si");
  const b = useQuery({ queryKey: ["bridge", material], queryFn: () => dft.bridge(material) });
  const d = b.data;
  const expA = d?.experiment[0]?.a_A ?? d?.certified[0]?.a_A ?? null;

  return (
    <div className="h-full overflow-auto bg-canvas">
      <div className="mx-auto max-w-6xl space-y-4 p-5">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Theory ↔ Experiment</h1>
            <p className="mt-0.5 max-w-3xl text-[13px] leading-5 text-muted">
              The same question from two directions: an XRD scan measures the crystal, DFT predicts it from first principles.
              Putting them side by side shows how good the theory is, and how much of the gap is physics (temperature, zero-point motion)
              rather than error.</p>
          </div>
          <form className="flex gap-1.5" onSubmit={(e) => { e.preventDefault(); setMaterial(q.trim()); }}>
            <input className={cn(inputCls, "w-28 font-mono")} value={q} onChange={(e) => setQ(e.target.value)} />
            <Button type="submit" variant="secondary">Show</Button>
          </form>
        </div>

        <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr_auto_1fr]">
          <Pillar icon={FlaskConical} title="Experiment (XRD workflow)" color="#121826"
            text="An agent pipeline reads the measured scan, fits every peak, refines the lattice parameter and writes a report in which every number is traced to a file." />
          <ArrowRight className="hidden self-center text-faint md:block" />
          <Pillar icon={Scale} title="Bridge" color="#1f4fd1"
            text="Simulated patterns of computed structures overlaid on the scan; lattice difference, strain and the pressure that would close the gap; phase identification against Materials Project." />
          <ArrowRight className="hidden self-center text-faint md:block" />
          <Pillar icon={Atom} title="Theory (DFT workflow)" color="#c2410c"
            text="The same crystal from Materials Project, inputs for every code checked against each other, converged settings, equation of state, phonons and Raman lines." />
        </div>

        {b.isError && <p className="text-sm text-bad">{String(b.error)}</p>}
        {d && !d.theory.length && !d.experiment.length && !d.certified.length && <div className="rounded-lg border border-line bg-surface">
          <Empty title={`Nothing for ${material} yet`}>Run an XRD refinement on a measured scan of {material}, and a DFT set with an equation of
            state for the same material; they appear here together.</Empty></div>}

        {d && (d.theory.length > 0 || expA) && (
          <section className="rounded-lg border border-line bg-surface">
            <header className="border-b border-line px-4 py-2.5"><h2 className="text-[13px] font-semibold">Lattice constant</h2>
              <p className="text-[11.5px] text-muted">Experiment: {d.experiment_reference ?? "none yet"}. Theory: equilibrium of each code's equation of state.</p></header>
            <div className="p-4">
              <NumberLine expA={expA} certified={d.certified[0]?.a_A ?? null} points={d.theory.map((t) => ({ name: t.code, a: t.a0_A }))} />
              <div className="mt-1 flex flex-wrap gap-3 text-[11.5px]">
                <span className="inline-flex items-center gap-1.5"><span className="h-3 w-0.5 bg-ink" />experiment (XRD)</span>
                {d.certified.length > 0 && <span className="inline-flex items-center gap-1.5"><span className="h-3 w-0 border-l border-dashed border-ink" />certified</span>}
                {d.theory.map((t, i) => <span key={i} className="inline-flex items-center gap-1.5">
                  <span className="size-2.5 rounded-full" style={{ background: COLORS[t.code] }} />{LABEL[t.code] ?? t.code}</span>)}
              </div>
              <table className="tabular mt-4 w-full text-[12.5px]">
                <thead className="text-left text-[11px] text-muted"><tr><th className="py-1">Source</th><th>a (Å)</th><th>vs experiment</th>
                  <th>pressure to match</th><th>details</th></tr></thead>
                <tbody className="divide-y divide-line">
                  {d.experiment.slice(0, 1).map((e) => <tr key={e.run}><td className="py-1.5 font-medium">XRD refinement</td>
                    <td className="font-mono">{e.a_A.toFixed(6)}{e.uncertainty_A ? ` ± ${e.uncertainty_A.toFixed(6)}` : ""}</td><td>—</td><td>—</td>
                    <td className="text-muted">{e.run}{e.temperature_C != null ? ` · scan at ${e.temperature_C.toFixed(1)} °C` : ""}</td></tr>)}
                  {d.certified.slice(0, 1).map((c) => <tr key={c.dataset}><td className="py-1.5 font-medium">Certified</td>
                    <td className="font-mono">{c.a_A.toFixed(6)}{c.uncertainty_A ? ` ± ${c.uncertainty_A}` : ""}</td>
                    <td className="font-mono">{expA ? `${((c.a_A / expA - 1) * 100).toFixed(4)} %` : "—"}</td><td>—</td>
                    <td className="text-muted">{c.temperature_C != null ? `at ${c.temperature_C} °C · ` : ""}{c.source}</td></tr>)}
                  {d.theory.map((t, i) => <tr key={i}><td className="py-1.5 font-medium" style={{ color: COLORS[t.code] }}>{LABEL[t.code] ?? t.code}</td>
                    <td className="font-mono">{t.a0_A.toFixed(4)}</td>
                    <td className="font-mono">{t.vs_experiment_percent != null ? `${t.vs_experiment_percent >= 0 ? "+" : ""}${t.vs_experiment_percent.toFixed(2)} %` : "—"}</td>
                    <td className="font-mono">{t.pressure_equivalent_GPa != null ? `${t.pressure_equivalent_GPa.toFixed(2)} GPa` : "—"}</td>
                    <td className="text-muted">{t.functional}{t.kmesh ? ` · k ${t.kmesh.join("×")}` : ""}{t.B0_GPa ? ` · B₀ ${t.B0_GPa.toFixed(0)} GPa` : ""}</td></tr>)}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {d && d.raman.length > 0 && (
          <section className="rounded-lg border border-line bg-surface">
            <header className="border-b border-line px-4 py-2.5"><h2 className="text-[13px] font-semibold">Vibrations (Γ phonons)</h2>
              <p className="text-[11.5px] text-muted">Computed optical modes and whether symmetry lets them appear in Raman or IR spectra.</p></header>
            <div className="flex flex-wrap gap-2 p-4">
              {d.raman.map((r, i) => <div key={i} className="rounded-md border border-line px-3 py-2">
                <div className="text-[11px]" style={{ color: COLORS[r.code] }}>{LABEL[r.code] ?? r.code} · {r.functional}</div>
                <div className="tabular font-mono text-[17px]">{r.frequency_cm1.toFixed(1)} <span className="text-xs text-muted">cm⁻¹</span></div>
                <div className="mt-0.5 flex gap-1">{r.label && <Tag>{r.label}</Tag>}{r.raman_active && <Tag tone="ok">Raman</Tag>}{r.ir_active && <Tag tone="run">IR</Tag>}</div>
              </div>)}
            </div>
          </section>
        )}

        {d && <ul className="list-disc space-y-1 pl-5 text-[12px] text-muted">{d.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      </div>
    </div>
  );
}

function Pillar({ icon: Icon, title, text, color }: { icon: typeof Atom; title: string; text: string; color: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3.5">
      <div className="mb-1.5 flex items-center gap-2 text-[13px] font-semibold" style={{ color }}><Icon size={16} /> {title}</div>
      <p className="text-[12.5px] leading-5 text-ink-2">{text}</p>
    </div>
  );
}

/** Every value on one axis: experiment as a band, codes as dots. */
function NumberLine({ expA, certified, points }: { expA: number | null; certified: number | null; points: { name: string; a: number }[] }) {
  const vals = [...points.map((p) => p.a), ...(expA ? [expA] : []), ...(certified ? [certified] : [])];
  if (!vals.length) return null;
  const lo = Math.min(...vals), hi = Math.max(...vals), pad = (hi - lo || 0.01) * 0.12;
  const W = 900, L = 20, R = 20;
  const sx = (v: number) => L + ((v - (lo - pad)) / (hi - lo + 2 * pad)) * (W - L - R);
  return (
    <svg viewBox={`0 0 ${W} 96`} className="w-full">
      <line x1={L} x2={W - R} y1={60} y2={60} stroke="#cfd4dc" />
      {[lo - pad, (lo + hi) / 2, hi + pad].map((v, i) => <text key={i} x={sx(v)} y={84} fontSize="11" textAnchor="middle" fill="#9aa2b0">{v.toFixed(4)} Å</text>)}
      {expA && <g><line x1={sx(expA)} x2={sx(expA)} y1={14} y2={70} stroke="#121826" strokeWidth={2} />
        <text x={sx(expA) + 4} y={22} fontSize="11" fill="#121826">experiment</text></g>}
      {certified && Math.abs((certified - (expA ?? 0))) > 1e-6 && <line x1={sx(certified)} x2={sx(certified)} y1={30} y2={70} stroke="#121826" strokeDasharray="3 3" />}
      {points.map((p, i) => <circle key={i} cx={sx(p.a)} cy={60} r={6} fill={COLORS[p.name] ?? "#6b7484"} stroke="white" strokeWidth={1.5}>
        <title>{LABEL[p.name] ?? p.name}: {p.a.toFixed(4)} Å</title></circle>)}
    </svg>
  );
}
