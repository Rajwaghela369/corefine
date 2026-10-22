import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { dft, type DftJob, type StudyPoint } from "../api/client";
import { Button, Empty, num } from "../components/ui";

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
