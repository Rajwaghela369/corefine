import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { dft, type ConvSeries, type DftJob, type StudyPoint } from "../api/client";
import { Legend, Node } from "../components/Flow";
import { Button, Empty, Status, cn, num } from "../components/ui";

const COLORS: Record<string, string> = { espresso: "#1f4fd1", questaal: "#c2410c", exciting: "#15803d", vasp: "#7c3aed",
  gpaw: "#0e7490", abinit: "#b45309", siesta: "#be185d", wien2k: "#121826" };
const color = (c: string) => COLORS[c] ?? "#6b7484";

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
  const r = st?.reasoning;
  const labels = Object.fromEntries(Object.entries(job.provenance.generated).map(([c, g]) => [c, g.label]));
  const running = st?.status === "running" || st?.status === "queued";
  return (
    <div className="flex h-full flex-col">
      <StudyHeader job={job} kind="convergence" label="convergence" note="k-mesh series, then basis series; installed codes only" />
      {!st || !r ? <Empty title="No convergence study yet">Runs each installed code over increasing k-meshes and then basis sizes, and
        shows for every code how it decided which setting is enough: each point, its distance from the most accurate one, and the reason.</Empty> : (
        <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="max-w-3xl space-y-1 text-[12.5px] leading-5 text-ink-2"><p>{r.criterion}</p><p className="text-muted">{r.plan}</p></div>
            <Legend />
          </div>
          <div className={cn("grid gap-4", Object.keys(r.codes).length >= 2 && "lg:grid-cols-2", Object.keys(r.codes).length >= 3 && "2xl:grid-cols-3")}>
            {Object.entries(r.codes).map(([code, e]) => (
              <section key={code} className="rounded-lg border border-line bg-surface">
                <header className="flex items-center gap-2 border-b border-line px-4 py-2.5">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: color(code) }} />
                  <h2 className="text-[13px] font-semibold">{labels[code] ?? code}</h2>
                  <span className="ml-auto"><Status status={e.done ? "done" : running ? "running" : "failed"} /></span>
                </header>
                <div className="p-4">
                  <Node actor="code" who="study plan · code" title="What is tried, and in which order">
                    <div>k-mesh first (basis at the default), then the basis at the chosen k-mesh.</div>
                    <div className="text-muted">Basis here means: {e.basis_parameter}.</div>
                  </Node>
                  <Node actor="program" who={`${labels[code] ?? code}, one run per point`} title="k-mesh series"
                    status={e.kpoints.rows.length ? undefined : running ? "running" : undefined}><SeriesTable s={e.kpoints} /></Node>
                  <Node actor="result" who="rule · code" title={`k-mesh: ${e.kpoints.chosen ?? "not confirmed"}`}>
                    <div className={cn(!e.kpoints.chosen && "text-warn")}>{e.kpoints.verdict}</div></Node>
                  <Node actor="program" who={`${labels[code] ?? code}, at that k-mesh`} title="Basis series"><SeriesTable s={e.basis} /></Node>
                  <Node actor="result" who="rule · code" title={`Basis: ${e.basis.chosen ?? "not confirmed"}`}>
                    <div className={cn(!e.basis.chosen && "text-warn")}>{e.basis.verdict}</div></Node>
                  <Node actor="result" who="for runs and studies of this set" title="Settings to use" last>
                    <div className="font-mono text-[12px]">{e.use}</div></Node>
                </div>
              </section>))}
          </div>
          <section className="rounded-lg border border-line bg-surface">
            <header className="border-b border-line px-4 py-2"><h3 className="text-[12.5px] font-semibold">The codes side by side</h3>
              <p className="text-[11px] text-muted">distance from each code's own most accurate point, per atom (log scale); the faster a curve
                falls below {st.tol_meV_per_atom} meV/atom, the cheaper that code converges</p></header>
            <div className="grid gap-4 p-3 lg:grid-cols-2">
              {(["kpoints", "basis"] as const).map((series) => (
                <div key={series}>
                  <div className="mb-0.5 text-[12px] font-medium">{series === "kpoints" ? "k-mesh" : "basis"}</div>
                  <Chart logY xLabel={series === "kpoints" ? "k-points along a" : "basis scale"} yLabel="meV/atom"
                    series={Object.entries(st.codes).map(([c, e]) => {
                      const pts = e[series] as (StudyPoint & { kmesh?: number[]; basis_scale?: number })[];
                      const ref = pts.at(-1)?.e_per_atom_eV;
                      return { name: c, dots: true, pts: pts.slice(0, -1).filter((p) => p.ok && ref != null)
                        .map((p) => [series === "kpoints" ? p.kmesh![0] : p.basis_scale!, Math.abs(p.e_per_atom_eV! - ref!) * 1000] as [number, number]) };
                    })} />
                  <div className="mt-1 flex flex-wrap gap-3 text-[11px]">{Object.keys(st.codes).map((c) => <span key={c} className="inline-flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full" style={{ background: color(c) }} />{labels[c] ?? c}</span>)}</div>
                </div>))}
            </div>
            <table className="mx-3 mb-3 w-[calc(100%-1.5rem)] text-[12px]">
              <thead className="text-left text-[11px] text-muted"><tr><th className="py-1">Code</th><th>k-mesh</th><th>basis</th><th>basis parameter</th></tr></thead>
              <tbody className="divide-y divide-line">{Object.entries(r.codes).map(([c, e]) => (
                <tr key={c}><td className="py-1 font-medium" style={{ color: color(c) }}>{labels[c] ?? c}</td>
                  <td className="font-mono">{e.kpoints.chosen ?? <span className="text-warn">not confirmed</span>}</td>
                  <td className="font-mono">{e.basis.chosen ?? <span className="text-warn">not confirmed</span>}</td>
                  <td className="text-[11px] text-muted">{e.basis_parameter}</td></tr>))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}

function SeriesTable({ s }: { s: ConvSeries }) {
  if (!s.rows.length) return <div className="text-muted">Not run yet.</div>;
  return (
    <table className="tabular w-full text-[12px]">
      <thead className="text-left text-[10.5px] text-muted"><tr><th className="py-0.5 font-medium">setting</th><th className="font-medium">E (eV/atom)</th>
        <th className="font-medium">Δ to most accurate</th><th className="font-medium">change</th><th className="font-medium">SCF</th></tr></thead>
      <tbody className="divide-y divide-line font-mono">
        {s.rows.map((r) => (
          <tr key={r.setting} className={cn(r.setting === s.chosen && "bg-ok-soft")}>
            <td className="py-0.5">{r.setting}{r.setting === s.chosen && <span className="ml-1 font-sans text-[10px] text-ok">chosen</span>}</td>
            {r.ok ? <>
              <td>{r.e_per_atom_eV?.toFixed(5)}</td>
              <td className={cn(r.is_reference ? "text-muted" : r.within ? "text-ok" : "text-warn")}>
                {r.is_reference ? "reference" : `${r.delta_to_most_accurate_meV?.toFixed(3)} meV`}</td>
              <td className="text-muted">{r.change_from_previous_meV != null ? `${r.change_from_previous_meV.toFixed(3)}` : ""}</td>
              <td className="text-muted">{r.scf_iterations ?? ""}{r.healed ? " ⟳" : ""}</td>
            </> : <td colSpan={4} className="font-sans text-[11px] text-bad">{r.error ?? "failed"}</td>}
          </tr>))}
      </tbody>
    </table>
  );
}
