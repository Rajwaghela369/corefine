import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Play } from "lucide-react";
import { useState } from "react";
import { api, dft, type DftJob, type EosFit, type StudyPoint } from "../api/client";
import { Button, Empty, Tag, num } from "../components/ui";

const COLORS: Record<string, string> = { espresso: "#1f4fd1", questaal: "#c2410c", exciting: "#15803d", vasp: "#7c3aed",
  gpaw: "#0e7490", abinit: "#b45309", siesta: "#be185d", wien2k: "#121826" };
const color = (c: string) => COLORS[c] ?? "#6b7484";
const GPA = 1 / 160.21766208;  // eV/Å³ per GPa

function StudyHeader({ job, kind, label, note }: { job: DftJob; kind: "convergence" | "eos"; label: string; note: string }) {
  const qc = useQueryClient();
  const st = job.studies?.[kind];
  const go = useMutation({ mutationFn: () => dft.startStudy(job.id, kind), onSettled: () => qc.invalidateQueries({ queryKey: ["dft-job", job.id] }) });
  const running = st?.status === "running" || st?.status === "queued";
  return (
    <div className="flex items-center gap-2 border-b border-line px-3 py-2 text-xs">
      <span className="text-muted">{note}</span>
      {running && <span className="text-accent">{st?.message || "running…"}</span>}
      {st?.status === "failed" && <span className="text-bad">{st.message}</span>}
      <Button size="sm" variant="secondary" className="ml-auto" disabled={running || go.isPending} onClick={() => go.mutate()}>
        <Play size={11} /> {st ? `Rerun ${label}` : `Run ${label}`}</Button>
    </div>
  );
}

/** Small SVG line chart; series share axes. */
export function Chart({ series, xLabel, yLabel, logY, height = 170 }: { series: { name: string; pts: [number, number][]; dashed?: boolean; dots?: boolean }[];
  xLabel: string; yLabel: string; logY?: boolean; height?: number }) {
  const all = series.flatMap((s) => s.pts).filter(([, y]) => !logY || y > 0);
  if (!all.length) return null;
  const W = 420, H = height, L = 46, R = 8, T = 8, B = 28;
  const xs = all.map((p) => p[0]), ys = all.map((p) => (logY ? Math.log10(p[1]) : p[1]));
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)], [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  const sx = (x: number) => L + ((x - x0) / (x1 - x0 || 1)) * (W - L - R);
  const sy = (y: number) => H - B - (((logY ? Math.log10(y) : y) - y0) / (y1 - y0 || 1)) * (H - T - B);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto block w-full max-w-[620px]">
      <line x1={L} y1={H - B} x2={W - R} y2={H - B} stroke="#cfd4dc" /><line x1={L} y1={T} x2={L} y2={H - B} stroke="#cfd4dc" />
      <text x={W / 2} y={H - 6} fontSize="10" textAnchor="middle" fill="#6b7484">{xLabel}</text>
      <text x={10} y={H / 2} fontSize="10" textAnchor="middle" fill="#6b7484" transform={`rotate(-90 10 ${H / 2})`}>{yLabel}</text>
      {[y0, (y0 + y1) / 2, y1].map((v, i) => <text key={i} x={L - 4} y={H - B - ((v - y0) / (y1 - y0 || 1)) * (H - T - B) + 3}
        fontSize="9" textAnchor="end" fill="#9aa2b0">{logY ? `1e${v.toFixed(1)}` : v.toFixed(v > 10 ? 0 : 2)}</text>)}
      {[x0, x1].map((v, i) => <text key={i} x={sx(v)} y={H - B + 11} fontSize="9" textAnchor="middle" fill="#9aa2b0">{num(v, 4)}</text>)}
      {series.map((s) => {
        const pts = s.pts.filter(([, y]) => !logY || y > 0);
        return <g key={s.name}>
          <polyline fill="none" stroke={color(s.name)} strokeWidth={1.5} strokeDasharray={s.dashed ? "4 3" : undefined}
            points={pts.map(([x, y]) => `${sx(x)},${sy(y)}`).join(" ")} />
          {s.dots && pts.map(([x, y], i) => <circle key={i} cx={sx(x)} cy={sy(y)} r={2.5} fill={color(s.name)} />)}
        </g>;
      })}
    </svg>
  );
}

export function ConvergencePane({ job }: { job: DftJob }) {
  const st = job.studies?.convergence;
  return (
    <div className="flex h-full flex-col">
      <StudyHeader job={job} kind="convergence" label="convergence" note="k-mesh series, then basis series; installed codes only" />
      {!st ? <Empty title="No convergence study yet">Runs each installed code over increasing k-meshes and basis sizes and picks the
        cheapest setting within 1 meV/atom of the most accurate one.</Empty> : (
        <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3 text-xs">
          <p className="text-muted">Criterion: {st.criterion}. A setting only counts if a more accurate point confirms it.</p>
          {(["kpoints", "basis"] as const).map((series) => (
            <div key={series}>
              <div className="mb-0.5 font-medium">{series === "kpoints" ? "k-points" : "basis"}: |E − E<sub>most accurate</sub>| per atom</div>
              <Chart logY xLabel={series === "kpoints" ? "k-points along a" : "basis scale"} yLabel="meV/atom"
                series={Object.entries(st.codes).map(([c, e]) => {
                  const pts = e[series] as (StudyPoint & { kmesh?: number[]; basis_scale?: number })[];
                  const ref = pts.at(-1)?.e_per_atom_eV;
                  return { name: c, dots: true, pts: pts.slice(0, -1).filter((p) => p.ok && ref != null)
                    .map((p) => [series === "kpoints" ? p.kmesh![0] : p.basis_scale!, Math.abs(p.e_per_atom_eV! - ref!) * 1000] as [number, number]) };
                })} />
            </div>
          ))}
          <table className="w-full">
            <thead className="text-left text-[11px] text-muted"><tr><th className="py-1">Code</th><th>converged k-mesh</th><th>converged basis</th><th>basis parameter</th></tr></thead>
            <tbody className="divide-y divide-line">{Object.entries(st.codes).map(([c, e]) => (
              <tr key={c}><td className="py-1 font-medium" style={{ color: color(c) }}>{c}</td>
                <td className="font-mono">{e.converged_kmesh ? e.converged_kmesh.join("×") : <span className="text-warn">not within series</span>}</td>
                <td className="font-mono">{e.converged_basis_scale != null ? `×${e.converged_basis_scale}` : <span className="text-warn">not within series</span>}</td>
                <td className="text-[11px] text-muted">{(e as unknown as { basis_parameter?: string }).basis_parameter}</td></tr>))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function EosHeader({ job }: { job: DftJob }) {
  const qc = useQueryClient();
  const st = job.studies?.eos;
  const [k, setK] = useState(["", "", ""]);
  const custom = k.every((v) => Number(v) >= 1) ? k.map(Number) : null;
  const go = useMutation({ mutationFn: () => dft.startStudy(job.id, "eos", custom), onSettled: () => qc.invalidateQueries({ queryKey: ["dft-job", job.id] }) });
  const running = st?.status === "running" || st?.status === "queued";
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2 text-xs">
      <span className="text-muted">7 volumes 94–106 %, Birch–Murnaghan.</span>
      <span className="text-muted">k-mesh:</span>
      {k.map((v, i) => <input key={i} value={v} placeholder="–" onChange={(e) => setK(k.map((x, j) => (j === i ? e.target.value.replace(/\D/g, "") : x)))}
        className="h-7 w-10 rounded border border-line-strong px-1 text-center font-mono" />)}
      <span className="text-[11px] text-faint">{custom ? "yours, for every code" : "blank = converged per code (else the plan's)"}</span>
      {running && <span className="text-accent">{st?.message || "running…"}</span>}
      {st?.status === "failed" && <span className="text-bad">{st.message}</span>}
      <Button size="sm" variant="secondary" className="ml-auto" disabled={running || go.isPending} onClick={() => go.mutate()}>
        <Play size={11} /> {st ? "Rerun" : "Run"} equation of state</Button>
    </div>
  );
}

function bm(v: number, f: { V0_A3_per_atom: number; B0_GPa: number; B0_prime: number }) {
  const eta = (f.V0_A3_per_atom / v) ** (2 / 3), b = f.B0_GPa * GPA;
  return (9 * f.V0_A3_per_atom * b / 16) * ((eta - 1) ** 3 * f.B0_prime + (eta - 1) ** 2 * (6 - 4 * eta));
}

export function EosPane({ job }: { job: DftJob }) {
  const qc = useQueryClient();
  const st = job.studies?.eos;
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  const save = useMutation({ mutationFn: (code: string) => dft.saveEos(job.id, code), onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }) });
  const xrdRuns = (runs.data ?? []).filter((r) => r.status === "done" && r.headline);
  const formula = job.provenance.cell.formula.replace(/\d/g, "");
  const ref = (st as unknown as { reference?: EosFit & { source: string; a0_conventional_A?: number } } | undefined)?.reference;
  return (
    <div className="flex h-full flex-col">
      <EosHeader job={job} />
      {!st ? <Empty title="No equation of state yet">Runs every installed code at seven volumes, fits V₀, B₀, B′ and compares codes
        with the Delta gauge (and with WIEN2k for elemental crystals).</Empty> : (
        <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3 text-xs">
          <Chart xLabel="volume (Å³/atom)" yLabel="E − E₀ (meV/atom)"
            series={[...Object.entries(st.codes).flatMap(([c, e]) => e.fit ? [
              { name: c, dots: true, pts: e.points.filter((p) => p.ok).map((p) => [p.volume_per_atom_A3!, (p.e_per_atom_eV! - e.fit!.E0_eV_per_atom) * 1000] as [number, number]) },
            ] : []),
            ...(ref ? [{ name: "wien2k", dashed: true, pts: Array.from({ length: 41 }, (_, i) => {
              const v = ref.V0_A3_per_atom * (0.94 + 0.003 * i); return [v, bm(v, ref) * 1000] as [number, number]; }) }] : [])]} />
          <table className="tabular w-full">
            <thead className="text-left text-[11px] text-muted"><tr><th className="py-1">Code</th><th>V₀ (Å³/atom)</th><th>a₀ (Å)</th><th>B₀ (GPa)</th><th>B′</th><th>settings</th><th /></tr></thead>
            <tbody className="divide-y divide-line">
              {Object.entries(st.codes).map(([c, e]) => (
                <tr key={c}><td className="py-1 font-medium" style={{ color: color(c) }}>{c}</td>
                  {e.fit ? <><td className="font-mono">{e.fit.V0_A3_per_atom.toFixed(4)}</td>
                    <td className="font-mono">{(e.fit as EosFit & { a0_conventional_A?: number }).a0_conventional_A?.toFixed(4) ?? "—"}</td>
                    <td className="font-mono">{e.fit.B0_GPa.toFixed(1)}</td><td className="font-mono">{e.fit.B0_prime.toFixed(2)}</td></>
                    : <td colSpan={4} className="text-bad">{e.error}</td>}
                  <td className="text-[10.5px] text-muted">k {e.settings.kmesh.join("×")}, basis ×{e.settings.basis_scale}{e.settings.from_convergence ? " (converged)" : ""}</td>
                  <td>{e.fit && <Button size="sm" variant="ghost" title="Save the equilibrium structure to Storage" onClick={() => save.mutate(c)}><Database size={11} /></Button>}</td></tr>
              ))}
              {ref && <tr><td className="py-1 font-medium">WIEN2k</td><td className="font-mono">{ref.V0_A3_per_atom.toFixed(4)}</td>
                <td className="font-mono">{ref.a0_conventional_A?.toFixed(4) ?? "—"}</td><td className="font-mono">{ref.B0_GPa.toFixed(1)}</td>
                <td className="font-mono">{ref.B0_prime.toFixed(2)}</td><td className="text-[10.5px] text-muted" colSpan={2}>all-electron reference (Delta project)</td></tr>}
            </tbody>
          </table>
          {Object.keys(st.delta_meV_per_atom).length > 0 && <div>
            <div className="mb-1 font-medium">Δ gauge between codes (meV/atom; below about 1 = agreement)</div>
            <div className="flex flex-wrap gap-1.5">{Object.entries(st.delta_meV_per_atom).map(([k, v]) => (
              <Tag key={k} tone={v < 1 ? "ok" : v < 2 ? "warn" : "bad"}>{k.replace("|", " vs ")}: {v.toFixed(2)}</Tag>))}</div>
          </div>}
          {save.isSuccess && <p className="text-ok">Saved to Storage as {save.data.dataset}.</p>}
          {xrdRuns.length > 0 && Object.values(st.codes).some((e) => (e.fit as EosFit & { a0_conventional_A?: number })?.a0_conventional_A) && (
            <div className="rounded-md border border-line bg-subtle/60 p-2">
              <div className="mb-1 font-medium">Against experiment (XRD refinements in this workspace)</div>
              {xrdRuns.slice(0, 3).map((r) => (
                <div key={r.id} className="flex flex-wrap gap-x-3 text-[11.5px]"><span className="font-mono">{r.id}</span>
                  <span>a = <span className="font-mono">{r.headline!.a_refined.toFixed(6)} Å</span></span>
                  {Object.entries(st.codes).map(([c, e]) => {
                    const a0 = (e.fit as EosFit & { a0_conventional_A?: number })?.a0_conventional_A;
                    return a0 ? <span key={c} style={{ color: color(c) }}>{c}: {((a0 / r.headline!.a_refined - 1) * 100).toFixed(2)} %</span> : null;
                  })}
                </div>))}
              <p className="mt-1 text-[10.5px] text-muted">For {formula}. PBE is known to overestimate lattice constants; the XRD value is at the scan
                temperature and includes zero-point motion, the DFT value is static.</p>
            </div>)}
        </div>
      )}
    </div>
  );
}



const RAMAN_CODES = [["espresso", "Quantum ESPRESSO"], ["gpaw", "GPAW"]] as const;

export function RamanPane({ job }: { job: DftJob }) {
  const qc = useQueryClient();
  const studies = job.studies?.raman ?? {};
  const [code, setCode] = useState<string>("espresso");
  const [exp, setExp] = useState("");
  const go = useMutation({ mutationFn: () => dft.startRaman(job.id, code), onSettled: () => qc.invalidateQueries({ queryKey: ["dft-job", job.id] }) });
  const running = Object.values(studies).some((s) => s.status === "running" || s.status === "queued");
  const expV = Number(exp) || null;
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2 text-xs">
        <span className="text-muted">Γ phonons by finite displacements; Raman/IR activity from symmetry.</span>
        <select value={code} onChange={(e) => setCode(e.target.value)} className="h-7 rounded border border-line-strong px-1.5">
          {RAMAN_CODES.map(([c, l]) => <option key={c} value={c}>{l}</option>)}</select>
        <label className="flex items-center gap-1 text-muted">measured (cm⁻¹)
          <input className="h-7 w-20 rounded border border-line-strong px-1.5 font-mono" value={exp} onChange={(e) => setExp(e.target.value)} placeholder="optional" /></label>
        {running && <span className="text-accent">{Object.values(studies).find((s) => s.status === "running")?.message || "running…"}</span>}
        <Button size="sm" variant="secondary" className="ml-auto" disabled={running || go.isPending} onClick={() => go.mutate()}><Play size={11} /> Run Raman</Button>
      </div>
      {!Object.keys(studies).length ? <Empty title="No Raman calculation yet">Displaces each atom of the cell, computes forces with the chosen
        code (one short run per displacement), builds the force constants with phonopy and finds the Γ modes. Symmetry decides which are
        Raman- or IR-active.</Empty> : (
        <div className="min-h-0 flex-1 space-y-3 overflow-auto p-3 text-xs">
          <Chart xLabel="Raman shift (cm⁻¹)" yLabel="active modes (positions only)"
            series={Object.entries(studies).filter(([, s]) => s.spectrum).map(([c, s]) => ({ name: c,
              pts: s.spectrum!.x.map((x, i) => [x, s.spectrum!.y[i]] as [number, number]).filter((_, i) => i % 4 === 0) }))} />
          {Object.entries(studies).map(([c, s]) => (
            <div key={c} className="rounded-md border border-line">
              <div className="flex items-center gap-2 border-b border-line px-2.5 py-1.5">
                <span className="font-medium" style={{ color: color(c) }}>{c}</span>
                <span className="text-muted">point group {s.point_group ?? "—"} · k {s.kmesh?.join("×")} · {s.n_displacements} displacement(s)</span>
                {s.status !== "done" && <span className={s.status === "failed" ? "text-bad" : "text-accent"}>{s.status} {s.message}</span>}
              </div>
              {s.modes && <table className="tabular w-full">
                <thead className="text-left text-[11px] text-muted"><tr><th className="px-2.5 py-1">ω (cm⁻¹)</th><th>irrep</th><th>degeneracy</th><th>Raman</th><th>IR</th>{expV && <th>vs measured</th>}</tr></thead>
                <tbody className="divide-y divide-line">{s.modes.filter((m) => !m.acoustic).map((m, i) => (
                  <tr key={i}><td className="px-2.5 py-1 font-mono">{m.frequency_cm1.toFixed(1)}</td><td>{m.label}</td><td>{m.degeneracy}</td>
                    <td>{m.raman_active ? <Tag tone="ok">active</Tag> : <span className="text-faint">–</span>}</td>
                    <td>{m.ir_active ? <Tag tone="run">active</Tag> : <span className="text-faint">–</span>}</td>
                    {expV && <td className="font-mono">{m.raman_active ? `${((m.frequency_cm1 / expV - 1) * 100).toFixed(1)} %` : ""}</td>}</tr>))}
                </tbody></table>}
              {s.notes && <p className="px-2.5 py-1.5 text-[10.5px] text-muted">{s.notes.join(" · ")}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
